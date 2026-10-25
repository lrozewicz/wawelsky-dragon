"""Test-double konektora integracji (kontrakt C8) — in-memory, bez sieci i bazy."""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from app.integrations.base import ChangeSet, ConnectionReport, Container, RemoteItem


def make_item(  # noqa: PLR0913, PLR0917 — skrót testowy z domyślnymi z kontraktu C8
    container_id: str = "c1",
    item_id: str = "i1",
    name: str = "a.txt",
    path: str = "/a.txt",
    size: int | None = 1,
    content_tag: str = "c1",
    meta_tag: str = "m1",
    is_folder: bool = False,
    deleted: bool = False,
    web_url: str | None = None,
    modified_at: datetime | None = None,
) -> RemoteItem:
    """Buduje ``RemoteItem`` z domyślnymi z kontraktu C8."""
    return RemoteItem(
        container_id=container_id,
        item_id=item_id,
        name=name,
        path=path,
        size=size,
        content_tag=content_tag,
        meta_tag=meta_tag,
        modified_at=modified_at,
        web_url=web_url,
        is_folder=is_folder,
        deleted=deleted,
    )


class FakeConnector:
    """Skryptowany konektor (C8): jedno wywołanie ``changes`` = jedno przejście silnika."""

    type: str = "fake"

    def __init__(self) -> None:
        self.containers: list[Container] = []
        self.files: dict[tuple[str, str], bytes] = {}
        self.fail_download: dict[tuple[str, str], Exception] = {}
        self.calls: list[tuple[str, ...]] = []
        self.block: asyncio.Event | None = None
        # container_id -> kolejka przejść; przejście = lista stron (ChangeSet-ów)
        self._runs: dict[str, list[list[ChangeSet]]] = {}
        # container_id -> stan pełny emitowany po sygnale reset_required
        self._reset_after: dict[str, list[ChangeSet]] = {}

    def script(self, container_id: str, changesets: list[ChangeSet]) -> None:
        """Ustawia pierwsze przejście: jedno wywołanie ``changes`` emituje wszystkie strony."""
        self._runs[container_id] = [list(changesets)]

    def script_run(self, container_id: str, changesets: list[ChangeSet]) -> None:
        """Dokłada kolejne przejście (kolejne wywołanie ``changes``)."""
        self._runs.setdefault(container_id, []).append(list(changesets))

    def script_reset(
        self, container_id: str, first: list[ChangeSet], after_reset: list[ChangeSet]
    ) -> None:
        """Przejście ``first``, potem sygnał ``reset_required``, potem stan ``after_reset``."""
        self._runs[container_id] = [list(first)]
        self._reset_after[container_id] = list(after_reset)

    async def test_connection(self, cfg: Any, *, dataset_exists: bool) -> ConnectionReport:
        return ConnectionReport(ok=True, checks=[], resolved={})

    async def resolve(self, cfg: Any) -> dict[str, Any]:
        return {}

    async def list_containers(self, cfg: Any) -> list[Container]:
        return self.containers

    async def changes(
        self, cfg: Any, container: Container, cursor: str | None
    ) -> AsyncIterator[ChangeSet]:
        self.calls.append(("changes", container.id, cursor))
        pending = self._reset_after.pop(container.id, None)
        if pending is not None and cursor is not None:
            # kolejne wywołanie z cursor=None ma zwrócić pełny stan po resecie
            self._runs[container.id] = [pending]
            yield ChangeSet(items=[], cursor=None, reset_required=True)
            return
        if pending is not None:
            # cursor=None — sygnał resetu jeszcze nie zadziałał, wraca przy następnym wywołaniu
            self._reset_after[container.id] = pending
        runs = self._runs.get(container.id) or []
        if runs:
            for changeset in runs.pop(0):
                yield changeset
            return
        yield ChangeSet(items=[], cursor=cursor)

    async def download(self, cfg: Any, item: RemoteItem, dest_path: Path, *, max_bytes: int) -> int:
        self.calls.append(("download", item.container_id, item.item_id))
        if self.block is not None:
            await self.block.wait()
        failure = self.fail_download.get((item.container_id, item.item_id))
        if failure is not None:
            raise failure
        payload = self.files.get((item.container_id, item.item_id), b"content")
        if len(payload) > max_bytes:
            raise ValueError("too large")
        await asyncio.to_thread(dest_path.write_bytes, payload)
        return len(payload)

    async def web_link(self, cfg: Any, container_id: str, item_id: str) -> RemoteItem | None:
        return None


async def fake_load_config(row: Any) -> object:
    """``ConfigLoader`` dla testów — zwraca puste cfg (kontrakt C8)."""
    return {}
