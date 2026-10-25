"""Katalog modeli i dostawców: widok rejestru ``models`` (brief SYS p. 4, złoto system--11..15).

Rekordy neutralne wobec kształtu odpowiedzi — mapowanie na nazwy pól RAGFlow robi warstwa
API (``app/api/ragflow/routes/models.py``, kontrakt ``compat-isolated``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import models as models_repo
from app.db.repositories import provider_instances as instances_repo
from app.db.uow import transaction
from app.services.provider_common import PROVIDER_COLUMN
from app.services.users import UserService

if TYPE_CHECKING:
    from app.core.container import Container


@dataclass(frozen=True)
class CatalogModel:
    """Model z rejestru; ``provider`` to kolumna ``models.provider`` (nazwa bramki WD).

    ``instance_id``/``instance_name`` opisują instancję tabeli (K13 §4 p. 9); ``None``
    oznacza model instancji domyślnej (``instance_id IS NULL``) — kształt złota bez zmian.
    """

    id: str
    name: str
    model_type: str
    provider: str
    base_url: str | None
    is_default: bool
    instance_id: str | None = None
    instance_name: str | None = None


@dataclass(frozen=True)
class ProviderGroup:
    """Dostawca wyliczony z rejestru: nazwa, pierwszy niepusty ``base_url``, liczba modeli.

    ``has_instance`` (K13 §0 p. 3): instancja tabeli albo model instancji domyślnej.
    """

    name: str
    base_url: str | None
    model_count: int
    has_instance: bool


def _catalog(row: models_repo.ModelRow, instance_names: dict[str, str]) -> CatalogModel:
    """Wiersz rejestru → rekord katalogu; nazwa instancji z mapy id → nazwa."""
    return CatalogModel(
        id=row.id,
        name=row.name,
        model_type=row.model_type,
        provider=row.provider,
        base_url=row.base_url,
        is_default=row.is_default,
        instance_id=row.instance_id,
        instance_name=instance_names.get(row.instance_id) if row.instance_id else None,
    )


def group_providers(models: list[CatalogModel]) -> list[ProviderGroup]:
    """Grupuje modele po dostawcy; kolejność po nazwie (determinizm odpowiedzi)."""
    grouped: dict[str, list[CatalogModel]] = {}
    for model in models:
        grouped.setdefault(model.provider, []).append(model)
    return [
        ProviderGroup(
            name=name,
            base_url=next((row.base_url for row in rows if row.base_url), None),
            model_count=len(rows),
            has_instance=any(row.instance_id is None for row in rows),
        )
        for name, rows in sorted(grouped.items())
    ]


def _with_litellm(groups: list[ProviderGroup], *, has_instances: bool) -> list[ProviderGroup]:
    """Dostawca ``litellm`` istnieje zawsze (K13 §0 p. 3); instancje tabeli są jego instancjami."""
    result: list[ProviderGroup] = []
    present = False
    for group in groups:
        if group.name == PROVIDER_COLUMN:
            present = True
            result.append(replace(group, has_instance=group.has_instance or has_instances))
        else:
            result.append(group)
    if not present:
        result.append(
            ProviderGroup(
                name=PROVIDER_COLUMN,
                base_url=None,
                model_count=0,
                has_instance=has_instances,
            )
        )
    return sorted(result, key=lambda group: group.name)


async def _instance_names(session: AsyncSession) -> dict[str, str]:
    """Mapa id → nazwa instancji dostawcy (poszerzenie modeli tras K13, §4 p. 9)."""
    rows = await instances_repo.list_by_provider(session, PROVIDER_COLUMN)
    return {row.id: row.name for row in rows}


class ModelCatalogService:
    """Czyta rejestr modeli i składa grupy dostawców (bez zapisu)."""

    def __init__(self, container: Container) -> None:
        self._container = container

    async def models(self) -> list[CatalogModel]:
        """Wszystkie modele rejestru w kolejności (typ, nazwa)."""
        async with transaction(self._sessionmaker()) as session:
            rows = await models_repo.list_all(session)
            names = await _instance_names(session)
        return [_catalog(row, names) for row in rows]

    async def defaults(self) -> list[CatalogModel]:
        """Modele z ``is_default = 1`` (najwyżej jeden na typ — uq_models_default_key)."""
        async with transaction(self._sessionmaker()) as session:
            rows = await models_repo.list_default(session)
            names = await _instance_names(session)
        return [_catalog(row, names) for row in rows]

    async def providers(self) -> list[ProviderGroup]:
        """Dostawcy rejestru; ``litellm`` istnieje zawsze (K13 §0 p. 3)."""
        async with transaction(self._sessionmaker()) as session:
            rows = await models_repo.list_all(session)
            instances = await instances_repo.list_by_provider(session, PROVIDER_COLUMN)
        names = {row.id: row.name for row in instances}
        groups = group_providers([_catalog(row, names) for row in rows])
        return _with_litellm(groups, has_instances=bool(instances))

    async def provider(self, name: str) -> ProviderGroup | None:
        """Dostawca po nazwie z kolumny; None gdy rejestr nie ma jego modeli."""
        for group in await self.providers():
            if group.name == name:
                return group
        return None

    async def tenant_name(self, user_id: str) -> str:
        """Nick użytkownika jako ``tenant_name`` (upstream oddaje nazwę tenanta)."""
        users = cast(UserService, self._container.users)
        return (await users.get(user_id)).nickname

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera (istnieje po ``start()``)."""
        return cast(async_sessionmaker[AsyncSession], self._container.sessionmaker)
