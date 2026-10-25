"""Zależności API (kontrakt C6) — jedyny moduł app.api importujący app.db."""

from typing import Annotated

from fastapi import Depends, Request

from app.db.health import check_ready


async def get_readiness(request: Request) -> str | None:
    """Przyczyna braku gotowości; None = gotowa.

    engine bierzemy z request.app.state.container (Any — kontenera nie importujemy z
    app.core.container, bo łańcuch importów złamałby kontrakt api-no-db).
    """
    engine = request.app.state.container.engine
    if engine is None:
        return "database engine not started"
    return await check_ready(engine)


ReadinessDep = Annotated[str | None, Depends(get_readiness)]
