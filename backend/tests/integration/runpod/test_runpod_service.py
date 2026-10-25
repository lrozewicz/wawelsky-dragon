"""Usługa RunPod na bazie: klucz, katalog, wdrożenie, stany poda, parsowanie i kasowanie."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.container import Container
from app.core.errors import Conflict, PermissionDenied, ValidationFailed
from app.db.repositories import documents as documents_repo
from app.db.repositories import models as models_repo
from app.db.uow import transaction
from app.domain.policy import Principal
from app.services.runpod import lifecycle
from app.services.runpod.client import RunpodClient
from app.services.runpod.guard import ensure_pod_ready
from app.services.runpod.keystore import client_for
from app.services.runpod.service import GpuUnavailable, RunpodService
from app.worker.errors import PermanentError
from tests.fakes.runpod import FakeRunpod
from tests.integration.ingest.conftest import make_document_row, seed_dataset

pytestmark = pytest.mark.db

MODEL = "xiaomi-ocr-0-runpod"
A40 = "NVIDIA A40"
RTX_4090 = "NVIDIA GeForce RTX 4090"
MIN_VRAM = 16
MAX_CONCURRENCY = 16


async def _with_key(container: Container, admin: Principal) -> RunpodService:
    service = RunpodService(container)
    await service.set_key(admin, "rpa_test")
    return service


async def _tick(container: Container, fake: FakeRunpod, *, advance_s: int = 20) -> None:
    container.clock.advance(advance_s * 1000)  # type: ignore[attr-defined]
    await lifecycle.tick(container)


@pytest.fixture(autouse=True)
def healthy(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    """Zdrowie vLLM sterowane z testu (zamiast prawdziwego GET /health)."""
    state = {"ok": False}

    async def fake_health(_: str) -> bool:
        return state["ok"]

    monkeypatch.setattr(lifecycle, "_model_healthy", fake_health)
    return state


async def test_key_is_validated_encrypted_and_masked(
    container: Container, admin: Principal, user: Principal, fake: FakeRunpod
) -> None:
    service = RunpodService(container)
    assert (await service.key_status()) == {"configured": False, "hint": None}
    with pytest.raises(PermissionDenied):
        await service.set_key(user, "rpa_test")
    with pytest.raises(ValidationFailed):
        await service.set_key(admin, "wrong")
    status = await service.set_key(admin, "rpa_test")
    assert status == {"configured": True, "hint": "…test"}
    assert container.sessionmaker is not None
    async with transaction(container.sessionmaker) as session:
        stored = (
            await session.execute(text("SELECT value FROM wd_settings WHERE name='runpod_api_key'"))
        ).scalar_one()
    assert "rpa_test" not in stored
    client = await client_for(container)
    assert isinstance(client, RunpodClient)


async def test_catalog_requires_superuser_and_filters(
    container: Container, admin: Principal, user: Principal
) -> None:
    service = await _with_key(container, admin)
    with pytest.raises(PermissionDenied):
        await service.catalog(user, model=MODEL)
    data = await service.catalog(admin, model=MODEL, min_vram=16, country="RO", only_available=True)
    ids = [g["id"] for g in data["gpus"]]
    assert ids == ["NVIDIA L4", RTX_4090]
    assert data["regions"] == ["EUROPE", "NORTH_AMERICA"] and "RO" in data["countries"]
    small = await service.catalog(admin, model=MODEL, max_vram=12)
    assert small["gpus"][0]["fits"] is False


async def test_deploy_walks_through_states_and_registers_the_model(
    container: Container, admin: Principal, fake: FakeRunpod, healthy: dict[str, bool]
) -> None:
    service = await _with_key(container, admin)
    sm = container.sessionmaker
    assert sm is not None
    dataset = await seed_dataset(
        sm, parser_config={"layout_recognize": MODEL, "pages": [[1, 100]], "delimiter": "\n"}
    )
    doc = make_document_row(dataset)
    async with transaction(sm) as session:
        await documents_repo.insert(session, doc)

    view = await service.deploy(
        admin, model=MODEL, gpu_id=A40, parse=[{"dataset_id": dataset.id, "document_ids": [doc.id]}]
    )
    assert view["status"] == "provisioning" and view["active"] and view["pending_documents"] == 1
    body = fake.pods["pod0001"]["body"]
    assert body["gpu"]["id"] == A40 and body["image"].startswith("vllm/vllm-openai")
    assert (await service.preflight(admin, dataset.id, [doc.id]))["state"] == "provisioning"

    fake.set_status("pod0001", "RUNNING")
    await _tick(container, fake)
    assert (await service.get(view["id"]))["status"] == "loading"
    healthy["ok"] = True
    await _tick(container, fake)
    ready = await service.get(view["id"])
    assert ready["status"] == "ready" and ready["pending_documents"] == 0

    async with transaction(sm) as session:
        model = await models_repo.get_by_name(session, MODEL, "image2text")
        run = (
            await session.execute(text("SELECT run FROM documents WHERE id=:i"), {"i": doc.id})
        ).scalar_one()
        tasks = (
            await session.execute(
                text("SELECT COUNT(*) FROM tasks WHERE document_id=:i"), {"i": doc.id}
            )
        ).scalar_one()
    assert model is not None and (model.extra or {}).get("max_concurrency") == MAX_CONCURRENCY
    assert run == "1" and tasks == 1  # parsowanie ruszyło samo po gotowości
    await ensure_pod_ready(container, MODEL)  # nie rzuca: pod gotowy
    pre = await service.preflight(admin, dataset.id, [doc.id])
    assert pre["needs_pod"] is False and pre["state"] == "ready"


async def test_pod_is_deleted_only_after_the_work_is_done(
    container: Container, admin: Principal, fake: FakeRunpod, healthy: dict[str, bool]
) -> None:
    service = await _with_key(container, admin)
    sm = container.sessionmaker
    assert sm is not None
    dataset = await seed_dataset(sm, parser_config={"layout_recognize": MODEL, "delimiter": "\n"})
    doc = make_document_row(dataset)
    async with transaction(sm) as session:
        await documents_repo.insert(session, doc)
    view = await service.deploy(
        admin, model=MODEL, gpu_id=A40, parse=[{"dataset_id": dataset.id, "document_ids": [doc.id]}]
    )
    fake.set_status("pod0001", "RUNNING")
    healthy["ok"] = True
    await _tick(container, fake)
    await _tick(container, fake)  # ready
    # zadanie parsowania nadal w kolejce → pod żyje nawet po długiej bezczynności
    await _tick(container, fake, advance_s=600)
    assert (await service.get(view["id"]))["status"] == "ready"
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE tasks SET status='done' WHERE document_id=:i"), {"i": doc.id}
        )
    await _tick(container, fake, advance_s=30)  # jeszcze w zwłoce
    assert (await service.get(view["id"]))["status"] == "ready"
    await _tick(container, fake, advance_s=lifecycle.IDLE_GRACE_S)
    ended = await service.get(view["id"])
    assert ended["status"] == "terminated" and not ended["active"]
    assert fake.pods["pod0001"]["status"] == "TERMINATED"  # DELETE poszedł do RunPod
    with pytest.raises(PermanentError, match="not running on RunPod"):
        await ensure_pod_ready(container, MODEL)
    pre = await service.preflight(admin, dataset.id, [doc.id])
    assert pre["needs_pod"] is True and pre["state"] == "off"
    assert pre["last_gpu"] == {"id": A40, "name": "A40", "vram_gb": 48}


async def test_unavailable_gpu_offers_alternatives_with_at_least_the_vram(
    container: Container, admin: Principal, fake: FakeRunpod
) -> None:
    service = await _with_key(container, admin)
    with pytest.raises(GpuUnavailable) as info:  # A4000 (16 GB): brak w katalogu
        await service.deploy(admin, model=MODEL, gpu_id="NVIDIA RTX A4000")
    alts = info.value.details["alternatives"]  # type: ignore[index]
    assert [a["id"] for a in alts] == ["NVIDIA L4", RTX_4090, A40]
    assert all(a["vram_gb"] >= MIN_VRAM for a in alts)
    assert fake.pods == {}  # nic nie powstało, nic nie kosztuje

    fake.create_error = (500, "There are no instances currently available")
    with pytest.raises(GpuUnavailable) as info2:  # katalog mówi „jest”, RunPod „nie ma”
        await service.deploy(admin, model=MODEL, gpu_id="NVIDIA L4")  # 24 GB
    ids = [a["id"] for a in info2.value.details["alternatives"]]  # type: ignore[index]
    assert ids == [RTX_4090, A40]  # ten sam VRAM albo większy, bez wybranego L4
    recent = await service.list_deployments()
    assert recent[0]["status"] == "failed" and not recent[0]["active"]


async def test_deploy_rules(container: Container, admin: Principal, user: Principal) -> None:
    service = await _with_key(container, admin)
    with pytest.raises(PermissionDenied):
        await service.deploy(user, model=MODEL, gpu_id=A40)
    with pytest.raises(ValidationFailed, match="cannot be hosted"):
        await service.deploy(admin, model="gpt-4", gpu_id=A40)
    with pytest.raises(ValidationFailed, match="at least 16 GB"):
        await service.deploy(admin, model=MODEL, gpu_id="NVIDIA GeForce RTX 3060")
    await service.deploy(admin, model=MODEL, gpu_id=A40)
    with pytest.raises(Conflict, match="already"):
        await service.deploy(admin, model=MODEL, gpu_id=A40)
    with pytest.raises(Conflict, match="Terminate"):
        await service.remove_key(admin)


async def test_manual_terminate_and_pods_that_vanish(
    container: Container, admin: Principal, fake: FakeRunpod
) -> None:
    service = await _with_key(container, admin)
    view = await service.deploy(admin, model=MODEL, gpu_id=A40)
    done = await service.terminate(admin, view["id"])
    assert done["status"] == "terminated" and fake.pods["pod0001"]["status"] == "TERMINATED"
    await service.remove_key(admin)  # nic nie działa → wolno
    assert (await service.key_status())["configured"] is False

    service = await _with_key(container, admin)
    second = await service.deploy(admin, model=MODEL, gpu_id=A40)
    fake.set_status("pod0002", "EXITED")  # RunPod zabił poda
    await _tick(container, fake)
    failed = await service.get(second["id"])
    assert failed["status"] == "failed" and "EXITED" in (failed["error"] or "")


async def test_provisioning_timeout_terminates_the_pod(
    container: Container, admin: Principal, fake: FakeRunpod
) -> None:
    service = await _with_key(container, admin)
    view = await service.deploy(admin, model=MODEL, gpu_id=A40)
    await _tick(container, fake, advance_s=lifecycle.PROVISION_TIMEOUT_S + 5)
    failed = await service.get(view["id"])
    assert failed["status"] == "failed" and "gpu_unavailable" in (failed["error"] or "")
    assert fake.pods["pod0001"]["status"] == "TERMINATED"


async def test_preflight_ignores_other_parsers(container: Container, admin: Principal) -> None:
    service = await _with_key(container, admin)
    sm = container.sessionmaker
    assert sm is not None
    dataset = await seed_dataset(sm)
    doc = make_document_row(dataset)
    async with transaction(sm) as session:
        await documents_repo.insert(session, doc)
    assert await service.preflight(admin, dataset.id, [doc.id]) == {"needs_pod": False}


async def test_queue_parse_waits_for_the_pod_or_starts_at_once(
    container: Container, admin: Principal, fake: FakeRunpod, healthy: dict[str, bool]
) -> None:
    service = await _with_key(container, admin)
    sm = container.sessionmaker
    assert sm is not None
    dataset = await seed_dataset(sm, parser_config={"layout_recognize": MODEL, "delimiter": "\n"})
    docs = [make_document_row(dataset, name=f"d{i}.txt") for i in range(2)]
    async with transaction(sm) as session:
        for doc in docs:
            await documents_repo.insert(session, doc)
    view = await service.deploy(admin, model=MODEL, gpu_id=A40)
    queued = await service.queue_parse(admin, view["id"], dataset.id, [docs[0].id])
    assert queued["pending_documents"] == 1  # czeka na gotowość poda
    fake.set_status("pod0001", "RUNNING")
    healthy["ok"] = True
    await _tick(container, fake)
    await _tick(container, fake)
    await service.queue_parse(admin, view["id"], dataset.id, [docs[1].id])  # pod gotowy → od razu
    async with transaction(sm) as session:
        runs = (
            (await session.execute(text("SELECT run FROM documents ORDER BY name"))).scalars().all()
        )
    assert runs == ["1", "1"]
    await service.terminate(admin, view["id"])
    with pytest.raises(Conflict, match="no longer running"):
        await service.queue_parse(admin, view["id"], dataset.id, [docs[0].id])
