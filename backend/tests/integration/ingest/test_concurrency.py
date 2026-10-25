"""Testy współbieżności OCR/wizji i embeddingu (SC-E5-H8b-01/02, E5-H8b T3/T5/T6).

Scenariusze wizji (SC-01) przechodzą po T6 (``vision_concurrency`` z ``extra.max_concurrency``
modelu wizji, kontrakt C2). Scenariusze embeddingu/429/Stopu (SC-02) przechodzą po T5.

Integracyjne: zachowanie przez pipeline na fake-llm (opóźnienie OCR/embeddingów, wstrzykiwane
429, liczniki ``max_concurrent`` z K10 C6).
"""

import asyncio
import contextlib
import logging
import os
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import chunk_vectors
from app.db.repositories import documents as documents_repo
from app.db.repositories import models as models_repo
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from app.llm.tokens import count_tokens
from app.parsing.diacritics_dict import correct_with_wordfreq
from app.services.ingest_convert import convert_document, convert_options
from app.services.ingest_pipeline import run_parse
from app.text.fulltext import stem_text
from app.worker.errors import PermanentError
from app.worker.main import create_worker
from tests.integration.ingest.conftest import DEFAULT_PARSER_CONFIG, TIME_MS, seed_dataset
from tests.integration.ingest.pipeline_helpers import (
    claim_context,
    make_container,
    make_pdf_bytes,
    make_source,
    register_models,
)

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]

# Nazwy modeli fake-llm (K10): `fake-ocr` to model OCR z sterowalnym opóźnieniem (C6).
_FAKE_OCR = "fake-ocr"
_FAKE_VISION = "fake-vision"
_FAKE_EMBED = "fake-embed-1024"
_EMBED_DIM = 1024
# Aliasy wstrzykiwania (C8): wstrzyknięcie opóźnienia/429/5xx obowiązuje tylko własny alias
# testu (`<base>~conc-<uuid8>`), więc równoległe testy pod xdist się nie psują.
_ALIAS_PREFIX = "conc"

# Aliasy zawężone użyte w tym module — zerowane w `_restore_fake_llm` po teście (C8).
_USED_ALIASES: set[str] = set()

OCR_DELAY_MS = 500
EMBED_DELAY_MS = 300
# 48 stron: przy `OCR_DELAY_MS` faza OCR trwa ~48*0,5/8 ≈ 3 s (c=8) i ~8 s (c=3), więc
# próg czasu z zapasem po obu stronach odróżnia równoległość 8 od domyślnej 3.
VISION_PAGES = 48
EMBED_BATCH_SIZE = 1  # mały batch → 1 partia na chunk (wiele partii dla współbieżności)
POLL_S = 0.05
WAIT_TIMEOUT_S = 30.0


def _big_text(paragraphs: int = 80, words: int = 60) -> str:
    """Tekst dający wiele chunków/partii (≥ 20) przy ``embed_batch_size=1``."""
    return "\n\n".join(" ".join(f"tok{i}_{j}" for j in range(words)) for i in range(paragraphs))


# --- fake-llm: sterowanie opóźnieniami, 429 i licznikami (K10 C6) ---


def _base(container: Container) -> str:
    return container.settings.llm_base_url.rstrip("/")


