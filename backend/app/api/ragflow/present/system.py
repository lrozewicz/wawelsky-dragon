"""Prezenter aliasu ``/v1/system/*`` i ``/v1/llm/my_llms`` (refaktor E2-2z T2) — kształty v0.24.

Trasy tego aliasu istnieją wyłącznie w v0.24 i — zgodnie z K11 §10d p. 17 — wywołane w profilu
0.27 działają tak samo, więc kształty są dosłownie v0.24 niezależnie od profilu: ``profile``
jest przyjmowany i ignorowany (spójny podpis prezenterów, wzór ``present/chats.py``).

Klucze ``token_list``/``new_token`` to ten sam wiersz co ``/api/v1/system/tokens`` (C9), więc
funkcje wołają ``app/api/ragflow/system.py`` zamiast powtarzać kształt.
"""

from collections.abc import Sequence

from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.routes.models import provider_name
from app.api.ragflow.system import created_token_dict, token_dict
from app.core.config import Settings
from app.services.api_keys import ApiKeyView
from app.services.model_catalog import CatalogModel

# Wersja w /v1/system/version: złoto system--17.json (upstream get_ragflow_version).
LEGACY_VERSION = "v0.24.0"
# Sufiks fabryki dopisywany w upstreamie do llm_name (llm_app.add_llm, factory
# "OpenAI-API-Compatible") — złoto system--25.json: "fake-chat___OpenAI-API".
FACTORY_SUFFIX = "___OpenAI-API"
# Tagi fabryki z conf/llm_factories.json v0.24.0 (złoto system--25.json).
FACTORY_TAGS = "LLM,TEXT EMBEDDING,SPEECH2TEXT,MODERATION"


def legacy_config(settings: Settings, profile: CompatProfile) -> dict[str, object]:
    """Data /v1/system/config (upstream get_config) — tylko ``registerEnabled``.

    Złoto system--18.json ma jeden klucz; ``disablePasswordLogin`` to pole RESTful
    /api/v1/system/config (system--03.json), którego legacy nie zna. ``profile`` bez wpływu:
    powierzchnia v0.24 (K11 §10d p. 17).
    """
    return {"registerEnabled": int(settings.register_enabled)}


def legacy_my_llms(models: Sequence[CatalogModel], profile: CompatProfile) -> dict[str, object]:
    """Data /v1/llm/my_llms (upstream llm_app.my_llms, gałąź bez ``include_details``).

    Modele grupowane po fabryce (u WD jedna — ``models.provider``); wpis ma ``type``,
    ``name`` z sufiksem fabryki, ``used_token`` i ``status``. Liczba modeli różni się od
    złota (WD zasiewa 5 — odchyłka ``length`` w deviations/v0.24.0/system.yaml). ``profile``
    bez wpływu (K11 §10d p. 17).
    """
    grouped: dict[str, list[dict[str, object]]] = {}
    for model in models:
        grouped.setdefault(provider_name(model.provider), []).append(
            {
                "type": model.model_type,
                "name": model.name + FACTORY_SUFFIX,
                "used_token": 0,
                "status": "1",
            }
        )
    return {
        factory: {"tags": FACTORY_TAGS, "llm": entries}
        for factory, entries in sorted(grouped.items())
    }


def legacy_version(profile: CompatProfile) -> str:
    """Wersja /v1/system/version — wartość dosłownie ze złota system--17.json (v0.24.0)."""
    return LEGACY_VERSION


def legacy_token(view: ApiKeyView, profile: CompatProfile) -> dict[str, object]:
    """Wpis /v1/system/token_list — kształt C9 bez zmian (złoto system--21.json).

    Pole ``name`` dodane w K20 §1 obowiązuje wyłącznie trasy ``/api/v1/system/tokens``;
    legacy v0.24 zostaje bez niego (złoto system--21.json bez odchyłek).
    """
    return {key: value for key, value in token_dict(view).items() if key != "name"}


def legacy_created_token(view: ApiKeyView, profile: CompatProfile) -> dict[str, object]:
    """Data /v1/system/new_token — kształt C9 bez zmian (złoto system--22.json).

    Bez ``name`` (K20 §1 dotyczy tylko ``/api/v1/system/tokens``).
    """
    return {key: value for key, value in created_token_dict(view).items() if key != "name"}
