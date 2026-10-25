"""Powierzchnia dostępów WD: router asystentów pod ``/api/wd/v1/access`` (kontrakt §1)."""

from fastapi import APIRouter

from app.api.wd.access import assistants

routers: tuple[APIRouter, ...] = (assistants.router,)