async def _fake_get(container: Container, path: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{_base(container)}{path}")
    response.raise_for_status()
    return response.json()


async def _fake_post(container: Container, path: str, body: dict) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{_base(container)}{path}", json=body)
    response.raise_for_status()
    return response.json()


async def _stats(container: Container) -> dict:
    return await _fake_get(container, "/fake/stats")


async def _reset_stats(container: Container) -> None:
    await _fake_post(container, "/fake/stats/reset", {})


async def _set_ocr_delay(container: Container, ms: int, model: str | None = None) -> None:
    body: dict = {"ms": ms}
    if model is not None:
        body["model"] = model
    await _fake_post(container, "/fake/ocr-delay", body)


async def _set_embed_delay(container: Container, ms: int, model: str | None = None) -> None:
    body: dict = {"ms": ms}
    if model is not None:
        body["model"] = model
    await _fake_post(container, "/fake/embed-delay", body)


async def _set_embed_429(
    container: Container, every: int, retry_after_s: int | None, model: str | None = None
) -> None:
    body: dict = {"every": every, "retry_after_s": retry_after_s}
    if model is not None:
        body["model"] = model
    await _fake_post(container, "/fake/embed-429", body)


def _scoped_alias(base: str) -> str:
    """Unikalny alias modelu (`<base>~<prefix>-<uuid8>`) dla jednego testu (C8).

    Wstrzyknięcie z tym `model` obowiązuje tylko żądania tego aliasu, więc równoległe testy
    xdist nie psują sobie nawzajem liczników fake-llm. Alias trafia do `_USED_ALIASES`
    i jest zerowany po teście.
    """
    alias = f"{base}~{_ALIAS_PREFIX}-{uuid.uuid4().hex[:8]}"
    _USED_ALIASES.add(alias)
    return alias


async def _max_concurrent(container: Container, model: str) -> int:
    return int((await _stats(container))["max_concurrent"].get(model, 0))


async def _peak_max_concurrent(
    container: Container, model: str, run: Awaitable[Any]
) -> tuple[Any, int]:
    """Uruchamia ``run``, próbkując ``max_concurrent[model]``; zwraca ``(wynik, szczyt)``.

    Odporne na ``POST /v1/fake/stats/reset`` z INNYCH testów w toku (zeruje wspólny licznik
    fake-llm): próbkujemy w trakcie, więc szczyt sprzed zerwania jest zapamiętany — czytanie
    tylko po zakończeniu ``run`` widziałoby już wyzerowany licznik.
    """
    peak = 0

    async def _poll() -> None:
        nonlocal peak
        while True:
            peak = max(peak, await _max_concurrent(container, model))
            await asyncio.sleep(0.02)

    poll = asyncio.create_task(_poll())
    try:
        result = await run
    finally:
        poll.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await poll
    return result, peak


def _line_seconds(line: str) -> int | None:
    """Sekundy dnia ze znacznika ``HH:MM:SS`` na początku linii logu; brak → ``None``."""
    match = re.match(r"^(\d{2}):(\d{2}):(\d{2})\b", line)
    if match is None:
        return None
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3))


def _ocr_phase_seconds(progress: str) -> float:
    """Czas fazy OCR z ``progress_msg``: od ``Converted … pages`` do ``OCR finished``.

    Mierzymy samą fazę rozpoznawania (opóźnienia fake-llm), nie cały ``run_parse``:
    konwersja, chunking, embedding i zapisy do bazy rosną pod obciążeniem ``verify.sh -n 8``
    i zacierały różnicę 8 vs 3 zapytań równoległych. Znaczniki ``HH:MM:SS`` w logu zadania
    niosą czas wywołania ``report`` (nie flush), więc faza jest mierzona wprost.
    """
    converted: int | None = None
    finished: int | None = None
    for line in progress.split("\n"):
        seconds = _line_seconds(line)
        if seconds is None:
            continue
        if converted is None and "Converted" in line:
            converted = seconds
        elif "OCR finished" in line:
            finished = seconds
    assert converted is not None and finished is not None, "brak znaczników fazy OCR w logu"
    return float(finished - converted)


def _own_embed_posts(caplog: pytest.LogCaptureFixture) -> int:
    """POST `/v1/embeddings` **z tego procesu** (log httpx2), nie globalny licznik fake-llm.

    Globalny `embeddings.requests` jest wspólny dla całego procesu usługi, więc pod
    `verify.sh -n 8` równoległe testy dorzucają żądania i `==` flakuje; stąd liczymy
    tylko własne żądania (worker biegnie w tym samym procesie co test).
    """
    return sum(
        1
        for record in caplog.get_records("call")
        if record.name == "httpx2"
        and record.getMessage().startswith("HTTP Request: POST")
        and "/v1/embeddings" in record.getMessage()
    )


@pytest.fixture(autouse=True)
def _serialize_fakellm(serialize_fakellm: None) -> None:
    """Blokada fake-llm (stan globalny) wspólna z ``test_pipeline_ocr.py`` — patrz conftest.

    Bierzemy tę samą blokadę co ``test_pipeline_ocr.py`` (fixture ``serialize_fakellm``
    z ``tests/integration/ingest/conftest.py``) — równoległe żądania wizji z tamtego pliku
    podnosiły obserwowane ``max_concurrent`` powyżej własnego pułapu testu (flak ``== 8``).
    """


