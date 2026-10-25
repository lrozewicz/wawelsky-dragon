"""Usługa instancji dostawców: odczyt, zapis i sonda połączenia (K13 §3-§4, CONTRACT E3-6b §T2).

Logika bez HTTP: trasy ``routes/provider_instances.py`` tylko mapują DTO i błędy. Klucz API
nigdy nie wraca w plaintekście — widoki niosą wyłącznie informację, czy klucz istnieje.
Syntetyczna instancja ``default`` (środowiskowa) nie ma wiersza w tabeli: jej ``base_url``
i klucz pochodzą z ``Settings``, a ``id`` (w warstwie API) z ``instance_id("litellm", …)``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db.repositories import models as models_repo
from app.db.repositories import provider_instances as instances_repo
from app.db.uow import transaction
from app.domain.policy import Principal
from app.services import provider_probe
from app.services.provider_common import (
    API_KEY_MASK,
    DEFAULT_INSTANCE_NAME,
    decrypt_key,
    dedupe,
    encrypt_key,
    is_default_name,
    normalize_base_url,
    require_superuser,
    resolve_provider,
)

if TYPE_CHECKING:
    from app.core.container import Container

# Komunikaty reguł K13 §4 p. 1-3 (dosłowne).
INSTANCE_REQUIRED = "instance_name is required"
BASE_URL_REQUIRED = "base_url is required"
INSTANCES_REQUIRED = "instances is required"
DEFAULT_MANAGED = "Instance 'default' is managed by environment configuration"


@dataclass(frozen=True)
class InstanceView:
    """Widok instancji dla trasy; ``id`` jest ``None`` tylko dla syntetycznej ``default``."""

    id: str | None
    name: str
    base_url: str
    has_api_key: bool
    managed: bool


@dataclass(frozen=True)
class ResolvedInstance:
    """Rozwiązana instancja (K13 §2); ``api_key`` to plaintext wyłącznie na użytek sondy."""

    id: str | None
    name: str
    base_url: str
    api_key: str | None
    managed: bool


# Aliasy typów: metoda ``list`` (K13 §3) przesłania wbudowany ``list`` w zasięgu klasy (mypy).
_InstanceTargets = list[tuple[str, str]]
_Ids = list[str]


class ProviderInstanceService:
    """Instancje dostawcy ``litellm``: odczyt dla zalogowanych, zapis tylko superuser (K13 §2)."""

    def __init__(self, container: Container) -> None:
        self._container = container

    async def list(self, provider: str) -> list[InstanceView]:
        """Instancje tabeli dostawcy, najnowsze pierwsze (K13 §3 p. 1).

        Syntetyczną ``default`` dokłada trasa (K13 §0 p. 2).
        """
        column = resolve_provider(provider)
        async with transaction(self._sm()) as session:
            rows = await instances_repo.list_by_provider(session, column)
        return [
            InstanceView(
                id=row.id,
                name=row.name,
                base_url=row.base_url,
                has_api_key=row.api_key_enc is not None,
                managed=False,
            )
            for row in rows
        ]

    async def get(self, provider: str, instance: str) -> InstanceView:
        """Instancja po id albo nazwie; ``default`` jest syntetyczna (K13 §2, §3 p. 3)."""
        resolved = await self.resolve_instance(provider, instance)
        return InstanceView(
            id=resolved.id,
            name=resolved.name,
            base_url=resolved.base_url,
            has_api_key=resolved.api_key is not None,
            managed=resolved.managed,
        )

    async def resolve_instance(self, provider: str, instance: str) -> ResolvedInstance:
        """Instancja po id albo nazwie; ``default`` z ``Settings`` (K13 §2)."""
        column = resolve_provider(provider)
        if is_default_name(instance):
            settings = self._container.settings
            return ResolvedInstance(
                id=None,
                name=DEFAULT_INSTANCE_NAME,
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key.get_secret_value() or None,
                managed=True,
            )
        async with transaction(self._sm()) as session:
            row = await instances_repo.get_by_id(session, instance)
            if row is None or row.provider != column:
                row = await instances_repo.get_by_name(session, column, instance)
        if row is None:
            raise NotFound(f"No instance found for provider '{provider}' and instance '{instance}'")
        key = None
        if row.api_key_enc is not None:
            key = decrypt_key(self._container.settings, row.id, row.api_key_enc)
        return ResolvedInstance(
            id=row.id, name=row.name, base_url=row.base_url, api_key=key, managed=False
        )

    async def create(self, principal: Principal, provider: str, body: Mapping[str, object]) -> None:
        """Zakłada instancję dostawcy (K13 §4 p. 1); tylko superuser."""
        require_superuser(principal)
        column = resolve_provider(provider)
        name = self._required_name(body)
        base_url = self._required_base_url(body)
        if is_default_name(name) or await self._exists(column, name):
            raise Conflict(f"Instance '{name}' already exists")
        key = body.get("api_key")
        plain = key if isinstance(key, str) and key else None
        instance_id = self._container.id_gen.new_id()
        enc = (
            encrypt_key(self._container.settings, instance_id, plain) if plain is not None else None
        )
        try:
            async with transaction(self._sm()) as session:
                await instances_repo.insert(
                    session,
                    id=instance_id,
                    provider=column,
                    name=name,
                    base_url=base_url,
                    api_key_enc=enc,
                    created_by=principal.user_id,
                    now_ms=self._container.clock.now_ms(),
                )
        except IntegrityError as exc:
            # Wyścig: nazwa dodana równolegle po sprawdzeniu `_exists` (K13 §4 p. 1) — jak przy
            # sprawdzeniu wstępnym, 102 z tym samym komunikatem.
            raise Conflict(f"Instance '{name}' already exists") from exc
        await self._audit(
            principal, "provider_instance_created", instance_id, {"name": name, "provider": column}
        )

    async def update(
        self, principal: Principal, provider: str, instance: str, body: Mapping[str, object]
    ) -> None:
        """Zmienia instancję tabeli (K13 §4 p. 2); ``default`` i superuser wg reguł."""
        require_superuser(principal)
        column = resolve_provider(provider)
        name, raw_base_url = self._required_fields(body)
        base_url = normalize_base_url(raw_base_url)
        resolved = await self.resolve_instance(provider, instance)
        if resolved.managed:
            raise Conflict(DEFAULT_MANAGED)
        if is_default_name(name) or await self._taken(column, name, cast(str, resolved.id)):
            raise Conflict(f"Instance '{name}' already exists")
        set_key, enc = self._update_key(body, cast(str, resolved.id))
        async with transaction(self._sm()) as session:
            await instances_repo.update(
                session,
                instance_id=cast(str, resolved.id),
                name=name,
                base_url=base_url,
                api_key_enc=enc,
                set_key=set_key,
                now_ms=self._container.clock.now_ms(),
            )
        await self._audit(
            principal,
            "provider_instance_updated",
            cast(str, resolved.id),
            {"name": name, "provider": column},
        )

    async def delete(self, principal: Principal, provider: str, body: Mapping[str, object]) -> None:
        """Usuwa instancje razem z ich modelami — wszystko albo nic (K13 §4 p. 3)."""
        require_superuser(principal)
        column = resolve_provider(provider)
        targets = await self._delete_targets(provider, body)
        async with transaction(self._sm()) as session:
            model_ids = await self._unblocked_model_ids(session, [iid for iid, _ in targets])
            await models_repo.delete_by_ids(session, model_ids)
            await instances_repo.delete_by_ids(session, [iid for iid, _ in targets])
        for instance_id, name in targets:
            await self._audit(
                principal,
                "provider_instance_deleted",
                instance_id,
                {"name": name, "provider": column},
            )

    async def verify(self, principal: Principal, provider: str, body: Mapping[str, object]) -> None:
        """Sonda połączenia ``GET {base_url}/models`` (K13 §4 p. 4); niczego nie zapisuje."""
        require_superuser(principal)
        resolve_provider(provider)
        base_url = body.get("base_url")
        api_key = body.get("api_key")
        instance_ref = body.get("instance_id")
        if isinstance(instance_ref, str) and instance_ref:
            resolved = await self.resolve_instance(provider, instance_ref)
            if not isinstance(base_url, str) or not base_url:
                base_url = resolved.base_url
            if api_key is None or api_key == API_KEY_MASK:
                api_key = resolved.api_key
        if not isinstance(base_url, str) or not base_url:
            raise ValidationFailed(BASE_URL_REQUIRED)
        key = api_key if isinstance(api_key, str) and api_key else None
        await provider_probe.probe_models(normalize_base_url(base_url), key)

    # --- pomocnicze -----------------------------------------------------------------

    def _sm(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera (istnieje po ``start()``)."""
        return cast(async_sessionmaker[AsyncSession], self._container.sessionmaker)

    def _required_name(self, body: Mapping[str, object]) -> str:
        """``instance_name`` niepuste (K13 §4 p. 1) albo 101."""
        raw = body.get("instance_name")
        if not isinstance(raw, str) or not raw:
            raise ValidationFailed(INSTANCE_REQUIRED)
        return raw

    def _required_base_url(self, body: Mapping[str, object]) -> str:
        """``base_url`` obecne i poprawne (K13 §2, §4 p. 1) albo 101."""
        raw = body.get("base_url")
        if not isinstance(raw, str) or not raw:
            raise ValidationFailed(BASE_URL_REQUIRED)
        return normalize_base_url(raw)

    def _required_fields(self, body: Mapping[str, object]) -> tuple[str, str]:
        """Pola wymagane PUT (K13 §4 p. 2) albo 101 ``Missing required fields: …``."""
        missing: list[str] = []
        raw_name = body.get("instance_name")
        if not isinstance(raw_name, str) or not raw_name:
            missing.append("instance_name")
        raw_base_url = body.get("base_url")
        if not isinstance(raw_base_url, str) or not raw_base_url:
            missing.append("base_url")
        if missing:
            raise ValidationFailed(f"Missing required fields: {', '.join(missing)}")
        return cast(str, raw_name), cast(str, raw_base_url)

    def _update_key(
        self, body: Mapping[str, object], instance_id: str
    ) -> tuple[bool, bytes | None]:
        """Klucz przy PUT (K13 §4 p. 2): brak/maska → bez zmian, ``""`` → usunięty, inny → nowy."""
        if "api_key" not in body:
            return False, None
        value = body["api_key"]
        if value == API_KEY_MASK:
            return False, None
        if value is None or value == "":
            return True, None
        if not isinstance(value, str):
            raise ValidationFailed("api_key must be a string")
        return True, encrypt_key(self._container.settings, instance_id, value)

    async def _exists(self, column: str, name: str) -> bool:
        """Czy istnieje wiersz o nazwie (kolacja ``ai_ci`` — bez rozróżniania wielkości liter)."""
        async with transaction(self._sm()) as session:
            return await instances_repo.get_by_name(session, column, name) is not None

    async def _taken(self, column: str, name: str, current_id: str) -> bool:
        """Czy nazwa należy do INNEGO wiersza (zmiana nazwy na własną jest dozwolona)."""
        async with transaction(self._sm()) as session:
            row = await instances_repo.get_by_name(session, column, name)
        return row is not None and row.id != current_id

    async def _delete_targets(self, provider: str, body: Mapping[str, object]) -> _InstanceTargets:
        """Id i nazwy instancji do usunięcia (K13 §4 p. 3); ``default`` → 102."""
        raw = body.get("instances")
        if not isinstance(raw, list) or not raw:
            raise ValidationFailed(INSTANCES_REQUIRED)
        for item in raw:
            if not isinstance(item, str) or not item:
                raise ValidationFailed(INSTANCES_REQUIRED)
            if is_default_name(item):
                raise Conflict(DEFAULT_MANAGED)
        targets: _InstanceTargets = []
        for item in dedupe(cast("list[str]", raw)):
            resolved = await self.resolve_instance(provider, item)
            targets.append((cast(str, resolved.id), resolved.name))
        return targets

    async def _unblocked_model_ids(self, session: AsyncSession, instance_ids: _Ids) -> _Ids:
        """Id modeli instancji po sprawdzeniu blokad K13 §4 p. 8; blokada → 102 i brak zmian."""
        model_ids: _Ids = []
        for instance_id in instance_ids:
            for row in await models_repo.list_by_instance(session, instance_id):
                if row.is_default:
                    raise Conflict(
                        f"Model '{row.name}' is a default model; set another default model first"
                        " (PUT /api/v1/system/models/default or Settings → Models) and retry"
                    )
                if row.model_type == "embedding":
                    count = await models_repo.count_datasets_using(session, row)
                    if count > 0:
                        raise Conflict(f"Model '{row.name}' is used by {count} dataset(s)")
                model_ids.append(row.id)
        return model_ids

    async def _audit(
        self,
        principal: Principal,
        action: str,
        target_id: str,
        details: Mapping[str, object],
    ) -> None:
        """Wpis audytu mutacji (``target_type="provider_instance"``); ``details`` bez klucza."""
        audit = self._container.audit
        if audit is None:
            raise RuntimeError("container not started")
        await audit.record(
            actor_label=principal.email,
            action=action,
            target_type="provider_instance",
            target_id=target_id,
            details=details,
            actor_id=principal.user_id,
        )
