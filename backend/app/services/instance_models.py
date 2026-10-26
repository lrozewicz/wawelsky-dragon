"""Modele instancji dostawcy: lista, dodawanie, zmiana i usuwanie (K13 §3 p. 7-10, §4 p. 6-8).

Usługa mówi wprost do repozytoriów (``models``, ``provider_instances``) — CONTRACT E3-6b §T3
zabrania importu usługi instancji T2; wspólna jest tylko sonda ``provider_probe``. Trasy
RAGFlow (``routes/provider_models.py``) mapują wyłącznie DTO i kopertę.

Instancja ``default`` nie ma wiersza w tabeli: jej modele mają ``instance_id IS NULL``,
a identyfikator liczony jest tak samo jak w ``routes/models.py`` (``wd-instance:<d>:<url>``);
usługa przyjmuje go w ścieżce obok dosłownej nazwy ``default`` (K13 §0 p. 2).
"""

from __future__ import annotations

import builtins
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db.repositories import models as models_repo
from app.db.repositories import provider_instances as instances_repo
from app.db.repositories.models import ModelRow
from app.db.repositories.provider_instances import InstanceRow
from app.db.uow import transaction
from app.domain.policy import Principal
from app.services import provider_probe
from app.services.concurrency import MAX_CONCURRENCY
from app.services.provider_common import (
    DEFAULT_INSTANCE_NAME,
    PROVIDER_COLUMN,
    decrypt_key,
    dedupe,
    is_default_name,
    require_superuser,
    resolve_provider,
)

if TYPE_CHECKING:
    from app.core.container import Container

# Ranga modelu: WD nie ma rang fabrycznych — wartość ze złota (K13 §3, `DEFAULT_RANK`).
RANK = 500

# `max_tokens` domyślne nowego modelu (K13 §4 p. 6).
DEFAULT_MAX_TOKENS = 8192

# Typ modelu z żądania → wartość kolumny `models.model_type` (K13 §2: `vision` = `image2text`).
MODEL_TYPES: dict[str, str] = {
    "chat": "chat",
    "embedding": "embedding",
    "rerank": "rerank",
    "vision": "image2text",
    "image2text": "image2text",
}

# Odwrotność mapowania `routes/models.MODEL_TYPE_NAMES`: w odpowiedzi zawsze „vision”.
MODEL_TYPE_OUT: dict[str, str] = {"image2text": "vision"}

STATUS_ACTIVE = "active"
STATUS_INACTIVE = "inactive"

# Kolumna `models.model_type` modeli embeddingowych (blokada usunięcia z K13 §4 p. 8).
EMBEDDING = "embedding"

# Klucze ciała PATCH, z których co najmniej jeden musi wystąpić (K13 §4 p. 7).
UPDATE_KEYS = ("status", "max_tokens", "extra")


@dataclass(frozen=True)
class InstanceModelView:
    """Widok modelu instancji (K13 §3, schemat ``InstanceModel``)."""

    name: str
    model_type: str
    max_tokens: int | None
    status: str
    rank: int
    extra: dict[str, Any]
    wd_model_id: str
    wd_dimension: int | None
    wd_is_default: bool


@dataclass(frozen=True)
class SupportedModelView:
    """Model wystawiony przez bramkę (K13 §3, schemat ``SupportedModel``)."""

    name: str
    rank: int
    model_type: str | None = None


@dataclass(frozen=True)
class ResolvedInstance:
    """Instancja dostawcy rozwiązana z ścieżki; ``id = None`` dla syntetycznej `default`."""

    id: str | None
    name: str
    base_url: str
    api_key: str | None


@dataclass(frozen=True)
class _NewModel:
    """Pola nowego modelu po walidacji ciała POST (K13 §4 p. 6)."""

    name: str
    model_type: str
    max_tokens: int
    dimension: int | None
    extra: dict[str, Any] | None


def default_instance_id() -> str:
    """Identyfikator syntetycznej instancji `default` — jak ``instance_id`` w `routes/models.py`."""
    return hashlib.sha256(f"wd-instance:{PROVIDER_COLUMN}:".encode()).hexdigest()[:32]


