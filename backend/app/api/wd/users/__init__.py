"""Powierzchnia użytkowników WD: routery CRUD i kluczy API pod ``/api/wd/v1`` (kontrakt §1)."""

from fastapi import APIRouter

from app.api.wd.users import api_keys, crud

routers: tuple[APIRouter, ...] = (crud.router, api_keys.router)
