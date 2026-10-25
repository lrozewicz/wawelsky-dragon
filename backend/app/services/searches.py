"""Usługa wyszukiwarek — CRUD (CONTRACT E4-4a §D1, §D4; K15 §1).

Port ``search_api.py`` v0.27.2 (create/list/detail/update/delete). Uprawnienia wyłącznie
przez ``app.domain.policy`` (K5 §7.2), komunikaty błędów dosłownie z §D4. ``kb_ids``
nie trafia do kolumny ``search_config`` — wiązania żyją w ``search_datasets`` (§D1),
a serwis wyciąga je z ``search_config`` żądania (albo z jawnego parametru ``kb_ids``).
``config_for_recommendation`` (T4) zwraca wiersz dla rekomendacji pytań; ``ask`` (T3) buduje
strumień completion.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import searches as searches_repo
from app.db.repositories.datasets import DatasetRecord
from app.db.repositories.searches import SearchRow
from app.db.uow import transaction
from app.domain.chat.config import ASK_RETRIEVAL, RetrievalDefaults, merge_prompt_config
from app.domain.chat.events import StreamIds
from app.domain.policy import Action, ResourceRef, can
from app.domain.retrieval.metadata import meta_data_filter_to_condition
from app.domain.search.config import default_config
from app.prompts import load_prompt
from app.services.chat import ChatStream, CompletionRequest
from app.services.chat_pipeline import RunContext, safe_events

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.container import Container
    from app.domain.policy.principal import Principal
    from app.llm.types import ModelRef

__all__ = ["SearchView", "SearchesService", "unique_name"]

# Dopisek duplikatu nazwy — semantyka upstream ``duplicate_name`` (§D4): ``a`` → ``a(1)``.
_COUNTER_RE: Final = re.compile(r"^(.*?)\((\d+)\)$")
_MAX_NAME_ATTEMPTS: Final = 1000
# Limity nazwy: 255 bajtów UTF-8 (upstream create) i 128 znaków (kolumna VARCHAR(128)).
_MAX_NAME_BYTES: Final = 255
_MAX_NAME_CHARS: Final = 128

# Prompt completion (§D1, §D7): plik trzyma ORYGINAŁ z ``{{ knowledge }}`` (jinja upstream),
# a pipeline WD podstawia pojedynczo nawiasowane ``{knowledge}`` (``build_system``).
_ASK_SUMMARY_SYSTEM: Final = load_prompt("ask_summary").replace("{{ knowledge }}", "{knowledge}")


@dataclass(frozen=True)
class SearchView:
    """Widok wyszukiwarki (§D4): wiersz + ``kb_ids`` z ``search_datasets``.

    ``owner_nickname``/``tenant_avatar`` wypełnia lista; szczegół zostawia ``None``.
    """

    row: SearchRow
    kb_ids: list[str]
    owner_nickname: str | None = None
    tenant_avatar: str | None = None


async def unique_name(name: str, taken: Callable[[str], Awaitable[bool]]) -> str:
    """Pierwsza wolna nazwa wg semantyki upstream ``duplicate_name`` (§D4).

    ``name`` wolna → ``name``; zajęta → baza z ``^(.*?)\\((\\d+)\\)$`` i licznik+1
    (brak dopisku → baza = nazwa, licznik 0). Po 1000 nieudanych próbach → ``RuntimeError``.
    """
    current = name
    for _ in range(_MAX_NAME_ATTEMPTS):
        if not await taken(current):
            return current
        match = _COUNTER_RE.search(current)
        base = name if match is None else match.group(1).rstrip()
        counter = 0 if match is None else int(match.group(2))
        current = f"{base}({counter + 1})"
    raise RuntimeError(
        f"Failed to generate unique name within {_MAX_NAME_ATTEMPTS} attempts. Original: {name}"
    )


def _validated_name(name: object) -> str:
    """Nazwa po walidacji i ``strip`` (§D4); komunikaty dosłownie z upstreamu."""
    if not isinstance(name, str):
        raise ValidationFailed("Search name must be string.")
    if name.strip() == "":
        raise ValidationFailed("Search name can't be empty.")
    if len(name.encode("utf-8")) > _MAX_NAME_BYTES or len(name) > _MAX_NAME_CHARS:
        raise ValidationFailed(f"Search name length is {len(name)} which is large than 255.")
    return name.strip()


def _config_kb_ids(config: object) -> list[str]:
    """``kb_ids`` z żądania jako lista; brak klucza lub nie-lista → ``[]`` (§D1)."""
    if not isinstance(config, Mapping):
        return []
    ids = config.get("kb_ids")
    return [str(item) for item in ids] if isinstance(ids, list) else []


def _search_ref(row: SearchRow) -> ResourceRef:
    """ResourceRef wyszukiwarki (§D1): decyzje zapadają w ``can``/``require`` z policy."""
    return ResourceRef(kind="search", owner_id=row.tenant_id, id=row.id)


def _dataset_ref(record: DatasetRecord) -> ResourceRef:
    """ResourceRef datasetu (wzór ``_dataset_ref`` z ``app/services/chat.py``)."""
    return ResourceRef(
        kind="dataset", owner_id=record.tenant_id, permission=record.permission, id=record.id
    )


async def _validate_kb_ids(
    session: AsyncSession, principal: Principal, dataset_ids: Sequence[str]
) -> None:
    """Każdy dataset istnieje i jest czytelny dla principala, inaczej 102 (§D4)."""
    for dataset_id in dataset_ids:
        record = await datasets_repo.get_record(session, dataset_id)
        if record is None or not can(principal, Action.READ, _dataset_ref(record)):
            raise ValidationFailed(f"You don't own the dataset {dataset_id}")


class SearchesService:
    """CRUD wyszukiwarek (§D4); transakcje przez ``app.db.uow.transaction`` (wzór chats.py)."""

    def __init__(self, container: Container) -> None:
        """Zapamiętuje kontener; bez I/O — właściwość może powstać przed ``start()``."""
        self._container = container

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Sessionmaker kontenera; bez startu → RuntimeError (wzór app/services/chats.py)."""
        if self._container.sessionmaker is None:
            raise RuntimeError("container not started")
        return self._container.sessionmaker

    async def create(  # noqa: PLR0913 — sygnatura z kontraktu §D4
        self,
        principal: Principal,
        *,
        name: str,
        description: str,
        avatar: str | None,
        search_config: dict[str, Any] | None,
        kb_ids: list[str] | None,
    ) -> str:
        """Tworzy wyszukiwarkę i zwraca jej id (§D4).

        ``search_config=None`` → ``default_config()``; podany obiekt zapisujemy dosłownie.
        ``kb_ids`` nigdy nie trafia do kolumny (§D1) — jest wiązane w ``search_datasets``.
        Wiązania: parametr ``kb_ids`` (gdy trasa wyciągnie je sama), inaczej ``kb_ids``
        z ``search_config``, po walidacji dostępności datasetów.
        """
        validated = _validated_name(name)
        source = default_config() if search_config is None else search_config
        config = {key: value for key, value in source.items() if key != "kb_ids"}
        requested = kb_ids if kb_ids is not None else _config_kb_ids(source)
        search_id = self._container.id_gen.new_id()
        async with transaction(self._sessionmaker()) as session:
            await _validate_kb_ids(session, principal, requested)
            unique = await unique_name(
                validated,
                _taken_in(session, principal.user_id),
            )
            await searches_repo.insert(
                session,
                id=search_id,
                tenant_id=principal.user_id,
                name=unique,
                description=description,
                avatar=avatar,
                search_config=config,
                now_ms=self._container.clock.now_ms(),
            )
            await searches_repo.set_dataset_ids(session, search_id, requested)
        return search_id

    async def get(self, principal: Principal, search_id: str) -> SearchView:
        """Widok wyszukiwarki (§D4); brak lub cudza → ``PermissionDenied`` (trasa → 103)."""
        async with transaction(self._sessionmaker()) as session:
            row = await searches_repo.get(session, search_id)
            if row is None or not can(principal, Action.READ, _search_ref(row)):
                raise PermissionDenied("Has no permission for this operation.")
            kb_ids = await searches_repo.list_dataset_ids(session, search_id)
        return SearchView(row=row, kb_ids=kb_ids)

    async def config_for_recommendation(
        self, principal: Principal, search_id: str
    ) -> SearchRow | None:
        """Wiersz wyszukiwarki dla rekomendacji pytań (§D4, §D7, T4).

        ``None`` — brak wyszukiwarki albo cudza; trasa zamienia to na kopertę odmowy
        (ta sama co dla tras czatu), więc metoda nie rzuca wyjątku.
        """
        async with transaction(self._sessionmaker()) as session:
            row = await searches_repo.get(session, search_id)
        if row is None or not can(principal, Action.READ, _search_ref(row)):
            return None
        return row

    async def list(  # noqa: PLR0913 — sygnatura z kontraktu §D4
        self,
        principal: Principal,
        *,
        keywords: str,
        orderby: str,
        desc: bool,
        page: int,
        page_size: int,
        owner_ids: list[str],
    ) -> tuple[list[SearchView], int]:
        """Strona wyszukiwarek principala (§D4, §D5); ``owner_ids`` bez właściciela → pusto."""
        if owner_ids and principal.user_id not in owner_ids:
            return [], 0
        async with transaction(self._sessionmaker()) as session:
            rows, total = await searches_repo.list_page(
                session,
                principal.user_id,
                keywords=keywords,
                orderby=orderby,
                desc=desc,
                page=page,
                page_size=page_size,
            )
            bindings = await searches_repo.list_dataset_ids_many(
                session, [item.row.id for item in rows]
            )
        return [
            SearchView(
                row=item.row,
                kb_ids=bindings.get(item.row.id, []),
                owner_nickname=item.nickname,
                tenant_avatar=item.tenant_avatar,
            )
            for item in rows
        ], total

    async def update(  # noqa: PLR0913 — sygnatura z kontraktu §D4
        self,
        principal: Principal,
        search_id: str,
        *,
        name: str,
        search_config: Any,
        description: str | None,
        avatar: str | None,
    ) -> SearchView:
        """Aktualizacja (§D4, kolejność jak upstream): nazwa → własność → duplikat → typ.

        ``search_config`` scalany z zapisanym (``kb_ids`` obsługiwane osobno), ``None``
        w ``description``/``avatar`` znaczy „bez zmiany”.
        """
        validated = _validated_name(name)
        async with transaction(self._sessionmaker()) as session:
            current = await searches_repo.get(session, search_id)
            if current is None or not can(principal, Action.UPDATE, _search_ref(current)):
                raise PermissionDenied("no authorization")
            if validated.lower() != current.name.lower() and await searches_repo.name_taken(
                session, principal.user_id, validated, exclude_id=search_id
            ):
                raise ValidationFailed("Duplicated search name.")
            if not isinstance(search_config, dict):
                raise ValidationFailed("search_config must be a JSON object")
            merged = {
                **current.search_config,
                **{key: value for key, value in search_config.items() if key != "kb_ids"},
            }
            if "kb_ids" in search_config:
                requested = _config_kb_ids(search_config)
                await _validate_kb_ids(session, principal, requested)
                await searches_repo.set_dataset_ids(session, search_id, requested)
            await searches_repo.update(
                session,
                search_id,
                name=validated,
                description=current.description if description is None else description,
                avatar=current.avatar if avatar is None else avatar,
                search_config=merged,
                now_ms=self._container.clock.now_ms(),
            )
            row = await self._load(session, search_id)
            kb_ids = await searches_repo.list_dataset_ids(session, search_id)
        return SearchView(row=row, kb_ids=kb_ids)

    async def delete(self, principal: Principal, search_id: str) -> None:
        """Twarde usunięcie (§D4); brak lub cudza → ``PermissionDenied("no authorization")``."""
        async with transaction(self._sessionmaker()) as session:
            row = await searches_repo.get(session, search_id)
            if row is None or not can(principal, Action.DELETE, _search_ref(row)):
                raise PermissionDenied("no authorization")
            await searches_repo.delete(session, search_id)

    async def ask(
        self, principal: Principal, search_id: str, question: str, body_kb_ids: Sequence[str]
    ) -> ChatStream:
        """Strumień podsumowania AI wyszukiwarki (§D7, port ``async_ask`` v0.27.2).

        Kolejność kontroli PRZED otwarciem strumienia (K15 §2 p. 4, złoto --24/--25):
        własność (109) → ``kb_ids`` z ``search_datasets`` albo ciała żądania (pusty → 102)
        → każdy dataset istnieje i jest czytelny (102). Sparsowane chunki nie są wymagane
        (DEC-174 p. 3).
        """
        async with transaction(self._sessionmaker()) as session:
            row = await searches_repo.get(session, search_id)
            if row is None or not can(principal, Action.READ, _search_ref(row)):
                raise PermissionDenied("no authorization")
            kb_ids = await searches_repo.list_dataset_ids(session, search_id) or list(body_kb_ids)
            if not kb_ids:
                raise ValidationFailed("`kb_ids` is required.")
            await _validate_kb_ids(session, principal, kb_ids)
        config = row.search_config
        model = await self._chat_model(config.get("chat_id") or None)
        # Puste ``doc_ids`` → ``None``: w retrievalu ``()`` znaczy „żaden dokument" (M6 p. 6),
        # a brak klucza w ``search_config`` znaczy brak zawężenia.
        doc_ids = tuple(str(item) for item in config.get("doc_ids") or [])
        # ``search_config.meta_data_filter`` stosowane jak w czacie (K11 §10f p. 5): ``manual``
        # → warunek tutaj, ``auto``/``semi_auto`` → model w kroku retrievalu (surowa specyfikacja).
        meta_data_filter = config.get("meta_data_filter")
        metadata = None
        if isinstance(meta_data_filter, Mapping):
            if meta_data_filter.get("method") in ("auto", "semi_auto"):
                pass
            else:
                metadata = meta_data_filter_to_condition(meta_data_filter)
                meta_data_filter = None
        else:
            meta_data_filter = None
        req = CompletionRequest(
            chat_id=None,
            session_id=None,
            messages=({"role": "user", "content": question},),
            llm_setting=config.get("llm_setting") or {},
            store_history_messages=False,
            pass_all_history_messages=True,
            doc_ids=doc_ids or None,
            source="api",
        )
        ctx = RunContext(
            container=self._container,
            req=req,
            chat=None,
            prompt_config=merge_prompt_config(
                {"system": _ASK_SUMMARY_SYSTEM, "empty_response": ""}
            ),
            model=model,
            dataset_ids=tuple(kb_ids),
            session_id=None,
            ids=StreamIds(
                message_id=self._container.id_gen.new_id(), session_id=None, chat_id=None
            ),
            metadata=metadata,
            meta_data_filter=meta_data_filter,
            retrieval=RetrievalDefaults(
                page_size=ASK_RETRIEVAL.page_size,
                similarity_threshold=config.get("similarity_threshold", 0.2),
                vector_similarity_weight=config.get("vector_similarity_weight", 0.3),
                top_k=config.get("top_k", 1024),
                rerank_candidates_count=config.get("rerank_candidates_count", 100),
            ),
            rerank_model=config.get("rerank_id") or None,
        )
        return ChatStream(ids=ctx.ids, events=safe_events(ctx))

    async def _chat_model(self, chat_id: str | None) -> ModelRef:
        """Model czatu ``search_config.chat_id``; puste → domyślny (DEC-174 p. 1).

        ``chat_id`` niepusty, ale nierozwiązywalny → ``ValidationFailed`` z komunikatem
        rejestru (102 przed strumieniem, §D7).
        """
        models = self._container.models
        if models is None:
            raise RuntimeError("container not started")
        try:
            return await models.resolve(chat_id, "chat")
        except NotFound as err:
            raise ValidationFailed(str(err)) from None

    async def _load(self, session: AsyncSession, search_id: str) -> SearchRow:
        """Wiersz po id w bieżącej sesji; brak → ``NotFound`` (§D4)."""
        row = await searches_repo.get(session, search_id)
        if row is None:
            raise NotFound(f"Cannot find search {search_id}")
        return row


def _taken_in(session: AsyncSession, tenant_id: str) -> Callable[[str], Awaitable[bool]]:
    """``taken`` dla ``unique_name``: ``name_taken`` w podanej transakcji (§D4)."""

    async def taken(candidate: str) -> bool:
        return await searches_repo.name_taken(session, tenant_id, candidate)

    return taken