def _model_view(row: ModelRow) -> InstanceModelView:
    """Wiersz rejestru → element ``InstanceModel`` (K13 §3)."""
    return InstanceModelView(
        name=row.name,
        model_type=MODEL_TYPE_OUT.get(row.model_type, row.model_type),
        max_tokens=row.max_tokens,
        status=STATUS_ACTIVE if row.is_active else STATUS_INACTIVE,
        rank=RANK,
        extra=row.extra if row.extra is not None else {},
        wd_model_id=row.id,
        wd_dimension=row.dimension,
        wd_is_default=row.is_default,
    )


def _extra_or_none(raw: object) -> dict[str, Any] | None:
    """`extra` żądania jako dict; inny typ jak brak; waliduje `max_concurrency` (K13 §3)."""
    if not isinstance(raw, dict):
        return None
    value = raw.get("max_concurrency")
    if "max_concurrency" in raw and not (type(value) is int and 1 <= value <= MAX_CONCURRENCY):
        raise ValidationFailed("extra.max_concurrency must be an integer between 1 and 32")
    return cast("dict[str, Any]", raw)


def _new_model(body: Mapping[str, object]) -> _NewModel:
    """Ciało POST → pola wiersza; komunikaty i wartości domyślne z K13 §4 p. 6."""
    name = body.get("model_name")
    raw_type = body.get("model_type")
    if not isinstance(name, str) or not name or not isinstance(raw_type, str) or not raw_type:
        raise ValidationFailed("model_name and model_type are required")
    model_type = MODEL_TYPES.get(raw_type)
    if model_type is None:
        raise ValidationFailed(f"Invalid model_type '{raw_type}'")
    raw_tokens = body.get("max_tokens")
    raw_dimension = body.get("wd_dimension")
    return _NewModel(
        name=name,
        model_type=model_type,
        max_tokens=raw_tokens if isinstance(raw_tokens, int) else DEFAULT_MAX_TOKENS,
        dimension=raw_dimension
        if model_type == EMBEDDING and isinstance(raw_dimension, int)
        else None,
        extra=_extra_or_none(body.get("extra")),
    )


def _delete_names(body: Mapping[str, object]) -> list[str]:
    """Ciało DELETE → lista nazw bez powtórzeń; brak albo pusta lista → 101 (K13 §4 p. 8)."""
    raw = body.get("model_name")
    if not isinstance(raw, list):
        raise ValidationFailed("model_name is required")
    names = dedupe([item for item in raw if isinstance(item, str) and item])
    if not names:
        raise ValidationFailed("model_name is required")
    return names


# Bramka LiteLLM z wildcardem `openrouter/*` wystawia modele jako `openrouter/<id>`.
OPENROUTER_PREFIX = "openrouter/"
WILDCARD_SUFFIX = "/*"


async def _supported_views(
    base_url: str, names: builtins.list[str]
) -> builtins.list[SupportedModelView]:
    """Lista bramki bez pozycji-wildcardów; dla OpenRouter z typami i modelami z katalogu.

    `/models` bramki nie zna typów i przy wildcardzie nie wylicza modeli embeddingowych ani
    rerank, więc dla bramki OpenRouter (host `openrouter…` albo nazwy `openrouter/…`) dokładamy
    publiczny katalog OpenRouter. Dla innych bramek lista zostaje taka, jak zwróciła sonda.
    """
    concrete = [name for name in names if not name.endswith(WILDCARD_SUFFIX)]
    prefix = OPENROUTER_PREFIX if any(n.startswith(OPENROUTER_PREFIX) for n in concrete) else ""
    is_openrouter = bool(prefix) or "openrouter" in base_url.lower() or len(concrete) < len(names)
    types = await provider_probe.fetch_openrouter_types() if is_openrouter else {}
    merged = {name: types.get(name.removeprefix(prefix)) for name in concrete}
    for model_id, model_type in types.items():
        merged.setdefault(f"{prefix}{model_id}", model_type)
    return [
        SupportedModelView(name=name, rank=RANK, model_type=merged[name]) for name in sorted(merged)
    ]


