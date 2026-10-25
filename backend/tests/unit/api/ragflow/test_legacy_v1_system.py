"""Testy kształtów tras legacy /v1/system/*, /v1/api/stats, /v1/llm/my_llms (E2-2a T3).

Kształty bierzemy DOSŁOWNIE z plików złota v0.24.0 (krok 16-25 scenariusza ``system``):
test czyta klucze i wartości prezentera i porównuje je z ``body`` (albo ``body.data``)
odpowiedniego pliku, tak jak ``test_present_sessions_v024.py``.
"""

import json
from pathlib import Path
from typing import Any, cast

from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.present.system import (
    legacy_config,
    legacy_created_token,
    legacy_my_llms,
    legacy_token,
    legacy_version,
)
from app.api.ragflow.refusals_v024 import PROFILES_V024
from app.api.ragflow.routes.system import stats_body
from app.core.config import Settings
from app.services.api_keys import ApiKeyView
from app.services.model_catalog import CatalogModel

GOLDEN = Path(__file__).parents[3] / "contract" / "golden" / "v0.24.0"

TIME_MS = 1730000000000
TOKEN = "ragflow-" + "a" * 43
USER_ID = "1" * 32
LACK_PERMISSION = 108
# Trasy /v1 to powierzchnia v0.24 — prezenter systemowy dostaje ten sam profil co trasa.
PROFILE: CompatProfile = "ragflow_0_24"


def _body(directory: str, name: str) -> dict[str, Any]:
    """``body`` pliku złota (koperta z ``data`` albo surowe ciało ``pong``)."""
    path = GOLDEN / directory / name
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8"))["body"])


def _view() -> ApiKeyView:
    """Widok klucza API właściciela (pola jak wiersz po ``api_keys.create``)."""
    return ApiKeyView(
        id="k" * 32,
        token=TOKEN,
        user_id=USER_ID,
        name=None,
        dialog_id=None,
        source=None,
        prefix=TOKEN[:16],
        last_used_at=None,
        expires_at=None,
        create_time=TIME_MS,
        update_time=TIME_MS,
    )


def test_config_body_has_only_register_enabled() -> None:
    """``/v1/system/config`` ma jeden klucz (złoto system--18); disablePasswordLogin to /api/v1."""
    golden = _body("v1__system__config", "system--18.json")["data"]
    body = legacy_config(Settings(env="test"), PROFILE)
    assert set(body) == set(golden)
    assert body["registerEnabled"] == 0  # WD_REGISTER_ENABLED domyślnie 0 (Settings)


def test_version_is_golden_value() -> None:
    """``/v1/system/version`` oddaje wersję dosłownie ze złota (system--17)."""
    assert _body("v1__system__version", "system--17.json")["data"] == legacy_version(PROFILE)


def test_token_dict_matches_golden_entry_keys() -> None:
    """Wpis ``/v1/system/token_list`` ma dokładnie klucze złota (system--21), bez ``name``."""
    golden = _body("v1__system__token_list", "system--21.json")["data"][0]
    body = legacy_token(_view(), PROFILE)
    assert set(body) == set(golden)
    assert "name" not in body  # K20 §1: pola name nie ma na trasach legacy v0.24
    assert body["tenant_id"] == USER_ID
    assert body["beta"] == TOKEN[-32:]


def test_created_token_dict_matches_golden_keys() -> None:
    """``/v1/system/new_token`` ma klucze złota i puste znaczniki UPDATE (system--22)."""
    golden = _body("v1__system__new_token", "system--22.json")["data"]
    body = legacy_created_token(_view(), PROFILE)
    assert set(body) == set(golden)
    assert "name" not in body  # K20 §1
    assert body["update_time"] is None
    assert body["update_date"] is None


def test_stats_body_matches_golden_keys() -> None:
    """``/v1/api/stats``: sześć pustych serii (złoto system--24)."""
    golden = _body("v1__api__stats", "system--24.json")["data"]
    body = stats_body()
    assert set(body) == set(golden)
    assert all(value == [] for value in body.values())


def test_my_llms_body_matches_golden_shape() -> None:
    """``/v1/llm/my_llms``: fabryka → {tags, llm}, wpis z sufiksem fabryki (złoto system--25)."""
    golden = _body("v1__llm__my_llms", "system--25.json")["data"]
    models = [
        CatalogModel(
            id="m" * 32,
            name="fake-chat",
            model_type="chat",
            provider="litellm",
            base_url=None,
            is_default=True,
        )
    ]
    body = legacy_my_llms(models, PROFILE)
    assert set(body) == set(golden) == {"OpenAI-API-Compatible"}
    factory = cast("dict[str, Any]", body["OpenAI-API-Compatible"])
    golden_factory = cast("dict[str, Any]", golden["OpenAI-API-Compatible"])
    assert set(factory) == set(golden_factory) == {"tags", "llm"}
    assert factory["tags"] == golden_factory["tags"]
    assert set(cast("list[dict[str, Any]]", factory["llm"])[0]) == set(
        cast("list[dict[str, Any]]", golden_factory["llm"])[0]
    )
    assert cast("list[dict[str, Any]]", factory["llm"])[0]["name"] == "fake-chat___OpenAI-API"


def test_my_llms_body_is_empty_without_models() -> None:
    """Brak modeli w rejestrze → pusta mapa (upstream ``res = {}``)."""
    assert legacy_my_llms([], PROFILE) == {}


def test_delete_refusal_profile_is_108_with_v024_message() -> None:
    """Odmowa cudzego tokenu: profil v0.24, kod 108 (C0 p. 9, brak pliku złota odmowy)."""
    profile = PROFILES_V024["v1_token_delete"]
    assert profile.code == LACK_PERMISSION
    assert profile.message == "You don't own the token."
