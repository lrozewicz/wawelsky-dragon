"""Testy live bramki LLM i sędziego (marker ``live``) — uruchamiane przez ``tools/dev/live.sh``.

Bramka z ``WD_LLM_BASE_URL`` musi udostępniać modele wpisane w ``wdeval/data/models.live.json``
(czat i embedding) oraz odpowiadać na czat. Sędzia NIE idzie przez bramkę: ma osobny endpoint
``WD_JUDGE_*`` (OpenRouter, DECISIONS Q2), więc jego modelu nie ma wśród modeli bramki.
Komunikaty asercji zawierają tylko nazwy modeli, wymiar i nazwę dostawcy — nigdy adresu bramki
ani klucza.
"""

import os
from collections.abc import Iterator

import openai
import pytest
from openai.types.chat import ChatCompletionUserMessageParam

pytestmark = pytest.mark.live

CHAT_MODEL = "openai/gpt-4.1-mini"
EMBEDDING_MODEL = "openai/text-embedding-3-large"
EMBEDDING_DIM = 3072  # wymiar z wdeval/data/models.live.json
REQUIRED_MODELS = (CHAT_MODEL, EMBEDDING_MODEL)
CHAT_MODELS = (CHAT_MODEL,)
# Zmienne osobnego endpointu sędziego (wdeval/judge_env.py, kontrakt C1).
JUDGE_ENV_REQUIRED = ("WD_JUDGE_BASE_URL", "WD_JUDGE_API_KEY", "WD_JUDGE_MODEL")
PROMPT: list[ChatCompletionUserMessageParam] = [
    {"role": "user", "content": "Odpowiedz jednym słowem: tak."}
]


@pytest.fixture
def client() -> Iterator[openai.OpenAI]:
    """Klient synchroniczny SDK ``openai`` na bramkę z env (bez wypisywania wartości)."""
    base_url = os.environ.get("WD_LLM_BASE_URL")
    api_key = os.environ.get("WD_LLM_API_KEY")
    if not base_url or not api_key:
        pytest.fail("brak WD_LLM_BASE_URL albo WD_LLM_API_KEY (uruchom przez tools/dev/live.sh)")
    with openai.OpenAI(base_url=base_url, api_key=api_key) as gateway:
        yield gateway


@pytest.fixture
def judge_client() -> Iterator[openai.OpenAI]:
    """Klient synchroniczny SDK ``openai`` na osobny endpoint sędziego ``WD_JUDGE_*``.

    Komunikat błędu wymienia tylko NAZWY brakujących zmiennych — nigdy ich wartości.
    """
    missing = [name for name in JUDGE_ENV_REQUIRED if not os.environ.get(name)]
    if missing:
        pytest.fail(
            "brak zmiennych sędziego: " + ", ".join(missing) + " (uruchom przez tools/dev/live.sh)"
        )
    with openai.OpenAI(
        base_url=os.environ["WD_JUDGE_BASE_URL"], api_key=os.environ["WD_JUDGE_API_KEY"]
    ) as judge:
        yield judge


def judge_extra_body() -> dict[str, object]:
    """``extra_body`` żądania do sędziego: rozumowanie + przypięcie dostawcy (kontrakt C1).

    Gdy ``WD_JUDGE_PROVIDER`` niepuste, ``provider.order`` wskazuje dostawcę, a
    ``allow_fallbacks=False`` zabrania cichego zejścia na innego (ten sam model u innego
    dostawcy odpowiada inaczej).
    """
    body: dict[str, object] = {"reasoning": {"effort": "medium"}}
    provider = os.environ.get("WD_JUDGE_PROVIDER", "")
    if provider:
        body["provider"] = {"order": [provider], "allow_fallbacks": False}
    return body


def test_gateway_udostepnia_modele(client: openai.OpenAI) -> None:
    """Bramka wystawia modele z models.live.json: czat i embedding."""
    available = {model.id for model in client.models.list()}
    missing = [name for name in REQUIRED_MODELS if name not in available]
    assert not missing, (
        "bramka nie udostępnia modeli: "
        + ", ".join(missing)
        + "; dostępne: "
        + ", ".join(sorted(available))
    )


@pytest.mark.parametrize("model", CHAT_MODELS)
def test_gateway_czat_zwraca_niepusta_odpowiedz(client: openai.OpenAI, model: str) -> None:
    """Czat modelem z models.live.json zwraca niepustą treść."""
    response = client.chat.completions.create(
        model=model, messages=PROMPT, max_completion_tokens=1024
    )
    content = (response.choices[0].message.content or "").strip()
    assert content != "", f"model {model}: pusta odpowiedź czatu"


def test_gateway_embedding_ma_wymiar_z_konfiguracji(client: openai.OpenAI) -> None:
    """Embedding zwraca wektor o wymiarze wpisanym w models.live.json."""
    response = client.embeddings.create(model=EMBEDDING_MODEL, input="Zdanie testowe.")
    dimension = len(response.data[0].embedding)
    assert dimension == EMBEDDING_DIM, (
        f"model {EMBEDDING_MODEL}: wymiar {dimension} != {EMBEDDING_DIM}"
    )


def test_judge_env_czat_zwraca_niepusta_odpowiedz(judge_client: openai.OpenAI) -> None:
    """Sędzia na ``WD_JUDGE_*`` odpowiada niepustą treścią i trzyma dostawcę z ``provider.order``.

    ``max_completion_tokens=2048`` (nie 1024): GLM z rozumowaniem zużywa zapas na „myślenie”
    i przy mniejszym limicie odpowiedź bywa ucięta."""
    response = judge_client.chat.completions.create(
        model=os.environ["WD_JUDGE_MODEL"],
        messages=PROMPT,
        max_completion_tokens=2048,
        temperature=0,
        extra_body=judge_extra_body(),
    )
    content = (response.choices[0].message.content or "").strip()
    assert content != "", "sędzia z WD_JUDGE_MODEL: pusta odpowiedź czatu"
    extras = response.model_extra or {}
    if "provider" in extras:  # OpenRouter dokłada pole dostawcy; inne endpointy mogą nie
        provider = extras["provider"]
        assert any(marker in str(provider).lower() for marker in ("z.ai", "z-ai", "zai")), (
            f"sędzia nie odpowiedział przez z.ai, tylko: {provider}"
        )
