"""``IntegrationService`` — CRUD integracji SharePoint, sekrety i sterowanie przebiegami (K12 §5).

Logika bez HTTP: trasy SVC (T4) i trasy WD (E4-3b) tylko mapują DTO i błędy. Konektor
pochodzi wyłącznie z rejestru (``registry.get("sharepoint")``), a sekrety wyłącznie
z ``app.integrations.secrets`` — plaintext nigdy nie trafia do ``details`` audytu,
komunikatów błędów ani ``IntegrationView`` (niesie tylko ``secret_enc``/``secret_last4``).
Odczyty i test połączenia są w klasie bazowej ``IntegrationCore`` (``integration_ops.py``).
"""

from __future__ import annotations

from dataclasses import fields
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories import integrations as integrations_repo
from app.db.repositories.integrations import (
    ContainerRow,
    EventRow,
    IntegrationRow,
    RunRow,
)
from app.db.uow import transaction
from app.integrations.secrets import decrypt_secret, encrypt_secret
from app.services.integration_input import IntegrationCreate, IntegrationUpdate
from app.services.integration_links import DocumentLink, DocumentLinkResolver
from app.services.integration_ops import (
    INTEGRATION_TYPE,
    NOT_FOUND,
    Actor,
    IntegrationCore,
    IntegrationView,
    StatusView,
    SyncOutcome,
)
from app.services.integration_runs import CancelResult, IntegrationRunsService

if TYPE_CHECKING:
    from app.core.container import Container
    from app.integrations.config import IntegrationsConfig

__all__ = [
    "Actor",
    "ContainerRow",  # re-eksport z app.db dla app.api (DEC-075, import-linter api-no-db)
    "EventRow",
    "IntegrationRow",
    "IntegrationService",
    "IntegrationView",
    "RunRow",
    "StatusView",
    "SyncOutcome",
]

DUPLICATE_CONSTRAINT = "uq_integrations_dataset"
SYNC_RUNNING = "Sync already running"


def _dataset_taken(dataset_id: str) -> str:
    """Komunikat 409 drugiego zapisu na ten sam dataset (oryginał ``integrations.ts:394``)."""
    return f"Dataset {dataset_id} is already linked to another integration"


def _is_duplicate_dataset(exc: IntegrityError) -> bool:
    """Czy ``IntegrityError`` dotyczy unikalnego ``dataset_id`` (``uq_integrations_dataset``)."""
    return DUPLICATE_CONSTRAINT in str(exc)


def _pick[T](new: T | None, current: T) -> T:
    """Wartość z żądania, a gdy jej nie ma — dotychczasowa z bazy (kontrakt §3 update)."""
    return current if new is None else new


def _changed_fields(data: IntegrationUpdate) -> list[str]:
    """Nazwy pól nadesłanych w żądaniu (``None`` = bez zmiany) — do ``details`` audytu."""
    return [field.name for field in fields(data) if getattr(data, field.name) is not None]


