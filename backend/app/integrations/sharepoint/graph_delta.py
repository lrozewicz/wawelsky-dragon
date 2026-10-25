"""Delta napędu Graph: `decode_item` i strony `iter_delta` (WP E4-2a, 09 §7.4)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.integrations.base import ChangeSet, RemoteItem
from app.integrations.sharepoint.errors import GraphError, GraphNotFound

if TYPE_CHECKING:
    from app.integrations.sharepoint.graph import GraphClient

HTTP_GONE = 410


def decode_item(raw: Mapping[str, Any], drive_id: str) -> RemoteItem:
    """Buduje `RemoteItem` z surowego driveItem; toleruje braki typowe dla delty."""
    name = raw.get("name", "")
    reference = raw.get("parentReference")
    parent_path = reference.get("path") if isinstance(reference, Mapping) else None
    if not name:
        path = ""
    elif isinstance(parent_path, str):
        path = f"{parent_path.partition('root:')[2]}/{name}"
    else:
        path = f"/{name}"

    modified_raw = raw.get("lastModifiedDateTime")
    modified_at: datetime | None = None
    if isinstance(modified_raw, str):
        normalized = modified_raw[:-1] + "+00:00" if modified_raw.endswith("Z") else modified_raw
        try:
            modified_at = datetime.fromisoformat(normalized)
        except ValueError:
            modified_at = None

    return RemoteItem(
        container_id=drive_id,
        item_id=raw["id"],
        name=name,
        path=path,
        size=raw.get("size"),
        content_tag=raw.get("cTag") or raw.get("eTag"),
        meta_tag=raw.get("eTag"),
        modified_at=modified_at,
        web_url=raw.get("webUrl"),
        is_folder="folder" in raw,
        deleted="deleted" in raw,
    )


async def iter_delta(
    client: GraphClient, drive_id: str, cursor: str | None, max_pages: int
) -> AsyncIterator[ChangeSet]:
    """Strumieniuje strony delty; 410 → jeden `ChangeSet` z `reset_required=True`."""
    # Import w funkcji, nie na górze: graph.py importuje ten moduł (cykl modułów).
    from app.integrations.sharepoint.graph import DELTA_SELECT  # noqa: PLC0415

    url = cursor if cursor is not None else f"/drives/{drive_id}/root/delta"
    params: Mapping[str, str] | None = None if cursor is not None else {"$select": DELTA_SELECT}
    page_number = 0
    while True:
        page_number += 1
        if page_number > max_pages:
            raise GraphError(0, "deltaPageLimitExceeded", f"delta page limit exceeded: {max_pages}")
        try:
            response = await client.request("GET", url, params=params)
        except GraphNotFound as exc:
            if exc.status != HTTP_GONE:
                raise
            yield ChangeSet(items=[], cursor=None, reset_required=True)
            return

        page: dict[str, Any] = response.json()
        items = [decode_item(raw, drive_id) for raw in page.get("value", [])]
        delta_link = page.get("@odata.deltaLink")
        if delta_link is not None:
            yield ChangeSet(items=items, cursor=delta_link)
            return
        next_link = page.get("@odata.nextLink")
        if next_link is None:
            raise GraphError(0, "deltaMalformed", "page has neither nextLink nor deltaLink")
        yield ChangeSet(items=items, cursor=None)
        url = next_link
        params = None
