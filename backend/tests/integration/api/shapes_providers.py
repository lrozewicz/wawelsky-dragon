"""Przepływ testu kształtów: instancje dostawcy i modele instancji (T5; K6 §5 p. 4).

Kształty ``ProviderInstanceDetail`` i unii ``list[InstanceModel] | list[SupportedModel]``
wymagają realnych odpowiedzi tras K13 (``openapi_shapes.check``). Nazwa dostawcy w żądaniach
to nazewnictwo upstreamu (``OpenAI-API-Compatible``), jak w ``shapes_chats``; ``base_url``
instancji to środowiskowa bramka fake-llm (``WD_LLM_BASE_URL``), więc sonda ``?supported=true``
też się udaje.
"""

import os

import httpx

from tests.integration.api.openapi_shapes import check

# Ścieżki tras K13 §3 (dostawca w nazewnictwie upstreamu, CONTRACT E3-6b §T2).
PROVIDER = "OpenAI-API-Compatible"
BASE = f"/api/v1/providers/{PROVIDER}/instances"
INSTANCE = "shape-gw"
MODELS = f"{BASE}/{INSTANCE}/models"


def flow(client: httpx.Client) -> set[str]:
    """Instancja + model → walidacja dwóch komponentów; sprząta i zwraca nazwy komponentów."""
    validated: set[str] = set()
    created = client.post(BASE, json={"instance_name": INSTANCE, "base_url": _gateway_url()})
    assert created.json()["code"] == 0, created.text
    validated.add(check("provider_instance_get", client.get(f"{BASE}/{INSTANCE}")))
    added = client.post(MODELS, json={"model_name": "shape-m", "model_type": "chat"})
    assert added.json()["code"] == 0, added.text
    validated.add(check("provider_instance_models_list", client.get(MODELS)))
    # Gałąź `SupportedModel` unii: lista bramki fake-llm (ten sam komponent — K13 §3 p. 7).
    supported = client.get(f"{MODELS}?supported=true")
    if supported.json()["code"] == 0:
        validated.add(check("provider_instance_models_list", supported))
    client.request("DELETE", BASE, json={"instances": [INSTANCE]})
    return validated


def _gateway_url() -> str:
    """``base_url`` bramki fake-llm z środowiska — jak środowiskowa instancja ``default``."""
    return os.environ["WD_LLM_BASE_URL"]
