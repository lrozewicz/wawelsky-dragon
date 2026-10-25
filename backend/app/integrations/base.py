"""Porty konektora integracji (K12 §2, 09 §3) — bez zależności od bazy i API."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class Container:  # SharePoint: drive (biblioteka dokumentów)
    id: str
    name: str


@dataclass(frozen=True)
class RemoteItem:
    container_id: str
    item_id: str  # stabilny id po stronie źródła
    name: str  # nazwa pliku
    path: str  # ścieżka wyświetlana (bez "root:")
    size: int | None
    content_tag: str | None  # zmienia się tylko przy zmianie treści (SP: cTag)
    meta_tag: str | None  # zmienia się przy zmianie metadanych/nazwy (SP: eTag)
    modified_at: datetime | None
    web_url: str | None
    is_folder: bool
    deleted: bool


@dataclass
class ChangeSet:
    items: list[RemoteItem]
    cursor: str | None  # SP: deltaLink do zapisania po przetworzeniu kontenera
    reset_required: bool = False  # SP: 410 resyncRequired


@dataclass(frozen=True)
class ConnectionReport:
    ok: bool
    checks: list[dict[str, object]]  # kształt DTO testu połączenia (09 §10) buduje E4-3
    resolved: dict[str, object]  # np. {"site_id": ..., "site_display_name": ...}


@dataclass
class SyncCounts:
    added: int = 0
    updated: int = 0
    renamed: int = 0
    deleted: int = 0
    failed: int = 0
    skipped: int = 0


RunTrigger = Literal["schedule", "manual", "full"]
RunStatus = Literal["success", "partial", "failed", "cancelled"]


class Connector(Protocol):
    """Port konektora (adnotacje `cfg` wg DEC-040)."""

    type: str  # "sharepoint"

    async def test_connection(self, cfg: Any, *, dataset_exists: bool) -> ConnectionReport: ...
    async def resolve(self, cfg: Any) -> dict[str, Any]: ...  # np. {"site_id": …}; create/update
    async def list_containers(self, cfg: Any) -> list[Container]: ...  # po filtrach wykluczeń

    def changes(
        self, cfg: Any, container: Container, cursor: str | None
    ) -> AsyncIterator[ChangeSet]: ...

    # strumieniowo na dysk; przerwanie po przekroczeniu max_bytes
    async def download(
        self, cfg: Any, item: RemoteItem, dest_path: Path, *, max_bytes: int
    ) -> int: ...
    async def web_link(self, cfg: Any, container_id: str, item_id: str) -> RemoteItem | None: ...
