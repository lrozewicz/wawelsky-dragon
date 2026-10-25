"""Powierzchnia WD integracji: routery CRUD i przebiegów pod ``/api/wd/v1`` (kontrakt §1)."""

from fastapi import APIRouter

from app.api.wd.integrations import crud, runs

routers: tuple[APIRouter, ...] = (crud.router, runs.router)