class IntegrationService(IntegrationCore):
    """Zapisy integracji, sterowanie przebiegami i audyt (kontrakt WP E4-3a §3; T4 dokłada link)."""

    def __init__(
        self,
        container: Container,
        config: IntegrationsConfig,
        runs: IntegrationRunsService | None = None,
    ) -> None:
        self._container = container
        self._config = config
        self._runs = runs if runs is not None else IntegrationRunsService(container, config)
        self._links = DocumentLinkResolver(container, config.link_cache_ttl_seconds)

    async def create(self, data: IntegrationCreate, actor: Actor) -> IntegrationView:
        """Zakłada integrację po udanym ``resolve`` konektora (kontrakt §3 create)."""
        async with transaction(self._sm()) as session:
            # ``get_record`` (nie ``get``): ``owner_id`` = ``datasets.created_by`` (DEC-074).
            dataset = await datasets_repo.get_record(session, data.dataset_id)
            if dataset is None:
                raise ValidationFailed(f"Dataset {data.dataset_id} not found")
            if await integrations_repo.find_by_dataset(session, data.dataset_id) is not None:
                raise Conflict(_dataset_taken(data.dataset_id))
        cfg = self._sharepoint_cfg(
            0,
            tenant_id=data.tenant_id,
            client_id=data.client_id,
            client_secret=data.client_secret,
            site_url=data.site_url,
            site_id=None,
            excluded_library_names=data.excluded_library_names,
            max_file_size_bytes=data.max_file_size_bytes,
        )
        resolved = await self._resolve(self._connector(), cfg)
        now_ms = self._now_ms()
        try:
            integration_id = await self._insert(
                data, owner_id=dataset.created_by, resolved=resolved, now_ms=now_ms
            )
        except IntegrityError as exc:  # wyścig create-to-create na ten sam dataset (§3 p. 4)
            if _is_duplicate_dataset(exc):
                raise Conflict(_dataset_taken(data.dataset_id)) from exc
            raise
        await self._audit(
            actor,
            "integration_created",
            integration_id,
            {
                "name": data.name,
                "dataset_id": data.dataset_id,
                "tenant_id": data.tenant_id,
                "client_id": data.client_id,
                "site_url": data.site_url,
            },
        )
        return await self.get(integration_id)

    async def update(
        self, integration_id: int, data: IntegrationUpdate, actor: Actor
    ) -> IntegrationView:
        """Zmienia integrację; ``None`` = bez zmiany, zmiana creds/URL → re-resolve (§3 update)."""
        async with transaction(self._sm()) as session:
            row = await integrations_repo.get_integration(session, integration_id)
            if row is None:
                raise NotFound(NOT_FOUND)
            sharepoint = await self._sharepoint_row(session, integration_id)
            if data.dataset_id is not None and data.dataset_id != row.dataset_id:
                if await datasets_repo.get(session, data.dataset_id) is None:
                    raise ValidationFailed(f"Dataset {data.dataset_id} not found")
                if await integrations_repo.find_by_dataset(session, data.dataset_id) is not None:
                    raise Conflict(_dataset_taken(data.dataset_id))
        name = _pick(data.name, row.name)
        dataset_id = _pick(data.dataset_id, row.dataset_id)
        excluded = _pick(data.excluded_library_names, sharepoint.excluded_library_names)
        max_size = _pick(data.max_file_size_bytes, row.max_file_size_bytes)
        ignored = _pick(data.ignored_extensions, row.ignored_extensions)
        interval = _pick(data.scan_interval_seconds, row.scan_interval_seconds)
        delete_propagation = _pick(data.delete_propagation, row.delete_propagation)
        is_active = _pick(data.is_active, row.is_active)
        current_tenant = sharepoint.tenant_id
        current_client = sharepoint.client_id
        current_url = sharepoint.site_url
        requested_tenant = _pick(data.tenant_id, current_tenant)
        requested_client = _pick(data.client_id, current_client)
        requested_url = _pick(data.site_url, current_url)
        site_id = sharepoint.site_id
        site_display_name = sharepoint.site_display_name
        new_secret = data.client_secret
        # Re-resolve tylko przy zmianie danych dostępowych albo adresu witryny (kontrakt §3 update).
        creds_changed = (
            requested_tenant != current_tenant
            or requested_client != current_client
            or requested_url != current_url
            or new_secret is not None
        )
        if creds_changed:
            secret = new_secret if new_secret is not None else self._decrypt(row)
            cfg = self._sharepoint_cfg(
                0,
                tenant_id=requested_tenant,
                client_id=requested_client,
                client_secret=secret,
                site_url=requested_url,
                site_id=None,
                excluded_library_names=excluded,
                max_file_size_bytes=max_size,
            )
            resolved = await self._resolve(self._connector(), cfg)
            site_id = resolved.get("site_id")
            site_display_name = resolved.get("site_display_name")
        now_ms = self._now_ms()
        try:
            async with transaction(self._sm()) as session:
                await integrations_repo.update_integration(
                    session,
                    integration_id,
                    name=name,
                    dataset_id=dataset_id,
                    max_file_size_bytes=max_size,
                    ignored_extensions=ignored,
                    scan_interval_seconds=interval,
                    delete_propagation=delete_propagation,
                    is_active=is_active,
                    now_ms=now_ms,
                )
                await integrations_repo.upsert_sharepoint(
                    session,
                    integration_id=integration_id,
                    tenant_id=requested_tenant,
                    client_id=requested_client,
                    site_url=requested_url,
                    site_id=site_id,
                    site_display_name=site_display_name,
                    excluded_library_names=excluded,
                )
                if new_secret is not None:
                    enc, last4 = encrypt_secret(self._key(), integration_id, new_secret)
                    await integrations_repo.set_secret(
                        session, integration_id, secret_enc=enc, secret_last4=last4, now_ms=now_ms
                    )
        except IntegrityError as exc:
            if _is_duplicate_dataset(exc):
                raise Conflict(_dataset_taken(dataset_id)) from exc
            raise
        await self._audit(
            actor, "integration_updated", integration_id, {"changed": _changed_fields(data)}
        )
        return await self.get(integration_id)

    async def delete(self, integration_id: int, actor: Actor) -> None:
        """Usuwa integrację i dane zależne; dokumenty i przebiegi zostają (K7 §7 p. 7)."""
        async with transaction(self._sm()) as session:
            row = await integrations_repo.get_integration(session, integration_id)
        if row is None:
            raise NotFound(NOT_FOUND)
        if row.is_running:
            await self._runs.cancel(integration_id)
        deleted_documents = await self._delete_documents(integration_id)
        async with transaction(self._sm()) as session:
            await integrations_repo.delete_integration(session, integration_id)
        await self._audit(
            actor,
            "integration_deleted",
            integration_id,
            {
                "name": row.name,
                "dataset_id": row.dataset_id,
                "delete_docs": self._config.delete_docs_on_integration_delete,
                "documents_deleted": deleted_documents,
            },
        )

    async def sync(
        self, integration_id: int, *, full: bool, wait: bool, actor: Actor
    ) -> SyncOutcome:
        """Zleca przebieg; ``wait`` czeka na zakończenie do ``wait_timeout_seconds`` (§3 sync)."""
        async with transaction(self._sm()) as session:
            row = await integrations_repo.get_integration(session, integration_id)
            if row is None:
                raise NotFound(NOT_FOUND)
            latest = await integrations_repo.latest_run(session, integration_id)
        previous = latest.id if latest is not None else 0
        try:
            await self._runs.request_sync(integration_id, full=full)
        except Conflict as exc:
            raise Conflict(SYNC_RUNNING) from exc
        await self._audit(
            actor, "integration_sync_requested", integration_id, {"full": full, "wait": wait}
        )
        if not wait:
            return SyncOutcome(True, full, None)
        run = await self._runs.wait_for_run(
            integration_id, since_run_id=previous, timeout_s=self._config.wait_timeout_seconds
        )
        return SyncOutcome(True, full, run)

    async def cancel(self, integration_id: int, actor: Actor) -> CancelResult:
        """Anuluje przebieg (K7 §7 p. 9); brak integracji → ``NotFound("Not found")``."""
        try:
            result = await self._runs.cancel(integration_id)
        except NotFound as exc:
            raise NotFound(NOT_FOUND) from exc
        await self._audit(
            actor,
            "integration_cancelled",
            integration_id,
            {
                "was_running_in_process": result.was_running_in_process,
                "lock_cleared": result.lock_cleared,
                "runs_marked_cancelled": result.runs_marked_cancelled,
            },
        )
        return result

    async def document_link(self, document_id: str) -> DocumentLink:
        """Link do dokumentu źródłowego — deleguje do resolvera z cache (§3, T4)."""
        return await self._links.resolve(document_id)

    # --- pomocnicze ---------------------------------------------------------------

    def _decrypt(self, row: IntegrationRow) -> str:
        """Sekret z bazy do re-resolve; brak zapisanego sekretu → 400 bez szczegółów (09 §11)."""
        if row.secret_enc is None:
            raise ValidationFailed("Cannot save: integration has no stored secret.")
        return decrypt_secret(self._key(), row.id, row.secret_enc)

    async def _insert(
        self, data: IntegrationCreate, *, owner_id: str, resolved: dict[str, Any], now_ms: int
    ) -> int:
        """Jedna transakcja: wiersz integracji, wiersz SharePoint i zaszyfrowany sekret."""
        async with transaction(self._sm()) as session:
            integration_id = await integrations_repo.insert_integration(
                session,
                type=INTEGRATION_TYPE,
                name=data.name,
                dataset_id=data.dataset_id,
                owner_id=owner_id,
                config={},
                ignored_extensions=data.ignored_extensions,
                max_file_size_bytes=data.max_file_size_bytes,
                scan_interval_seconds=data.scan_interval_seconds,
                delete_propagation=data.delete_propagation,
                is_active=data.is_active,
                now_ms=now_ms,
            )
            await integrations_repo.upsert_sharepoint(
                session,
                integration_id=integration_id,
                tenant_id=data.tenant_id,
                client_id=data.client_id,
                site_url=data.site_url,
                site_id=resolved.get("site_id"),
                site_display_name=resolved.get("site_display_name"),
                excluded_library_names=data.excluded_library_names,
            )
            enc, last4 = encrypt_secret(self._key(), integration_id, data.client_secret)
            await integrations_repo.set_secret(
                session, integration_id, secret_enc=enc, secret_last4=last4, now_ms=now_ms
            )
        return integration_id

    async def _delete_documents(self, integration_id: int) -> int:
        """Kasuje dokumenty z mapowań, gdy włączono ``delete_docs_on_integration_delete``."""
        if not self._config.delete_docs_on_integration_delete:
            return 0
        async with transaction(self._sm()) as session:
            mapped = await integrations_repo.mapping_document_ids(session, integration_id)
            existing = await documents_repo.get_many(session, mapped) if mapped else []
        if not existing:
            return 0
        return await self._container.ingest.delete_documents([document.id for document in existing])

    async def _audit(
        self, actor: Actor, action: str, integration_id: int, details: dict[str, object]
    ) -> None:
        """Wpis audytu mutacji (``target_type="integration"``); ``details`` nigdy z sekretem."""
        audit = self._container.audit
        if audit is None:
            raise RuntimeError("container not started")
        await audit.record(
            actor_label=actor.label,
            action=action,
            target_type="integration",
            target_id=str(integration_id),
            details=details,
            actor_id=actor.id,
            ip=actor.ip,
        )