@pytest.fixture(autouse=True)
async def _restore_fake_llm(_serialize_fakellm: None) -> AsyncIterator[None]:
    """Po teście zeruje opóźnienia i 429 w fake-llm (stan globalny i reguły zawężone, C8)."""
    yield
    base = os.environ["WD_LLM_BASE_URL"].rstrip("/")
    async with httpx.AsyncClient() as client:
        for path, body in (
            ("/fake/ocr-delay", {"ms": 0}),
            ("/fake/embed-delay", {"ms": 0}),
            ("/fake/embed-429", {"every": 0, "retry_after_s": None}),
        ):
            response = await client.post(f"{base}{path}", json=body)
            response.raise_for_status()
        # Reguły zawężone (C8) zerujemy per alias (wartość zerowa + `model` usuwa regułę).
        for model in _USED_ALIASES:
            for path, body in (
                ("/fake/ocr-delay", {"ms": 0, "model": model}),
                ("/fake/embed-delay", {"ms": 0, "model": model}),
                ("/fake/embed-429", {"every": 0, "retry_after_s": None, "model": model}),
            ):
                response = await client.post(f"{base}{path}", json=body)
                response.raise_for_status()


# --- baza: kontenery, rejestr modeli, odczyty ---


async def _register_image_model(container: Container, model_id: str, name: str) -> None:
    assert container.sessionmaker is not None
    async with transaction(container.sessionmaker) as session:
        existing = await models_repo.get_by_name(session, name, "image2text")
        if existing is None:
            await models_repo.insert(
                session,
                id=model_id,
                name=name,
                model_type="image2text",
                is_default=False,
                now_ms=TIME_MS,
            )


async def _register_image_alias(container: Container, alias: str) -> None:
    """Rejestruje model image2text o nazwie-aliasie (`fake-ocr~conc-<uuid8>`, C8)."""
    await _register_image_model(container, uuid.uuid4().hex, alias)


async def _register_embedding_alias(container: Container, alias: str) -> None:
    """Rejestruje model embeddingu o nazwie-aliasie (`fake-embed-1024~conc-<uuid8>`, C8)."""
    assert container.sessionmaker is not None
    async with transaction(container.sessionmaker) as session:
        await models_repo.insert(
            session,
            id=uuid.uuid4().hex,
            name=alias,
            model_type="embedding",
            is_default=False,
            now_ms=TIME_MS,
        )


async def _set_model_extra(
    container: Container, name: str, model_type: str, extra: dict | None
) -> None:
    """Zapis ``models.extra`` jak panel/API (``PATCH``) — rejestr czyta go w następnym zadaniu."""
    assert container.sessionmaker is not None
    async with transaction(container.sessionmaker) as session:
        row = await models_repo.get_by_name(session, name, model_type)
        assert row is not None, f"model {name} ({model_type}) musi być w rejestrze"
        await models_repo.update_fields(
            session, model_id=row.id, is_active=None, max_tokens=None, extra=extra, now_ms=TIME_MS
        )