class InstanceModelService:
    """Modele instancji dostawcy: odczyt dla każdego, zapis tylko dla superusera (K13 §2)."""

    def __init__(self, container: Container) -> None:
        self._container = container

    async def list(  # metoda przesłania wbudowane `list` w zasięgu klasy → `builtins.list`
        self, provider: str, instance: str
    ) -> builtins.list[InstanceModelView]:
        """Modele instancji posortowane po nazwie (K13 §3 p. 7, bez `supported`)."""
        async with transaction(self._sm()) as session:
            resolved = await self._resolve_instance(session, provider, instance)
            rows = await models_repo.list_by_instance(session, resolved.id)
        return [_model_view(row) for row in rows]

    async def supported(
        self, principal: Principal, provider: str, instance: str
    ) -> builtins.list[SupportedModelView]:
        """Modele bramki instancji — sonda `GET {base_url}/models` (K13 §4 p. 5)."""
        require_superuser(principal)
        async with transaction(self._sm()) as session:
            resolved = await self._resolve_instance(session, provider, instance)
        names = await provider_probe.probe_models(resolved.base_url, resolved.api_key)
        return await _supported_views(resolved.base_url, names)

    async def add(
        self, principal: Principal, provider: str, instance: str, body: Mapping[str, object]
    ) -> None:
        """Dodaje model instancji; duplikat (nazwa, typ) w rejestrze → 102 (K13 §4 p. 6)."""
        require_superuser(principal)
        new = _new_model(body)
        model_id = self._container.id_gen.new_id()
        try:
            instance_name = await self._insert(principal, provider, instance, model_id, new)
        except IntegrityError as exc:
            raise Conflict(f"Model '{new.name}' already exists") from exc
        await self._audit(
            principal,
            "model_added",
            model_id=model_id,
            name=new.name,
            model_type=new.model_type,
            instance_name=instance_name,
        )

    async def update(
        self,
        principal: Principal,
        provider: str,
        instance: str,
        model_name: str,
        body: Mapping[str, object],
    ) -> None:
        """Zmienia wszystkie wiersze tej nazwy w instancji (K13 §4 p. 7)."""
        require_superuser(principal)
        if "model_type" in body:
            raise ValidationFailed("model_type cannot be changed")
        if not any(key in body for key in UPDATE_KEYS):
            raise ValidationFailed("At least one of status, max_tokens, or extra is required.")
        status = body.get("status")
        if status is not None and status not in (STATUS_ACTIVE, STATUS_INACTIVE):
            raise ValidationFailed("status must be 'active' or 'inactive'")
        raw_tokens = body.get("max_tokens")
        raw_extra = body.get("extra")
        async with transaction(self._sm()) as session:
            resolved = await self._resolve_instance(session, provider, instance)
            targets = [
                row
                for row in await models_repo.list_by_instance(session, resolved.id)
                if row.name == model_name
            ]
            if not targets:
                raise NotFound(f"Model '{model_name}' not found")
            if status == STATUS_INACTIVE and any(row.is_default for row in targets):
                raise Conflict(
                    f"Model '{model_name}' is a default model; set another default model first"
                    " (PUT /api/v1/system/models/default or Settings → Models) and retry"
                )
            now_ms = self._container.clock.now_ms()
            for row in targets:
                await models_repo.update_fields(
                    session,
                    model_id=row.id,
                    is_active=None if status is None else status == STATUS_ACTIVE,
                    max_tokens=raw_tokens if isinstance(raw_tokens, int) else None,
                    extra=_extra_or_none(raw_extra),
                    now_ms=now_ms,
                )
        instance_name = resolved.name
        for row in targets:
            await self._audit(
                principal,
                "model_updated",
                model_id=row.id,
                name=row.name,
                model_type=row.model_type,
                instance_name=instance_name,
            )

    async def delete(
        self, principal: Principal, provider: str, instance: str, body: Mapping[str, object]
    ) -> None:
        """Usuwa modele instancji — wszystko albo nic, jedna transakcja (K13 §4 p. 8)."""
        require_superuser(principal)
        names = _delete_names(body)
        async with transaction(self._sm()) as session:
            resolved = await self._resolve_instance(session, provider, instance)
            by_name: dict[str, list[ModelRow]] = {}
            for row in await models_repo.list_by_instance(session, resolved.id):
                by_name.setdefault(row.name, []).append(row)
            targets: list[ModelRow] = []
            for name in names:
                found = by_name.get(name)
                if not found:
                    raise NotFound(f"Model '{name}' not found")
                targets.extend(found)
            for name in names:
                for row in by_name[name]:
                    if row.is_default:
                        raise Conflict(
                            f"Model '{name}' is a default model; set another default model first"
                            " (PUT /api/v1/system/models/default or Settings → Models) and retry"
                        )
                    if row.model_type == EMBEDDING:
                        used = await models_repo.count_datasets_using(session, row)
                        if used:
                            raise Conflict(f"Model '{name}' is used by {used} dataset(s)")
            await models_repo.delete_by_ids(session, [row.id for row in targets])
        instance_name = resolved.name
        for row in targets:
            await self._audit(
                principal,
                "model_deleted",
                model_id=row.id,
                name=row.name,
                model_type=row.model_type,
                instance_name=instance_name,
            )

    async def _insert(
        self, principal: Principal, provider: str, instance: str, model_id: str, new: _NewModel
    ) -> str:
        """Wstawia wiersz instancji i zwraca nazwę rozwiązaną instancji (K13 §4 p. 6)."""
        async with transaction(self._sm()) as session:
            resolved = await self._resolve_instance(session, provider, instance)
            duplicate = await models_repo.get_by_name_type_any(session, new.name, new.model_type)
            if duplicate is not None:
                raise Conflict(f"Model '{new.name}' already exists")
            await models_repo.insert_for_instance(
                session,
                id=model_id,
                name=new.name,
                model_type=new.model_type,
                instance_id=resolved.id,
                max_tokens=new.max_tokens,
                dimension=new.dimension,
                extra=new.extra,
                created_by=principal.user_id,
                now_ms=self._container.clock.now_ms(),
            )
        return resolved.name

    async def _resolve_instance(
        self, session: AsyncSession, provider: str, instance: str
    ) -> ResolvedInstance:
        """Instancja ze ścieżki: `default`, jej id syntetyczne albo id/nazwa wiersza (K13 §2)."""
        column = resolve_provider(provider)
        if is_default_name(instance) or instance == default_instance_id():
            return self._default_instance()
        row = await instances_repo.get_by_id(session, instance)
        if row is None:
            row = await instances_repo.get_by_name(session, column, instance)
        if row is None:
            raise NotFound(f"No instance found for provider '{provider}' and instance '{instance}'")
        return ResolvedInstance(
            id=row.id, name=row.name, base_url=row.base_url, api_key=self._instance_key(row)
        )

    def _default_instance(self) -> ResolvedInstance:
        """Syntetyczna instancja `default`: bramka i klucz ze środowiska (K13 §0 p. 2)."""
        settings = self._container.settings
        key = settings.llm_api_key.get_secret_value()
        return ResolvedInstance(
            id=None,
            name=DEFAULT_INSTANCE_NAME,
            base_url=settings.llm_base_url,
            api_key=key or None,
        )

    def _instance_key(self, row: InstanceRow) -> str | None:
        """Klucz instancji z tabeli; None gdy nie zapisano (K13 §1, AAD = id instancji)."""
        if row.api_key_enc is None:
            return None
        return decrypt_key(self._container.settings, row.id, row.api_key_enc)

    async def _audit(  # noqa: PLR0913 — wpis audytu na model (K13 §2)
        self,
        principal: Principal,
        action: str,
        *,
        model_id: str,
        name: str,
        model_type: str,
        instance_name: str,
    ) -> None:
        """Jeden wpis audytu na model; ``details`` bez klucza (K13 §2)."""
        audit = self._container.audit
        if audit is None:
            raise RuntimeError("container not started")
        await audit.record(
            actor_label=principal.email,
            action=action,
            target_type="model",
            target_id=model_id,
            details={"name": name, "model_type": model_type, "instance": instance_name},
            actor_id=principal.user_id,
        )

    def _sm(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera (istnieje po ``start()``)."""
        return cast(async_sessionmaker[AsyncSession], self._container.sessionmaker)
