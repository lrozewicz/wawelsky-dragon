"""Testy wdeval.judge_env — sędzia na osobnym endpoincie ``WD_JUDGE_*`` (C1/C2/C5).

Wszystko na atrapach: bez sieci, bez bazy, bez importu ``openai`` na poziomie modułu.
Atrapa klienta to klasa z ``chat.completions.create`` (async) zapisującą kwargs —
żaden test nie woła prawdziwego endpointu.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

import wdeval.run as run_module
from wdeval.evaluate import RunResult
from wdeval.judge import JudgeRunner
from wdeval.judge_env import (
    JUDGE_ENV_REQUIRED,
    JudgeConfigError,
    JudgeEndpoint,
    judge_endpoint_from_env,
    judge_env_extra_body,
    make_env_chat,
)
from wdeval.llm_models import LiveModels
from wdeval.manifest import validate_manifest

# Sztuczne wartości z briefu: muszą wystarczyć do wykrycia wycieku w manifeście/repr.
FAKE_URL = "https://example.invalid/v1"
FAKE_KEY = "sk-test-123"
FAKE_MODEL = "z-ai/glm-5.3-flash"
FAKE_PROVIDER = "z-ai/fp8"

FULL_ENV: dict[str, str] = {
    "WD_JUDGE_BASE_URL": FAKE_URL,
    "WD_JUDGE_API_KEY": FAKE_KEY,
    "WD_JUDGE_MODEL": FAKE_MODEL,
    "WD_JUDGE_PROVIDER": FAKE_PROVIDER,
}

_PAYLOAD = {
    "question": "Jaka jest stolica Polski?",
    "context": "[Źródło 1] Warszawa jest stolicą Polski.",
    "answer": "Warszawa [1].",
}


class _FakeCompletions:
    """Atrapa ``client.chat.completions``: zapisuje kwargs i zwraca zadaną treść."""

    def __init__(self, content: str | None = "TAK") -> None:
        self.content = content
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeClient:
    """Atrapa ``openai.AsyncOpenAI`` — bez sieci i bez prawdziwego klucza."""

    def __init__(self, content: str | None = "TAK") -> None:
        self.completions = _FakeCompletions(content)
        self.chat = SimpleNamespace(completions=self.completions)

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.completions.calls


def _endpoint(provider: str | None = FAKE_PROVIDER) -> JudgeEndpoint:
    return JudgeEndpoint(
        base_url=FAKE_URL,
        api_key=FAKE_KEY,
        model=FAKE_MODEL,
        provider=provider,
    )


# --- judge_endpoint_from_env ---------------------------------------------------


def test_pelna_konfiguracja_daje_endpoint() -> None:
    endpoint = judge_endpoint_from_env(FULL_ENV)
    assert endpoint == JudgeEndpoint(
        base_url=FAKE_URL, api_key=FAKE_KEY, model=FAKE_MODEL, provider=FAKE_PROVIDER
    )


def test_provider_pusty_lub_brak_daje_none() -> None:
    bez_providera = {name: FULL_ENV[name] for name in JUDGE_ENV_REQUIRED}
    assert judge_endpoint_from_env(bez_providera).provider is None
    assert judge_endpoint_from_env(dict(bez_providera, WD_JUDGE_PROVIDER="")).provider is None


def test_pusty_env_daje_none() -> None:
    assert judge_endpoint_from_env({}) is None


def test_puste_wartosci_sa_nieustawione() -> None:
    """Pusty string == nieustawiona: same puste pola nie konfigurują sędziego."""
    puste = {name: "" for name in JUDGE_ENV_REQUIRED}
    assert judge_endpoint_from_env(puste) is None


def test_czesciowa_konfiguracja_rzuca_z_nazwami_brakujacych() -> None:
    with pytest.raises(JudgeConfigError) as excinfo:
        judge_endpoint_from_env({"WD_JUDGE_BASE_URL": "x"})

    message = str(excinfo.value)
    assert "WD_JUDGE_API_KEY" in message
    assert "WD_JUDGE_MODEL" in message
    assert "x" not in message


def test_komunikat_czesciowej_konfiguracji_nie_wycieka_wartosciami() -> None:
    """Ustawione wartości (URL, klucz) nie mogą trafić do komunikatu błędu."""
    with pytest.raises(JudgeConfigError) as excinfo:
        judge_endpoint_from_env({"WD_JUDGE_BASE_URL": FAKE_URL, "WD_JUDGE_API_KEY": FAKE_KEY})

    message = str(excinfo.value)
    assert FAKE_URL not in message
    assert FAKE_KEY not in message
    assert FAKE_MODEL not in message
    assert "WD_JUDGE_MODEL" in message
    assert "WD_JUDGE_BASE_URL" not in message
    assert "WD_JUDGE_API_KEY" not in message


def test_czesciowa_konfiguracja_z_kluczem_i_modelem() -> None:
    """Każdy brakujący zestaw nazw trafia do komunikatu (tu brak URL-a)."""
    with pytest.raises(JudgeConfigError, match="WD_JUDGE_BASE_URL"):
        judge_endpoint_from_env({"WD_JUDGE_API_KEY": "k", "WD_JUDGE_MODEL": "m"})


def test_repr_endpointu_bez_klucza_i_url() -> None:
    text = repr(_endpoint())
    assert FAKE_KEY not in text
    assert FAKE_URL not in text
    assert FAKE_MODEL in text  # model jest bezpieczny (i tak trafia do manifestu)


# --- judge_env_extra_body ------------------------------------------------------


def test_extra_body_z_providerem() -> None:
    assert judge_env_extra_body("medium", FAKE_PROVIDER) == {
        "reasoning": {"effort": "medium"},
        "provider": {"order": [FAKE_PROVIDER], "allow_fallbacks": False},
    }


def test_extra_body_bez_providera() -> None:
    assert judge_env_extra_body("low", None) == {"reasoning": {"effort": "low"}}


# --- make_env_chat -------------------------------------------------------------


async def test_make_env_chat_wysyla_model_endpointu_i_extra_body() -> None:
    client = _FakeClient()
    chat = make_env_chat(_endpoint(), "medium", client=client)

    raw = await chat(
        "glm-5.3-flash",
        [{"role": "user", "content": "Ile?"}],
        temperature=0,
        extra_body={"chat_template_kwargs": {"enable_thinking": True}},
    )

    assert raw == "TAK"
    (request,) = client.calls
    assert request["model"] == FAKE_MODEL
    assert request["messages"] == [{"role": "user", "content": "Ile?"}]
    assert request["temperature"] == 0
    assert request["extra_body"]["reasoning"] == {"effort": "medium"}
    assert request["extra_body"]["provider"] == {
        "order": [FAKE_PROVIDER],
        "allow_fallbacks": False,
    }
    # extra_body z JudgeRunner (pola bramki: vLLM/z.ai) jest ignorowany
    assert "chat_template_kwargs" not in request["extra_body"]


async def test_make_env_chat_bez_providera_nie_wysyla_klucza_provider() -> None:
    client = _FakeClient()
    chat = make_env_chat(_endpoint(provider=None), "medium", client=client)

    await chat("glm-5.3-flash", [], temperature=0, extra_body=None)

    assert "provider" not in client.calls[0]["extra_body"]


async def test_make_env_chat_pomija_temperature_gdy_none() -> None:
    client = _FakeClient()
    chat = make_env_chat(_endpoint(), "medium", client=client)

    await chat("glm-5.3-flash", [], temperature=None, extra_body=None)

    assert "temperature" not in client.calls[0]


async def test_make_env_chat_pusta_tresc_daje_pusty_string() -> None:
    client = _FakeClient(content=None)
    chat = make_env_chat(_endpoint(), "medium", client=client)

    assert await chat("glm-5.3-flash", [], temperature=0, extra_body=None) == ""


async def test_runner_wola_endpoint_ale_podaje_nazwe_modelu_do_klucza() -> None:
    """C1: ``model_name`` (nazwa w cache/manifeście) != ``endpoint.model`` (na drucie)."""
    client = _FakeClient("TAK")
    runner = JudgeRunner(
        model_name="glm-5.3-flash",
        chat=make_env_chat(_endpoint(), "medium", client=client),
        mode="medium",
    )

    verdict = await runner("grounded", _PAYLOAD)

    assert verdict.value is True
    assert client.calls[0]["model"] == FAKE_MODEL
    assert client.calls[0]["temperature"] == 0


# --- manifest: endpoint bez wycieku -------------------------------------------


def _live_models() -> LiveModels:
    return LiveModels(
        chat="glm-5.3-flash",
        embedding="openai/text-embedding-3-large",
        dimension=3072,
        image2text="",
        judge="glm-5.3-flash",
        judge_mode="medium",
    )


def _plan_stub() -> SimpleNamespace:
    return SimpleNamespace(
        run_id="20260929T000000Z-dev-live",
        profile=SimpleNamespace(name="dev"),
        llm="live",
        k_list=[1],
        models=_live_models(),
        beta_corpus=None,
        codex_corpus=None,
        items=[],
        arms=["fast"],
        docs=[],
    )


def _seeds_stub() -> dict[str, SimpleNamespace]:
    return {
        "fast": SimpleNamespace(
            spec=SimpleNamespace(dataset_name="eval-fast", layout_recognize="Plain Text"),
            documents=[],
            failed=[],
            chunk_count=0,
            parse_seconds=0.0,
        )
    }


def _manifest_dla_env(judge_endpoint: str) -> dict[str, Any]:
    return run_module._manifest(
        _plan_stub(),
        _seeds_stub(),
        RunResult(results=[], aggregates=[], comparisons=[]),
        SimpleNamespace(ocr_engine="none"),
        judge_endpoint=judge_endpoint,
    )


def test_manifest_judge_env_zapisuje_endpoint_i_nie_wycieka() -> None:
    endpoint = judge_endpoint_from_env(FULL_ENV)
    assert endpoint is not None
    manifest = _manifest_dla_env("judge_env" if endpoint else "gateway")

    assert manifest["judge_model"] == {
        "name": "glm-5.3-flash",
        "family": "zhipu-glm",
        "mode": "medium",
        "endpoint": "judge_env",
    }
    dumped = json.dumps(manifest)
    assert FAKE_KEY not in dumped
    assert FAKE_URL not in dumped
    assert FAKE_PROVIDER not in dumped
    assert validate_manifest(manifest) == []


def test_manifest_gateway_gdy_brak_env() -> None:
    endpoint = judge_endpoint_from_env({})
    manifest = _manifest_dla_env("judge_env" if endpoint else "gateway")
    assert manifest["judge_model"]["endpoint"] == "gateway"


# --- run_pipeline: env czytany tylko na ścieżce live ---------------------------


async def _pusty_stos(settings: Any) -> AsyncIterator[Any]:
    """Stos, który pada na wejściu — ścieżka env jest sprawdzana PRZED nim (C4)."""
    raise RuntimeError("stop")
    yield  # pragma: no cover — generator nigdy nie dojdzie do yield


def _spy(monkeypatch: pytest.MonkeyPatch, calls: list[Mapping[str, str]]) -> None:
    def zapisz(env: Mapping[str, str]) -> None:
        calls.append(env)

    monkeypatch.setattr(run_module, "judge_endpoint_from_env", zapisz)
    monkeypatch.setattr(run_module, "running_worker", asynccontextmanager(_pusty_stos))
    monkeypatch.setenv("WD_JUDGE_BASE_URL", FAKE_URL)
    monkeypatch.setenv("WD_JUDGE_API_KEY", FAKE_KEY)
    monkeypatch.setenv("WD_JUDGE_MODEL", FAKE_MODEL)


async def test_sciezka_fake_nie_czyta_env_sedziego(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Mapping[str, str]] = []
    _spy(monkeypatch, calls)

    with pytest.raises(RuntimeError, match="stop"):
        await run_module.run_pipeline(SimpleNamespace(llm="fake"), SimpleNamespace())

    assert calls == []


async def test_sciezka_live_czyta_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Mapping[str, str]] = []
    _spy(monkeypatch, calls)

    with pytest.raises(RuntimeError, match="stop"):
        await run_module.run_pipeline(SimpleNamespace(llm="live"), SimpleNamespace())

    assert calls == [os.environ]
