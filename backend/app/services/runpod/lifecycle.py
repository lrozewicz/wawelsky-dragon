"""Cykl życia poda: postęp stanów, gotowość modelu, start parsowania i automatyczne kasowanie.

Wołane cyklicznie przez worker (``tick``). Stan jest w ``runpod_pods``, więc restart workera
niczego nie gubi. Zasada kosztowa: pod jest kasowany (``DELETE``) zawsze, gdy nie ma już zadań
parsowania, które go używają (po krótkiej zwłoce), po błędzie albo po przekroczeniu limitów czasu.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from app.core.crypto import decrypt
from app.db.repositories import runpod_pods as pods_repo
from app.db.repositories.runpod_pods import PodRow
from app.db.uow import transaction
from app.services.runpod.client import RunpodAuthError, RunpodClient, RunpodError
from app.services.runpod.hosted import HostedModel, get_model, proxy_url
from app.services.runpod.keystore import client_for
from app.services.runpod.registry import ensure_registered

if TYPE_CHECKING:
    from app.core.container import Container

logger = logging.getLogger("app.runpod")

REQUEST_TIMEOUT_S = 120
PROVISION_TIMEOUT_S = 300  # brak maszyny dłużej niż 5 min = GPU niedostępne
# Maszyna jest, ale kontener nie wstał (powolne pobieranie obrazu, błędy hosta przy `create`).
# Zdrowy pod: obraz ~5 min + start ~1 min, więc 12 min to już zły host — wolimy inne GPU niż 25 min.
CONTAINER_START_TIMEOUT_S = 12 * 60
# Pod ze startu parsowania (`origin=parse`): tyle po ostatnim zadaniu jeszcze żyje (kolejne pliki,
# ponowne próby). Pod z panelu (`origin=panel`) nie wygasa — kasuje go tylko człowiek.
IDLE_GRACE_S = 300
MAX_LIFETIME_S = 8 * 3600  # twardy bezpiecznik kosztów
HEALTH_TIMEOUT_S = 5.0
PANEL_ORIGIN = "panel"
PARSE_ORIGIN = "parse"
HTTP_OK = 200
HTTP_NOT_FOUND = 404
_RUNPOD_TO_STATUS = {"PROVISIONING": "provisioning", "STARTING": "starting", "RUNNING": "loading"}
_GONE = {"EXITED", "ERROR", "TERMINATED"}


def pod_token(container: Container, row: PodRow) -> str | None:
    """Klucz vLLM poda (odszyfrowany)."""
    if row.api_token_enc is None:
        return None
    key = container.settings.crypto_key.get_secret_value()
    return decrypt(key, row.api_token_enc, f"runpod-pod:{row.id}".encode()).decode()


async def _update(container: Container, row: PodRow, **fields: Any) -> None:
    assert container.sessionmaker is not None  # noqa: S101
    async with transaction(container.sessionmaker) as session:
        await pods_repo.update_fields(session, row.id, now_ms=container.clock.now_ms(), **fields)


async def _terminate(
    container: Container, client: RunpodClient, row: PodRow, *, status: str, error: str | None
) -> None:
    """Kasuje poda w RunPod (koniec kosztów) i zapisuje stan końcowy."""
    if row.pod_id:
        try:
            await client.delete_pod(row.pod_id)
        except RunpodError as exc:
            logger.warning("runpod delete failed", extra={"pod": row.pod_id, "error": exc.message})
            await _update(container, row, status="terminating", error=error)
            return
    await _update(container, row, status=status, error=error, end_time=container.clock.now_ms())


async def _health_status(base_url: str) -> int | None:
    """Kod HTTP ``GET /health`` vLLM przez proxy RunPod (bez klucza); ``None`` = błąd sieci.

    200 = silnik gotowy. 404 z proxy = port poda nie jest jeszcze zarejestrowany (kontener nie
    wystartował); 502 = kontener działa, ale vLLM jeszcze nie nasłuchuje (ładuje model).
    """
    health = base_url.removesuffix("/v1") + "/health"
    try:
        async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT_S) as http:
            return (await http.get(health)).status_code
    except httpx.HTTPError:
        return None


def _container_started(pod: dict[str, Any], health: int | None) -> bool:
    """Czy kontener już działa: `runtime` z RunPod albo proxy, które nie odpowiada 404.

    Błąd sieci (``None``) liczymy jako „działa”, żeby chwilowa awaria proxy nie ubiła poda.
    """
    return bool(pod.get("runtime")) or health != HTTP_NOT_FOUND


async def _become_ready(container: Container, row: PodRow, model: HostedModel) -> None:
    """Model odpowiada: rejestr WD dostaje adres i klucz, czekające dokumenty idą do parsowania."""
    base_url = row.base_url or ""
    await ensure_registered(
        container,
        model,
        base_url=base_url,
        api_token=pod_token(container, row),
        created_by=row.created_by,
    )
    now = container.clock.now_ms()
    await _update(container, row, status="ready", ready_time=now, busy_time=now, pending_parse=[])
    await _start_pending_parse(container, row)


async def _start_pending_parse(container: Container, row: PodRow) -> None:
    """Parsowanie dokumentów zleconych przy wdrożeniu; błąd jednego nie zatrzymuje reszty."""
    await start_parse(container, row.pending_parse)


async def start_parse(container: Container, items: list[dict[str, Any]]) -> None:
    """Zleca parsowanie dokumentów z ``[{dataset_id, document_ids}]``; pomija niemożliwe."""
    for item in items:
        ids = [str(doc_id) for doc_id in item.get("document_ids", [])]
        for doc_id in ids:
            try:
                await container.ingest.enqueue_parse([doc_id])
            except Exception as exc:  # noqa: BLE001 — np. dokument już w kolejce albo usunięty
                logger.info(
                    "runpod pending parse skipped", extra={"document": doc_id, "error": str(exc)}
                )


async def advance(  # noqa: PLR0911 — automat stanów: każdy stan końcowy to osobny return
    container: Container, row: PodRow, client: RunpodClient
) -> None:
    """Jeden krok automatu dla wdrożenia (idempotentny; wołany co kilkanaście sekund)."""
    model = get_model(row.model_name)
    now = container.clock.now_ms()
    age_s = (now - row.create_time) / 1000
    if row.status == "terminating":
        await _terminate(container, client, row, status="terminated", error=row.error)
        return
    if (
        row.status == "requested"
    ):  # deploy jeszcze woła RunPod; po 2 min uznajemy zlecenie za zgubione
        if age_s > REQUEST_TIMEOUT_S:
            await _update(container, row, status="failed", error="deployment request was lost")
        return
    if model is None or row.pod_id is None:
        # Model zniknął z kodu, a pod w RunPod nadal kosztuje — kasujemy go (bez poda: tylko stan).
        await _terminate(container, client, row, status="failed", error="unknown model or pod")
        return
    if age_s > MAX_LIFETIME_S:
        await _terminate(container, client, row, status="terminated", error="max lifetime reached")
        return
    pod = await client.get_pod(row.pod_id)
    runpod_status = str(pod.get("status", "")) if pod else "TERMINATED"
    if runpod_status in _GONE:
        reason = f"pod ended unexpectedly ({runpod_status})"
        await _terminate(container, client, row, status="failed", error=reason)
        return
    assert pod is not None  # noqa: S101 — TERMINATED obsłużone wyżej
    if row.status == "ready":
        await _while_ready(container, client, row, model, now)
        return
    new_status = _RUNPOD_TO_STATUS.get(runpod_status, row.status)
    cost = float(pod.get("cost", 0) or 0)
    fields: dict[str, Any] = {}
    if cost > 0 and abs(cost - row.price_per_hr) > 0.001:  # noqa: PLR2004
        fields["price_per_hr"] = cost
    if pod.get("dataCenterId") and not row.data_center_id:
        fields["data_center_id"] = pod["dataCenterId"]
    base_url = row.base_url or proxy_url(row.pod_id)
    fields["base_url"] = base_url
    health = await _health_status(base_url) if new_status in {"starting", "loading"} else None
    if new_status in {"starting", "loading"}:
        # RunPod potrafi zgłaszać RUNNING przed startem kontenera, a STARTING mimo działającego
        # kontenera — o etapie decyduje to, czy kontener faktycznie odpowiada.
        new_status = "loading" if _container_started(pod, health) else "starting"
    if (error := _timeout_error(new_status, age_s, model)) is not None:
        await _terminate(container, client, row, status="failed", error=error)
        return
    if new_status == "loading" and health == HTTP_OK:
        await _update(container, row, **fields)
        await _become_ready(container, _with(row, base_url=base_url), model)
        return
    await _update(container, row, status=new_status, **fields)


def _timeout_error(status: str, age_s: float, model: HostedModel) -> str | None:
    """Powód przerwania wdrożenia, które za długo tkwi w danym stanie (``None`` = czekamy dalej).

    Prefiks ``gpu_unavailable`` sprawia, że panel proponuje inne GPU / centrum danych.
    """
    if status == "provisioning" and age_s > PROVISION_TIMEOUT_S:
        return "gpu_unavailable: no machine within 5 minutes"
    if status == "starting" and age_s > CONTAINER_START_TIMEOUT_S:
        minutes = CONTAINER_START_TIMEOUT_S // 60
        return f"gpu_unavailable: the container did not start within {minutes} minutes"
    if status in {"starting", "loading"} and age_s > model.startup_timeout_s:
        return "model did not start in time"
    return None


def _with(row: PodRow, **changes: Any) -> PodRow:
    from dataclasses import replace  # noqa: PLC0415

    return replace(row, **changes)


async def _while_ready(
    container: Container, client: RunpodClient, row: PodRow, model: HostedModel, now: int
) -> None:
    """Pod gotowy: dopóki są zadania używające modelu, żyje; po zwłoce bezczynności — kasowanie.

    Pod uruchomiony z panelu RunPod jest pomijany: zostaje do ręcznego wyłączenia (poza
    ``MAX_LIFETIME_S``, który sprawdza ``advance``).
    """
    if row.origin == PANEL_ORIGIN:
        return
    assert container.sessionmaker is not None  # noqa: S101
    async with transaction(container.sessionmaker) as session:
        pending = await pods_repo.count_pending_parse_tasks(session, model.name)
    if pending > 0:
        await _update(container, row, busy_time=now)
        return
    idle_s = (now - (row.busy_time or row.ready_time or row.create_time)) / 1000
    if idle_s >= IDLE_GRACE_S:
        await _terminate(container, client, row, status="terminated", error=None)


async def tick(container: Container) -> int:
    """Przebieg dla wszystkich aktywnych wdrożeń (zwraca ich liczbę); błąd jednego nie blokuje."""
    assert container.sessionmaker is not None  # noqa: S101
    async with transaction(container.sessionmaker) as session:
        rows = await pods_repo.list_active(session)
    if not rows:
        return 0
    try:
        client = await client_for(container)
    except Exception:  # noqa: BLE001 — brak klucza: nie da się kasować, ale też nic nie kosztuje przez WD
        logger.warning("runpod tick: no API key while pods are active")
        return len(rows)
    for row in rows:
        try:
            await advance(container, row, client)
        except RunpodAuthError:
            logger.error("runpod tick: API key rejected")
            break
        except Exception:
            logger.exception("runpod tick failed", extra={"deployment": row.id})
    return len(rows)
