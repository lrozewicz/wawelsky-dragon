"""Powierzchnia systemowa WD: routery statystyk i audytu pod ``/api/wd/v1`` (kontrakt §1)."""

from fastapi import APIRouter

from app.api.wd.system import audit, stats

routers: tuple[APIRouter, ...] = (stats.router, audit.router)
