"""Paginacja RAGFlow: Page i parse_page (C5)."""

from collections.abc import Mapping
from dataclasses import dataclass

from app.api.ragflow.messages import MSG_FIELD_INVALID, literal_message
from app.api.ragflow.normalize.common import to_bool
from app.core.errors import ValidationFailed


@dataclass(frozen=True)
class Page:
    """Znormalizowane parametry listy (C5)."""

    page: int
    page_size: int
    orderby: str
    desc: bool


def _to_int(value: str | None) -> int | None:
    """int(value) bez wyjątku; wartość nieliczbowa → None."""
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_page(  # noqa: PLR0913 — sygnatura z kontraktu C5
    query: Mapping[str, str],
    *,
    default_size: int = 30,
    max_size: int,
    orderby_allowed: frozenset[str] = frozenset({"create_time", "update_time"}),
    default_orderby: str = "create_time",
    allow_zero_size: bool = False,
) -> Page:
    """Normalizacja page/page_size/orderby/desc — reguły dosłownie z C5.

    „Liczbowy” = int(v) bez wyjątku; page_size 0 honorowany tylko z allow_zero_size.
    """
    page = _to_int(query.get("page"))
    if page is None or page < 1:
        page = 1
    size = _to_int(query.get("page_size"))
    if size == 0 and allow_zero_size:
        size = 0
    elif size is None or size < 1:
        size = default_size
    elif size > max_size:
        size = max_size
    orderby = query.get("orderby", default_orderby)
    if orderby not in orderby_allowed:
        raise ValidationFailed(
            MSG_FIELD_INVALID.format(
                field="orderby",
                msg=literal_message(orderby_allowed),
                value=orderby,
            )
        )
    raw_desc = query.get("desc")
    desc = True if raw_desc is None else to_bool(raw_desc)
    return Page(page=page, page_size=size, orderby=orderby, desc=desc)