@pytest.fixture(scope="module", autouse=True)
def _warm_process(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Rozgrzewa leniwe zasoby procesu (tokenizer, stemmer, słownik diakrytyków, PDFium).

    Pierwsze w procesie użycie tokenizera (``count_tokens``), tabeli stemmera (``stem_text``),
    indeksu ``wordfreq`` (``correct_with_wordfreq``) i PDFium (konwersja PDF) trwa kilka sekund.
    Test czasu fazy OCR jest pierwszy w module, więc bez rozgrzewki mierzyłby głównie ten
    jednorazowy narzut, a nie konwersję.
    """
    count_tokens("rozgrzewka")
    stem_text("rozgrzewka")
    correct_with_wordfreq("rozgrzewka słownikowa")
    directory = tmp_path_factory.mktemp("warmup")
    path = directory / "warmup.pdf"
    path.write_bytes(make_pdf_bytes(1))
    asyncio.run(_warmup_convert(path))


async def _warmup_convert(path: Path) -> None:
    """Minimalna konwersja PDF (bez OCR/VLM) — rozgrzewa ścieżkę PDFium."""
    opts = convert_options(
        {"layout_recognize": "Plain Text"},
        Settings(env="test"),
        layout_vision=False,
        vision_available=False,
        ocr_available=False,
    )
    await convert_document(path, "pdf", opts, executor=None, ocr=None, vision=None)


@pytest.fixture
async def vision_container(migrated_db: Settings, tmp_path) -> AsyncIterator[Container]:
    """Kontener (fake-embed-1024 domyślny) + modele wizji ``fake-ocr`` i ``fake-vision``."""
    container = await make_container(migrated_db, tmp_path)
    await _register_image_model(container, "f" * 32, _FAKE_OCR)
    await _register_image_model(container, "d" * 32, _FAKE_VISION)
    yield container
    await container.aclose()


@pytest.fixture
async def embed_container(migrated_db: Settings, tmp_path) -> AsyncIterator[Container]:
    """Kontener z ``embed_batch_size=1``, bez retry SDK na domyślnym fake-embed-1024.

    ``llm_max_retries=0`` — ponowienia 429 robi bramka (C4), nie SDK; na bazie 429 propaguje.
    """
    container = await make_container(
        migrated_db,
        tmp_path,
        settings_overrides={"embed_batch_size": EMBED_BATCH_SIZE, "llm_max_retries": 0},
    )
    yield container
    await container.aclose()


async def _progress(sm: async_sessionmaker[AsyncSession], document_id: str) -> str:
    async with transaction(sm) as session:
        row = await documents_repo.get(session, document_id)
    assert row is not None
    return row.progress_msg


async def _parse_pdf(
    container: Container, data: bytes, name: str, layout: str
) -> tuple[DocumentRow, float]:
    """Dataset z parserem wizji + upload PDF + ``run_parse`` (executor=None); (dokument, czas)."""
    assert container.sessionmaker is not None
    parser_config = {**DEFAULT_PARSER_CONFIG, "layout_recognize": layout}
    ds = await seed_dataset(container.sessionmaker, parser_config=parser_config)
    doc = await container.ingest.upload(ds.id, make_source(data, name), created_by=ds.tenant_id)
    ctx = await claim_context(container, doc.id)
    started = time.monotonic()
    await run_parse(container, ctx.task, ctx, executor=None)
    return doc, time.monotonic() - started


async def _parse_text(
    container: Container, body: str, name: str, embedding_model: str = _FAKE_EMBED
) -> tuple[str, float]:
    """Ingestia tekstu przez pipeline (executor=None); (id dokumentu, czas).

    ``embedding_model`` (alias zawężony, C8) trafia do datasetu, więc żądania embeddingu idą
    na własny alias testu.
    """
    assert container.sessionmaker is not None
    ds = await seed_dataset(container.sessionmaker, embedding_model=embedding_model)
    doc = await container.ingest.upload(
        ds.id, make_source(body.encode(), name), created_by=ds.tenant_id
    )
    ctx = await claim_context(container, doc.id)
    started = time.monotonic()
    await run_parse(container, ctx.task, ctx, executor=None)
    return doc.id, time.monotonic() - started


def _embedding_progress(progress: str) -> list[tuple[int, int]]:
    return [
        (int(done), int(total))
        for done, total in re.findall(r"Embedding chunks \((\d+)/(\d+)\)", progress)
    ]


# --- SC-E5-H8b-01: równoległe zapytania OCR/wizji ---


async def test_vision_concurrency_from_model_extra(vision_container: Container) -> None:
    """SC-01/2: `extra.max_concurrency=8` → 8 równoległych zapytań, log i czas fazy OCR."""
    alias = _scoped_alias(_FAKE_OCR)
    progress, _ = await _run_vision(vision_container, alias, {"max_concurrency": 8})
    stats_max = await _max_concurrent(vision_container, alias)
    assert stats_max == 8  # noqa: PLR2004
    assert f"OCR concurrency: 8 ({alias})" in progress
    assert "OCR pages" in progress and f"({alias})" in progress
    # Mierzymy samą fazę OCR (nie całe zadanie): strony * 0,5 s / 8 (+/- 30%) + zapas na
    # narzut fal żądań. Przy c=3 faza trwałaby VISION_PAGES*0,5/3 ≈ 8 s, więc próg
    # z zapasem po obu stronach odróżnia c=8 (~3 s) od c=3 (kontrakt C2).
    ocr_estimate = VISION_PAGES * (OCR_DELAY_MS / 1000) / 8
    assert _ocr_phase_seconds(progress) <= ocr_estimate * 1.3 + 2.0


async def _run_vision(container: Container, alias: str, extra: dict) -> tuple[str, float]:
    """Rejestruje alias obrazu, wstrzykuje opóźnienie OCR zawężone do aliasu i parsuje PDF (C8).

    Wstrzyknięcie z `model=alias` obowiązuje tylko żądania tego aliasu, więc równoległe testy
    xdist nie zanieczyszczają liczników bazowego `fake-ocr`.
    """
    await _register_image_alias(container, alias)
    await _set_ocr_delay(container, OCR_DELAY_MS, model=alias)
    await _set_model_extra(container, alias, "image2text", extra)
    await _reset_stats(container)
    doc, elapsed = await _parse_pdf(container, make_pdf_bytes(VISION_PAGES), "skan.pdf", alias)
    assert container.sessionmaker is not None
    return await _progress(container.sessionmaker, doc.id), elapsed


async def test_vision_concurrency_changes_between_tasks(vision_container: Container) -> None:
    """SC-01 wariant „zmiana między zadaniami”: PATCH 8 → 2 bez restartu, drugie zadanie ≤ 2."""
    alias = _scoped_alias(_FAKE_OCR)
    await _run_vision(vision_container, alias, {"max_concurrency": 8})
    assert await _max_concurrent(vision_container, alias) == 8  # noqa: PLR2004

    second, _ = await _run_vision(vision_container, alias, {"max_concurrency": 2})
    assert await _max_concurrent(vision_container, alias) <= 2  # noqa: PLR2004
    assert f"OCR concurrency: 2 ({alias})" in second


async def test_vision_concurrency_default_when_extra_missing(vision_container: Container) -> None:
    """SC-01 wariant „pole puste”: brak klucza → domyślne `WD_VLM_CONCURRENCY` (3)."""
    alias = _scoped_alias(_FAKE_OCR)
    progress, _ = await _run_vision(vision_container, alias, {})
    assert f"OCR concurrency: 3 ({alias})" in progress


async def test_vision_concurrency_rejects_out_of_range_extra(
    vision_container: Container,
) -> None:
    """SC-01/3: `extra.max_concurrency=99` wprost w bazie → czytelny błąd przed konwersją."""
    await _set_model_extra(vision_container, _FAKE_VISION, "image2text", {"max_concurrency": 99})
    assert vision_container.sessionmaker is not None
    parser_config = {**DEFAULT_PARSER_CONFIG, "layout_recognize": _FAKE_VISION}
    ds = await seed_dataset(vision_container.sessionmaker, parser_config=parser_config)
    doc = await vision_container.ingest.upload(
        ds.id, make_source(make_pdf_bytes(), "skan.pdf"), created_by=ds.tenant_id
    )
    ctx = await claim_context(vision_container, doc.id)
    with pytest.raises(
        PermanentError,
        match=r"extra\.max_concurrency must be an integer between 1 and 32 \(model fake-vision\)",
    ):
        await run_parse(vision_container, ctx.task, ctx, executor=None)
    progress = await _progress(vision_container.sessionmaker, doc.id)
    assert "Converting pages" not in progress, "walidacja musi paść przed konwersją"


# --- SC-E5-H8b-02: embedding równoległy, 429, Stop ---


async def test_embedding_concurrency_from_model_extra(embed_container: Container) -> None:
    """SC-02/1: `extra.max_concurrency=6` → 6 partii równolegle, monotoniczny postęp, czas."""
    alias = _scoped_alias(_FAKE_EMBED)
    await _register_embedding_alias(embed_container, alias)
    await _set_embed_delay(embed_container, EMBED_DELAY_MS, model=alias)
    await _set_model_extra(embed_container, alias, "embedding", {"max_concurrency": 6})
    await _reset_stats(embed_container)
    doc_id, elapsed = await _parse_text(
        embed_container, _big_text(), "korpus.txt", embedding_model=alias
    )
    assert embed_container.sessionmaker is not None
    calls = _embedding_progress(await _progress(embed_container.sessionmaker, doc_id))
    assert calls, "brak wpisów „Embedding chunks (n/N)”"
    total = calls[-1][1]
    assert total >= 20  # noqa: PLR2004 — ≥ 20 partii przy `embed_batch_size=1`
    dones = [done for done, _ in calls]
    assert dones == sorted(dones) and len(set(dones)) == len(dones)
    assert calls[-1][0] == total
    # Alias jest prywatny dla tego testu (C8), więc własny licznik nie jest podbijany przez
    # równoległe testy xdist; `>= 6` zostaje jako dowód równoległości (sekwencyjnie byłoby 1).
    assert await _max_concurrent(embed_container, alias) >= 6  # noqa: PLR2004
    # Czas liczony po całości (konwersja/chunking/DB), nie tylko embedding — a `verify.sh`
    # puszcza to równolegle (`-n 8`), więc budżet jest luźny: najważniejszy dowód
    # równoległości to `max_concurrent == 6`; sekwencyjnie byłoby ~`estimate * 6`.
    estimate = total * (EMBED_DELAY_MS / 1000) / 6
    assert elapsed <= estimate * 2.0 + 5.0


async def test_embedding_concurrency_default_when_extra_missing(embed_container: Container) -> None:
    """SC-02 wariant „pole puste”: brak klucza → domyślne `WD_EMBED_CONCURRENCY` (4)."""
    alias = _scoped_alias(_FAKE_EMBED)
    await _register_embedding_alias(embed_container, alias)
    await _set_embed_delay(embed_container, EMBED_DELAY_MS, model=alias)
    await _set_model_extra(embed_container, alias, "embedding", {})
    await _reset_stats(embed_container)
    (doc_id, _), peak = await _peak_max_concurrent(
        embed_container,
        alias,
        _parse_text(embed_container, _big_text(), "korpus.txt", embedding_model=alias),
    )
    assert embed_container.sessionmaker is not None
    calls = _embedding_progress(await _progress(embed_container.sessionmaker, doc_id))
    assert calls, "brak wpisów „Embedding chunks (n/N)”"
    total = calls[-1][1]
    assert total >= 20  # noqa: PLR2004 — ≥ 20 partii przy `embed_batch_size=1`
    # Alias jest prywatny (C8), więc szczyt `max_concurrent` mierzymy próbkując w trakcie —
    # zerwanie wspólnego licznika przez inny test nie ukryje szczytu. `>= 2` dowodzi
    # równoległości domyślnej (sekwencyjnie byłoby 1); dokładny pułap (4) pilnuje
    # `Settings.embed_concurrency` + `test_embed_texts_caps_inflight_at_concurrency`.
    assert peak >= 2  # noqa: PLR2004


async def test_embedding_concurrency_rejects_out_of_range_extra(
    embed_container: Container,
) -> None:
    """SC-02/walidacja (C2): `extra.max_concurrency=99` → czytelny błąd PRZED konwersją.

    Walidacja embeddingu nie może czekać do kroku 10 — dokument z błędną wartością ma
    dostać błąd bez wykonywania kosztownej konwersji/OCR.
    """
    await _set_model_extra(embed_container, _FAKE_EMBED, "embedding", {"max_concurrency": 99})
    assert embed_container.sessionmaker is not None
    ds = await seed_dataset(embed_container.sessionmaker)
    doc = await embed_container.ingest.upload(
        ds.id, make_source(make_pdf_bytes(), "skan.pdf"), created_by=ds.tenant_id
    )
    ctx = await claim_context(embed_container, doc.id)
    expected = (
        r"extra\.max_concurrency must be an integer between 1 and 32"
        r" \(model fake-embed-1024\)"
    )
    with pytest.raises(PermanentError, match=expected):
        await run_parse(embed_container, ctx.task, ctx, executor=None)
    progress = await _progress(embed_container.sessionmaker, doc.id)
    assert "Converting pages" not in progress, "walidacja musi paść przed konwersją"


@pytest.mark.parametrize("retry_after_s", [1, None])
async def test_429_retry_preserves_chunk_order(
    embed_container: Container, monkeypatch: pytest.MonkeyPatch, retry_after_s: int | None
) -> None:
    """SC-02/2: 429 co 5. partię (z `Retry-After` i bez) → „Sukces” i wektory w kolejności."""
    alias = _scoped_alias(_FAKE_EMBED)
    await _register_embedding_alias(embed_container, alias)
    await _set_embed_delay(embed_container, 0, model=alias)
    with contextlib.suppress(ImportError):
        import app.llm.rate_limit as rate_limit_module  # noqa: PLC0415

        monkeypatch.setattr(rate_limit_module, "BACKOFF_BASE_S", 0.01, raising=False)

    body = _big_text(paragraphs=40)
    # (A) odniesienie: sekwencyjnie, bez 429.
    await _set_embed_429(embed_container, 0, None, model=alias)
    await _set_model_extra(embed_container, alias, "embedding", {"max_concurrency": 1})
    ref_doc, _ = await _parse_text(embed_container, body, "korpus.txt", embedding_model=alias)
    reference = await _vectors_by_ordinal(embed_container, ref_doc)
    assert reference, "brak wektorów odniesienia"

    # (B) równolegle z 429 (co 5. żądanie).
    await _set_model_extra(embed_container, alias, "embedding", {"max_concurrency": 6})
    await _set_embed_429(embed_container, 5, retry_after_s, model=alias)
    doc_id, _ = await _parse_text(embed_container, body, "korpus.txt", embedding_model=alias)
    assert await _vectors_by_ordinal(embed_container, doc_id) == reference


async def _vectors_by_ordinal(container: Container, document_id: str) -> list[str]:
    """Tekstowa postać wektorów committed=1 w kolejności ordinal (VEC_ToText)."""
    assert container.sessionmaker is not None
    table = chunk_vectors.table_name(_EMBED_DIM)
    sql = (
        f"SELECT VEC_ToText(v.embedding) FROM {table} v"  # noqa: S608 — nazwa z table_name(int)
        " JOIN chunks c ON c.id = v.chunk_id"
        " WHERE c.document_id = :d AND c.committed = 1 ORDER BY c.ordinal"
    )
    async with transaction(container.sessionmaker) as session:
        rows = (await session.execute(text(sql), {"d": document_id})).scalars()
        return [str(value) for value in rows]


# --- testy na prawdziwym workerze: trwały 429, Stop, stan dokumentu ---


@contextlib.asynccontextmanager
async def _worker(
    migrated_db: Settings, tmp_path, *, embed_batch_size: int = EMBED_BATCH_SIZE
) -> AsyncIterator[Container]:
    """Prawdziwy Worker (create_worker) z małym batch embeddingu i bez retry SDK."""
    settings = migrated_db.model_copy(
        update={
            "storage_root": str(tmp_path),
            "ocr_engine": "none",
            "worker_poll_s": POLL_S,
            "llm_max_retries": 0,
            "embed_batch_size": embed_batch_size,
        }
    )
    container, worker = create_worker(settings)
    await container.start()
    assert container.sessionmaker is not None
    await register_models(container.sessionmaker)
    stop = asyncio.Event()
    run_task = asyncio.create_task(worker.run(stop))
    try:
        yield container
    finally:
        stop.set()
        await asyncio.wait_for(run_task, timeout=15)
        await container.aclose()


async def _wait_final(sm: async_sessionmaker[AsyncSession], document_id: str) -> DocumentRow:
    """Czeka na stan końcowy dokumentu (run ∈ {2,3,4}, brak zadań w toku); zwraca wiersz."""
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        async with transaction(sm) as session:
            row = await documents_repo.get(session, document_id)
        async with sm() as session:
            pending = (
                await session.execute(
                    text(
                        "SELECT COALESCE(SUM(status NOT IN"
                        " ('done','failed','cancelled','dead')), 0)"
                        " FROM tasks WHERE document_id = :i"
                    ),
                    {"i": document_id},
                )
            ).scalar_one()
        if row is not None and row.run in ("2", "3", "4") and int(pending) == 0:
            return row
        await asyncio.sleep(0.2)
    raise AssertionError(f"{document_id} bez stanu końcowego w {WAIT_TIMEOUT_S} s")


async def test_embedding_permanent_429_fails_document(
    migrated_db: Settings, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-02/3: 429 trwale → dokument „Błąd” z komunikatem z C4 w `progress_msg`."""
    from app.llm import rate_limit as rate_limit_module  # noqa: PLC0415
    from app.worker import queue as queue_module  # noqa: PLC0415

    monkeypatch.setattr(queue_module, "backoff_ms", lambda attempts, jitter_ms: 200)
    # Backoff bramki zerujemy: interesuje nas stan końcowy dokumentu, nie realne przerwy
    # (BASE=1 s dałoby >30 s na próbę zadania; budżet `_wait_final` to 30 s).
    monkeypatch.setattr(rate_limit_module, "BACKOFF_BASE_S", 0.01)
    async with _worker(migrated_db, tmp_path) as container:
        assert container.sessionmaker is not None
        alias = _scoped_alias(_FAKE_EMBED)
        await _register_embedding_alias(container, alias)
        await _set_embed_delay(container, 0, model=alias)
        await _set_embed_429(container, 1, None, model=alias)
        await _set_model_extra(container, alias, "embedding", {"max_concurrency": 6})
        ds = await seed_dataset(container.sessionmaker, embedding_model=alias)
        doc = await container.ingest.upload(
            ds.id,
            make_source(_big_text(paragraphs=20).encode(), "korpus.txt"),
            created_by=ds.tenant_id,
            parse=True,
        )
        row = await _wait_final(container.sessionmaker, doc.id)
        assert row.run == "4"
        expected = (
            f"Embedding provider rate limit (429) — reduce Parallel requests of model {alias}"
        )
        assert expected in row.progress_msg
        assert expected in (row.error or "")


async def test_stop_during_embedding_cancels_quickly(
    migrated_db: Settings, tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    """SC-02/4: Stop w trakcie embeddingu → „Anulowano” ≤ 15 s, brak nowych partii po anulowaniu."""
    caplog.set_level(logging.INFO, logger="httpx2")  # własne żądania bramki (ten proces)
    async with _worker(migrated_db, tmp_path) as container:
        assert container.sessionmaker is not None
        alias = _scoped_alias(_FAKE_EMBED)
        await _register_embedding_alias(container, alias)
        await _set_embed_delay(container, EMBED_DELAY_MS, model=alias)
        await _set_model_extra(container, alias, "embedding", {"max_concurrency": 4})
        await _reset_stats(container)
        ds = await seed_dataset(container.sessionmaker, embedding_model=alias)
        doc = await container.ingest.upload(
            ds.id,
            make_source(_big_text().encode(), "korpus.txt"),
            created_by=ds.tenant_id,
            parse=True,
        )
        # Czekamy, aż ruszy faza chunków (żądanie nr 1 to wektor tytułu, `concurrency=1`),
        # więc ≥ 2 żądania WŁASNE oznaczają partie chunków w locie — dopiero wtedy Stop.
        deadline = time.monotonic() + WAIT_TIMEOUT_S
        while _own_embed_posts(caplog) < 2:  # noqa: PLR2004 — tytuł + ≥1 partia chunku
            assert time.monotonic() < deadline, "embedding nie wystartował"
            await asyncio.sleep(0.05)
        cancelled_at = time.monotonic()
        assert await container.ingest.cancel([doc.id]) == 1
        row = await _wait_final(container.sessionmaker, doc.id)
        assert row.run == "2"
        assert time.monotonic() - cancelled_at <= 15  # noqa: PLR2004
        # Równoległość potwierdzona (licznik aliasu ≥ 2), a po anulowaniu liczba NASZYCH
        # żądań stoi (przez 2 s, brak sierot).
        assert await _max_concurrent(container, alias) >= 2  # noqa: PLR2004
        after = _own_embed_posts(caplog)
        await asyncio.sleep(2)
        assert _own_embed_posts(caplog) == after
