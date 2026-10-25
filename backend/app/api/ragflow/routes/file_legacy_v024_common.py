"""Wspólne sprawdzenia tras legacy v0.24 (CONTRACT E4-5b §D2).

``first_unusable`` obsługuje ``mv`` i ``convert`` (T3): wskazuje pierwszy identyfikator
z ciała, którego nie da się użyć — nieistniejący albo cudzy (DEC-201: odmowa jak „nie
znaleziono"). Identyfikatory sprawdzane są w kolejności z żądania, każdy w osobnej sesji.

Uwaga o kontrakcie ``api-no-db`` (pyproject, „API nie dotyka bazy bezpośrednio"): ``app.api``
nie może importować ``app.db``, więc zamiast ``app.db.uow.transaction`` korzystamy z fabryki
sesji udostępnionej przez usługę (``FilesService.sessionmaker`` — alias z ``services/files.py``
na użytek E4-5b, CONTRACT §D3). Sprawdzenia są tylko odczytem, więc brak jawnej transakcji
nie zmienia wyniku.
"""

from collections.abc import Sequence

from app.core.errors import PermissionDenied
from app.domain.policy import Principal
from app.services.files import FilesService


async def first_unusable(svc: FilesService, principal: Principal, ids: Sequence[str]) -> str | None:
    """Pierwsze id nieistniejące albo cudze; ``None``, gdy wszystkie użyteczne (§D2)."""
    sessionmaker = svc.sessionmaker()
    for file_id in ids:
        async with sessionmaker() as session:
            row = await svc.visible(session, file_id)
        if row is None:
            return file_id
        try:
            svc.owned(principal, row)
        except PermissionDenied:
            return file_id
    return None
