"""Usługa dokumentów dla /api/v1/datasets/{id}/documents (kontrakt E1-9a C2.2).

Uprawnienia wyłącznie przez ``DatasetService.load`` (jedyne miejsce sprawdzania
datasetu — C1.2). DTO dla prezentertów re-eksportowane (``DocumentRow``,
``DocumentListQuery``, ``UploadSource``), bo ``app.api`` nie może importować
``app.db``. ``Container`` pod ``TYPE_CHECKING`` (wzór: ``app/services/datasets.py``).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories import documents_query
from app.db.repositories.documents import DocumentRow
from app.db.repositories.documents_query import DocumentListQuery
from app.db.uow import transaction
from app.domain.policy import Action, Principal
from app.domain.retrieval.metadata import match_documents, pushdown_condition
from app.services.datasets import (
    MSG_CHUNK_METHOD_UNSUPPORTED,
    UNSUPPORTED_CHUNK_METHODS,
    DatasetService,
    deep_merge,
    unique_name,
)
from app.services.ingest import UploadSource, file_suffix
from app.storage.keys import StorageKey

if TYPE_CHECKING:
    from app.core.container import Container

__all__ = [
    "MSG_CHUNK_METHOD_EMPTY",
    "MSG_DATASET_NOT_FOUND",
    "MSG_DELETE_BOTH",
    "MSG_DELETE_FOREIGN",
    "MSG_DELETE_NEITHER",
    "MSG_DOCS_NOT_FOUND",
    "MSG_DOCUMENT_NOT_OWNED",
    "MSG_DOCUMENT_NOT_OWNED_V024",
    "MSG_DOC_NOT_OWNED",
    "MSG_DUPLICATED_NAME",
    "MSG_EXTENSION_CHANGE",
    "MSG_IMMUTABLE",
    "MSG_STOP_NOT_RUNNING",
    "MSG_UNSUPPORTED_FILE_TYPE",
    "RUN_CODES",
    "DocumentListQuery",
    "DocumentNotOwned",
    "DocumentRow",
    "DocumentService",
    "UnsupportedFileType",
    "UploadSource",
]

RUN_CODES = {  # common/constants.py:106-112
    "UNSTART": "0",
    "RUNNING": "1",
    "CANCEL": "2",
    "DONE": "3",
    "FAIL": "4",
    "SCHEDULE": "5",
}

MSG_DOCS_NOT_FOUND = "Documents not found: {ids}"  # DOC:1614, :1727 ({ids} = repr listy)
MSG_DOC_NOT_OWNED = "you don't own the document {document_id}"  # DOC:924
MSG_DELETE_NEITHER = (  # DOC:1188 (spacja na końcu)
    "should either provide doc ids or set delete_all(true), dataset: {dataset_id}. "
)
MSG_DELETE_BOTH = (  # DOC:1191
    "should not provide both doc ids and delete_all(true), dataset: {dataset_id}. "
)
MSG_DELETE_FOREIGN = (  # DOC:1198 ({ids} = ", ".join)
    "These documents do not belong to dataset {dataset_id} or Document not found: {ids}"
)
MSG_STOP_NOT_RUNNING = "Can't stop parsing document that has not started or already completed"
MSG_EXTENSION_CHANGE = "The extension of file can't be changed"  # VU:1120
MSG_DUPLICATED_NAME = "Duplicated document name in the same dataset."  # VU:1124
MSG_IMMUTABLE = "can't change `{field}`"  # VU:1084-1093
MSG_CHUNK_METHOD_EMPTY = "`chunk_method` (empty string) is not valid"  # VU:1146
MSG_DOCUMENT_NOT_OWNED = "the dataset doesn't own the document"  # v0.27.2 DOC:223
MSG_DOCUMENT_NOT_OWNED_V024 = "The dataset doesn't own the document."  # v0.24.0 sdk/doc.py:244
MSG_DATASET_NOT_FOUND = "Can't find the dataset with ID {dataset_id}!"  # DOC:516
MSG_UNSUPPORTED_FILE_TYPE = "This type of file has not been supported yet!"  # DOC:571, :639


class UnsupportedFileType(ValidationFailed):
    """Upload pliku o nieobsługiwanym rozszerzeniu (DOC:571 → 500, DEC-088 p. 4).

    Trasa zamienia ją na kopertę ``code 500`` z komunikatem ``<nazwa>: <komunikat stałej>``;
    bez przechwycenia (np. w API wd) działa jak ``ValidationFailed`` (101)."""


class DocumentNotOwned(Conflict):
    """PATCH …/documents/{id}: dokument nie należy do datasetu (DOC:223, DEC-088 p. 5d).

    Osobny typ, bo trasa aktualizacji ma własne komunikaty (v0.27.2 bez kropki, v0.24.0
    z kropką) i nie przechodzi przez profil odmowy ``documents_update`` (ten obsługuje
    wyłącznie brak dostępu do datasetu — złoto ``errors_access--16``).
    """


# Kolejność sprawdzania pól niezmiennych w update (C2.2) — pierwszy obecny.
_IMMUTABLE_FIELDS = ("chunk_count", "token_count", "progress")
_DONE_RUN = "3"  # RUN_CODES["DONE"]
_STOPPABLE_RUNS = frozenset({"1", "5"})  # RUNNING, SCHEDULE


class DocumentService:
    """Dokumenty datasetu: upload/list/get/open_file/update/delete/parse/stop."""

    def __init__(self, container: Container) -> None:
        self._container = container

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera (C0 p. 2)."""
        return cast(async_sessionmaker[AsyncSession], self._container.sessionmaker)

    async def upload(
        self, principal: Principal, dataset_id: str, sources: Sequence[UploadSource]
    ) -> list[DocumentRow]:
        """Wgrywa pliki z deduplikacją nazw w ramach datasetu; limit/rozszerzenie w ingest.

        Wszystkie sprawdzenia **przed** jakimkolwiek zapisem: brak datasetu → 102 z jego id
        (upstream DOC:514-516, *przed* kontrolą uprawnień, inaczej profil odmowy dałby 109),
        a nieobsługiwane rozszerzenia → ``UnsupportedFileType`` (upstream DOC:571/705 → 500).
        """
        async with transaction(self._sessionmaker()) as session:
            dataset = await datasets_repo.get_record(session, dataset_id)
        if dataset is None:
            raise Conflict(MSG_DATASET_NOT_FOUND.format(dataset_id=dataset_id))
        await DatasetService(self._container).load(principal, dataset_id, Action.UPDATE)
        unsupported: list[str] = []
        for source in sources:
            try:
                file_suffix(source.filename)
            except ValidationFailed:  # tylko nieznane rozszerzenie (jak `_checked_name`)
                unsupported.append(source.filename)
        if unsupported:
            raise UnsupportedFileType(
                "\n".join(f"{filename}: {MSG_UNSUPPORTED_FILE_TYPE}" for filename in unsupported)
            )
        async with transaction(self._sessionmaker()) as session:
            taken = await documents_query.names_in_dataset(session, dataset_id)
        rows: list[DocumentRow] = []
        for source in sources:
            name = unique_name(source.filename, taken)
            taken.add(name.lower())
            rows.append(
                await self._container.ingest.upload(
                    dataset_id, source, created_by=principal.user_id, name=name
                )
            )
        return rows

    async def get(self, principal: Principal, dataset_id: str, document_id: str) -> DocumentRow:
        """Dokument z datasetu; brak albo inny dataset → NotFound (C2.2)."""
        await DatasetService(self._container).load(principal, dataset_id, Action.READ)
        return await self._load_document(dataset_id, document_id)

    async def open_file(
        self, principal: Principal, dataset_id: str, document_id: str
    ) -> tuple[DocumentRow, AsyncIterator[bytes]]:
        """(wiersz, iterator bajtów pliku); iterator bez konsumowania (C2.2)."""
        row = await self.get(principal, dataset_id, document_id)
        return row, self._container.storage.open(StorageKey(row.location))

    async def update(
        self,
        principal: Principal,
        dataset_id: str,
        document_id: str,
        fields: Mapping[str, Any],
    ) -> DocumentRow:
        """Aktualizacja metadanych wg kolejności C2.2; zwraca świeży wiersz."""
        await DatasetService(self._container).load(principal, dataset_id, Action.UPDATE)
        try:
            row = await self._load_document(dataset_id, document_id)
        except NotFound:  # PATCH ma własny komunikat dokumentu (DOC:223), nie profil odmowy
            raise DocumentNotOwned(MSG_DOCUMENT_NOT_OWNED) from None
        for field in _IMMUTABLE_FIELDS:
            if field in fields:
                raise Conflict(MSG_IMMUTABLE.format(field=field))
        to_save: dict[str, Any] = {}
        if "name" in fields:
            to_save["name"] = await self._checked_name(fields["name"], row, dataset_id)
        if "chunk_method" in fields:
            chunk_method = fields["chunk_method"]
            if chunk_method == "":
                raise Conflict(MSG_CHUNK_METHOD_EMPTY)
            if chunk_method in UNSUPPORTED_CHUNK_METHODS:
                raise ValidationFailed(
                    MSG_CHUNK_METHOD_UNSUPPORTED.format(chunk_method=chunk_method)
                )
            to_save["chunk_method"] = chunk_method
        if fields.get("parser_config"):
            # Upstream ``DocumentService.update_parser_config`` (DOC:1078-1098): rekurencyjny
            # merge, a żądanie bez ``raptor`` kasuje stary klucz (inaczej zostaje poprzednia,
            # pełna konfiguracja RAPTOR-a). Zapisujemy surowy dict, nie model ParserConfig.
            config = deep_merge(row.parser_config, fields["parser_config"])
            if not fields["parser_config"].get("raptor"):
                config.pop("raptor", None)
            to_save["parser_config"] = config
        to_save.update({key: fields[key] for key in ("enabled", "meta_fields") if key in fields})
        async with transaction(self._sessionmaker()) as session:
            await documents_query.update_meta(
                session, document_id, to_save, now_ms=self._container.clock.now_ms()
            )
            fresh = await documents_repo.get(session, document_id)
        if fresh is None:  # wiersz istniał chwilę wcześniej w tej samej transakcji
            raise AssertionError("document row missing after update")
        return fresh

    async def delete(
        self, principal: Principal, dataset_id: str, ids: Sequence[str] | None, delete_all: bool
    ) -> int:
        """Usuwa dokumenty (bez duplikatów id); najpierw wszystkie sprawdzenia (C2.2).

        Przynależność id do datasetu liczymy w Pythonie na zbiorze id datasetu (upstream
        ``document_api.py:1185-1198`` robi tak samo). Porównanie ``id IN (…)`` w SQL
        wywraca się na nie-ASCII wartościach: kolumna ``documents.id`` ma w WD kolacją
        ``ascii_bin``, więc MySQL zgłasza „Illegal mix of collations" (błąd-WD ujawniony
        przez port; id z żądania bywa dowolnym łańcuchem i musi dać 102, nie 100).
        """
        await DatasetService(self._container).load(principal, dataset_id, Action.UPDATE)
        if not ids and not delete_all:
            raise Conflict(MSG_DELETE_NEITHER.format(dataset_id=dataset_id))
        if ids and delete_all:
            raise Conflict(MSG_DELETE_BOTH.format(dataset_id=dataset_id))
        unique_ids = list(dict.fromkeys(ids)) if ids else []
        async with transaction(self._sessionmaker()) as session:
            present = set(await datasets_repo.list_document_ids(session, dataset_id))
        if delete_all:
            target = sorted(present)
        else:
            missing = [doc_id for doc_id in unique_ids if doc_id not in present]
            if missing:
                raise Conflict(
                    MSG_DELETE_FOREIGN.format(dataset_id=dataset_id, ids=", ".join(missing))
                )
            target = unique_ids
        if not target:  # delete_all przy datasetie bez dokumentów → 0 bez ingest (C2.2)
            return 0
        return await self._container.ingest.delete_documents(target)

    async def parse(
        self, principal: Principal, dataset_id: str, document_ids: Sequence[str]
    ) -> tuple[int, list[str]]:
        """Zleca parsowanie: DONE z clear_existing=True, pozostałe bez; (liczba, duplikaty).

        Zachowanie upstream ``document_api.py:1580-1663``: duplikaty id trafiają do
        ``data.errors``, a nieznane id nie przerywają żądania — poprawne dokumenty są
        parsowane, a odpowiedź kończy się 102 (``MSG_DOCS_NOT_FOUND``) dopiero po
        zleceniu. Gdy znanych id nie ma wcale, żądanie kończy się od razu.
        """
        await DatasetService(self._container).load(principal, dataset_id, Action.UPDATE)
        unique_ids = list(dict.fromkeys(document_ids))
        duplicates = [
            f"Duplicate document ids: {doc_id}"
            for doc_id, count in Counter(document_ids).items()
            if count > 1
        ]
        async with transaction(self._sessionmaker()) as session:
            present = await documents_query.ids_in_dataset(session, dataset_id, unique_ids)
        not_found = [doc_id for doc_id in unique_ids if doc_id not in present]
        valid = [doc_id for doc_id in unique_ids if doc_id in present]
        if not valid:
            raise Conflict(MSG_DOCS_NOT_FOUND.format(ids=repr(not_found)))
        async with transaction(self._sessionmaker()) as session:
            docs = await documents_repo.get_many(session, valid)
        run_by_id = {doc.id: doc.run for doc in docs}
        done = [doc_id for doc_id in valid if run_by_id[doc_id] == _DONE_RUN]
        rest = [doc_id for doc_id in valid if run_by_id[doc_id] != _DONE_RUN]
        if done:
            await self._container.ingest.enqueue_parse(done, clear_existing=True)
        if rest:
            await self._container.ingest.enqueue_parse(rest)
        if not_found:
            raise Conflict(MSG_DOCS_NOT_FOUND.format(ids=repr(not_found)))
        return len(valid), duplicates

    async def stop(
        self, principal: Principal, dataset_id: str, document_ids: Sequence[str]
    ) -> tuple[int, list[str]]:
        """Anuluje RUNNING/SCHEDULE; pozostałe → po jednym MSG_STOP_NOT_RUNNING (C2.2)."""
        unique_ids = await self._checked_ids(principal, dataset_id, document_ids)
        async with transaction(self._sessionmaker()) as session:
            docs = await documents_repo.get_many(session, unique_ids)
        run_by_id = {doc.id: doc.run for doc in docs}
        running = [doc_id for doc_id in unique_ids if run_by_id[doc_id] in _STOPPABLE_RUNS]
        if running:
            await self._container.ingest.cancel(running)
        return len(running), [MSG_STOP_NOT_RUNNING] * (len(unique_ids) - len(running))

    async def _load_document(self, dataset_id: str, document_id: str) -> DocumentRow:
        """Dokument po id; brak albo dataset_id ≠ dataset → NotFound (C2.2; grep-test OK)."""
        async with transaction(self._sessionmaker()) as session:
            row = await documents_repo.get(session, document_id)
        if row is None or row.dataset_id != dataset_id:
            raise NotFound(MSG_DOC_NOT_OWNED.format(document_id=document_id))
        return row

    async def _checked_ids(
        self, principal: Principal, dataset_id: str, document_ids: Sequence[str]
    ) -> list[str]:
        """load(UPDATE) + ids bez duplikatów; brakujące → NotFound z repr listy (C2.2)."""
        await DatasetService(self._container).load(principal, dataset_id, Action.UPDATE)
        unique_ids = list(dict.fromkeys(document_ids))
        async with transaction(self._sessionmaker()) as session:
            present = await documents_query.ids_in_dataset(session, dataset_id, unique_ids)
        missing = [doc_id for doc_id in unique_ids if doc_id not in present]
        if missing:
            raise NotFound(MSG_DOCS_NOT_FOUND.format(ids=repr(missing)))
        return unique_ids

    async def _checked_name(self, name: str, row: DocumentRow, dataset_id: str) -> str:
        """Rozszerzenie niezmienione (nawet nieobsługiwane) i nazwa wolna (C2.2).

        Duplikat liczymy porównaniem **dokładnym** (upstream ``d.name == req_doc_name``,
        VU:1122-1124): kolumna ``documents.name`` ma kolację ``utf8mb4_uca1400_ai_ci``, więc
        sam ``=`` w SQL nie odróżnia wielkości liter, a ``RAGFLOW_TEST_UPLOAD_1.TXT`` obok
        ``ragflow_test_upload_1.txt`` jest dla upstreamu poprawną, nową nazwą (DEC-088 p. 5e).
        """
        try:
            suffix = file_suffix(name)
        except ValidationFailed:  # tylko z file_suffix (C2.2)
            raise ValidationFailed(MSG_EXTENSION_CHANGE) from None
        if suffix != row.suffix:
            raise ValidationFailed(MSG_EXTENSION_CHANGE)
        async with transaction(self._sessionmaker()) as session:
            names = await documents_query.exact_names_in_dataset(session, dataset_id)
        if name != row.name and name in names:
            raise Conflict(MSG_DUPLICATED_NAME)
        return name

    # Metoda ``list`` na końcu klasy: dalsza definicja przesłoniłaby wbudowany ``list``
    # w adnotacjach metod zdefiniowanych poniżej (mypy strict).
    async def list(
        self, principal: Principal, dataset_id: str, q: DocumentListQuery
    ) -> tuple[list[tuple[DocumentRow, str]], int]:
        """Strona listy dokumentów datasetu + total (C2.2).

        Istnienie filtrów ``id``/``name`` sprawdzamy OSOBNO, przed listowaniem (upstream
        ``document_api.py:918-927``), komunikatem ``you don't own the document …`` (102);
        puste przecięcie obu filtrów to ``code 0`` z pustą listą — tak samo jak dla listy
        datasetów (DEC-062 p. 3). ``Conflict``, nie ``NotFound``: odmowę trasy
        (``refuse``/``documents_list``) ma dostać wyłącznie brak dostępu do datasetu —
        ten wyjątek oddaje komunikat błędu do koperty ogólnej (K3 §3).

        Zakres ``create_time_from``/``create_time_to`` zawęża stronę PO zapytaniu i nie
        zmienia ``total`` (upstream DOC:972-975 filtruje już pobrane ``docs``).
        """
        await DatasetService(self._container).load(principal, dataset_id, Action.READ)
        async with transaction(self._sessionmaker()) as session:
            if q.document_id is not None and not await documents_query.exists(
                session, dataset_id, document_id=q.document_id
            ):
                raise Conflict(MSG_DOC_NOT_OWNED.format(document_id=q.document_id))
            if q.name is not None and not await documents_query.exists(
                session, dataset_id, name=q.name
            ):
                raise Conflict(MSG_DOC_NOT_OWNED.format(document_id=q.name))
            allowed_ids: frozenset[str] | None = None
            if q.meta_condition is not None:
                # Jedno zapytanie po (id, meta_fields) kandydatów z SQL-owym pushdownem (nadzbiór,
                # DEC-300 p. 2); dopasowanie liczy ``match_documents`` (K11 §10f p. 1) — bez
                # zapytania per dokument.
                pushdown = pushdown_condition(q.meta_condition)
                metas = await documents_query.meta_fields_by_document(
                    session, dataset_id, pushdown=pushdown
                )
                allowed_ids = match_documents(metas, q.meta_condition)
            rows, total = await documents_query.list_page(
                session, dataset_id, q, allowed_ids=allowed_ids
            )
        if q.create_time_from or q.create_time_to:
            rows = [
                (row, nickname)
                for row, nickname in rows
                if (not q.create_time_from or row.create_time >= q.create_time_from)
                and (not q.create_time_to or row.create_time <= q.create_time_to)
            ]
        return rows, total
