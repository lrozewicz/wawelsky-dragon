"""Runner scenariuszy MCP dla contract-recordera (WP E6-0, kontrakt T3a).

Wykonuje kroki MCP (klient = oficjalny pakiet ``mcp`` z PyPI) przeciwko serwerowi MCP
upstream v0.27.2 (tryb ``host``; klient podaje klucz API w naglowku) i zapisuje golden
files do ``<out_root>/v0.27.2/mcp/<scenariusz>--<nr>-<id>.json``. Krok ``op: http`` jest
pomocniczy (tworzenie datasetu itd.) i reuzywa ``runner._run_step``/``_capture``; nie
zapisuje zlota.

Transporty (nazwy endpointow z ``mcp/server/server.py``): ``streamable_http`` -> ``/mcp``,
``sse`` -> ``/sse``. W trybie ``host`` serwer wymaga naglowka z kluczem na kazdym z tych
sciezek (``AuthMiddleware``), dlatego brak/zly klucz konczy sie bledem HTTP zapisanym jako
``outcome: error`` (jesli krok ma ``expect_error: true``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import runner
import yaml
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from normalize import IdRegistry, normalize_json
from runner import (
    _capture,
    _dig,
    _run_step,
    _snapshot_value,
    _substitute,
    auth_headers,
    kind_of,
)

if TYPE_CHECKING:
    from rf_bootstrap import RagflowSession

GOLDEN_VERSION = "v0.27.2"
GOLDEN_DIR = "mcp"
TRANSPORTS = ("streamable_http", "sse")
OPS = ("initialize", "list_tools", "call_tool", "http")
AUTH_MODES = ("key", "api_key_header", "x_api_key", "none", "bad")
_ENDPOINTS = {"streamable_http": "/mcp", "sse": "/sse"}
# Jawny hojny timeout klienta MCP (T7): domyślny read timeout httpx to 5 s, a retrieval pod
# obciążeniem (xdist -n 8) trwa dłużej — flak ``sha_retrieval_dataset_ids`` (ReadTimeout).
MCP_REQUEST_TIMEOUT_S = 60.0
HEADER_PLACEHOLDER = "<HEADER>"


def load_mcp_scenario(path: Path) -> dict:
    """Wczytuje i waliduje scenariusz MCP (name == nazwa pliku, unikalne id, op/transport/auth)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path.name}: scenariusz nie jest mapowaniem YAML")
    if data.get("name") != path.stem:
        raise ValueError(f"{path.name}: 'name' ({data.get('name')}) != nazwa pliku")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError(f"{path.name}: brak niepustej listy 'steps'")
    seen: set[str] = set()
    for step in steps:
        step_id = step.get("id") if isinstance(step, dict) else None
        if not step_id or step_id in seen:
            raise ValueError(
                f"{path.name}: brakujące lub zduplikowane id kroku: {step_id!r}"
            )
        seen.add(step_id)
        op = step.get("op")
        if op not in OPS:
            raise ValueError(f"{path.name}/{step_id}: zły 'op' {op!r}")
        if step.get("auth", "key") not in AUTH_MODES:
            raise ValueError(
                f"{path.name}/{step_id}: zły tryb auth {step.get('auth')!r}"
            )
        if op == "http":
            if str(step.get("method", "")).upper() not in runner.METHODS:
                raise ValueError(
                    f"{path.name}/{step_id}: zła metoda {step.get('method')!r}"
                )
            if not isinstance(step.get("path"), str):
                raise TypeError(f"{path.name}/{step_id}: brak 'path'")
            continue
        transport = step.get("transport")
        if transport not in TRANSPORTS:
            raise ValueError(f"{path.name}/{step_id}: zły 'transport' {transport!r}")
        if op == "call_tool" and not isinstance(step.get("tool"), str):
            raise TypeError(f"{path.name}/{step_id}: brak 'tool' dla call_tool")
    return data


def mcp_golden_path(
    out_root: Path, scenario_name: str, number: int, step_id: str
) -> Path:
    """Sciezka golden file kroku MCP: ``<out_root>/v0.27.2/mcp/<scenariusz>--<nr>-<id>.json``."""
    return (
        out_root
        / GOLDEN_VERSION
        / GOLDEN_DIR
        / f"{scenario_name}--{number:02d}-{step_id}.json"
    )


def _expand_json_text(value: Any) -> Any:
    """Zamienia ``text`` (TextContent) bedacy JSON-em na sparsowana strukture.

    Serwer MCP zwraca wyniki ``ragflow_*`` jako JSON w stringu ``TextContent.text``;
    bez tego kroku normalizacja nie zajrzalaby do srodka. Tekst nie-JSON zostaje bez zmian.
    """
    if isinstance(value, dict):
        expanded: dict[str, Any] = {}
        for key, item in value.items():
            if key == "text" and isinstance(item, str):
                expanded[key] = _maybe_json(item)
            else:
                expanded[key] = _expand_json_text(item)
        return expanded
    if isinstance(value, list):
        return [_expand_json_text(item) for item in value]
    return value


def _maybe_json(value: str) -> Any:
    """JSON z stringa, jesli to obiekt/tablica; inaczej oryginalny string."""
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return value
    try:
        return json.loads(value)
    except ValueError:
        return value


def _redact_headers(obj: Any) -> Any:
    """Maskuje wartosci w ``capabilities.experimental.headers`` (upstream ``handle_sse``).

    Klucze zostaja (kolejnosc i zestaw to fakt dla K17), kazda wartosc -> ``<HEADER>``;
    brak tej sciezki nie zmienia niczego. Drzewo przechodzone rekurencyjnie.
    """
    if isinstance(obj, dict):
        redacted = {key: _redact_headers(value) for key, value in obj.items()}
        capabilities = redacted.get("capabilities")
        if isinstance(capabilities, dict):
            experimental = capabilities.get("experimental")
            if isinstance(experimental, dict):
                headers = experimental.get("headers")
                if isinstance(headers, dict):
                    experimental["headers"] = dict.fromkeys(headers, HEADER_PLACEHOLDER)
        return redacted
    if isinstance(obj, list):
        return [_redact_headers(item) for item in obj]
    return obj


def normalize_mcp_result(obj: Any, ids: IdRegistry) -> Any:
    """Normalizuje wynik klienta MCP do postaci golden (czyste, bez sieci).

    Teksty ``TextContent.text`` bedace JSON-em sa rozwijane i normalizowane rekurencyjnie;
    reszta idzie przez ``normalize.normalize_json`` (id 32-hex, znaczniki czasu, tokeny).
    Naglowki zadania wkładane przez upstream do ``capabilities.experimental.headers``
    sa maskowane (``_redact_headers``) — zloto nie moze zawierac klucza API.
    """
    return normalize_json(_redact_headers(_expand_json_text(obj)), ids)


def _auth_headers(session: RagflowSession, mode: str) -> dict[str, str]:
    """Naglowki MCP dla trybu ``auth`` kroku (kontrakt T3a).

    Serwer czyta naglowek ``_extract_token_from_headers``: ``Authorization: Bearer``
    albo ``api_key``/``x-api-key``/``X-API-Key``.
    """
    if mode == "key":
        return {"Authorization": f"Bearer {session.api_key}"}
    if mode == "api_key_header":
        return {"api_key": session.api_key}
    if mode == "x_api_key":
        return {"X-API-Key": session.api_key}
    if mode == "none":
        return {}
    if mode == "bad":
        return {"Authorization": f"Bearer {runner.BAD_KEY}"}
    raise ValueError(f"nieznany tryb auth MCP: {mode!r}")


@contextlib.asynccontextmanager
async def _transport(transport: str, url: str, headers: dict[str, str]):
    """Otwiera transport MCP (streamable-http albo SSE) i zwraca strumienie sesji."""
    if transport == "streamable_http":
        async with (
            httpx.AsyncClient(
                headers=headers, timeout=httpx.Timeout(MCP_REQUEST_TIMEOUT_S)
            ) as client,
            streamable_http_client(url, http_client=client) as streams,
        ):
            yield streams
    else:
        async with sse_client(
            url, headers=headers, timeout=MCP_REQUEST_TIMEOUT_S
        ) as streams:
            yield streams


async def _execute_mcp(
    step: dict, headers: dict[str, str], mcp_base_url: str, arguments: Any
) -> Any:
    """Laczy sie z serwerem MCP, robi ``initialize`` i wykonuje ``op`` kroku.

    ``initialize`` jest wymagane przez protokol przed ``list_tools``/``call_tool``;
    dla op ``initialize`` zwracamy wlasnie jego wynik.
    """
    url = mcp_base_url.rstrip("/") + _ENDPOINTS[step["transport"]]
    async with _transport(step["transport"], url, headers) as streams:
        read_stream, write_stream = streams[0], streams[1]
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await session.initialize()
            if step["op"] == "initialize":
                return initialized
            if step["op"] == "list_tools":
                return await session.list_tools()
            return await session.call_tool(step["tool"], arguments)


def _unwrap_single(exc: BaseException) -> BaseException:
    """Rozwija grupe anyio z jednym wyjatkiem do tego wyjatku (np. 401 z HTTPStatusError).

    ``streamable_http_client``/``sse_client`` uzywaja ``anyio.create_task_group``, ktory
    opakowuje pojedynczy blad w ``ExceptionGroup``; bez rozwiazania ``error_type`` bylby
    bezuzyteczny, a ``http_status`` zgubiony.
    """
    # hasattr zamiast isinstance: ruff bez target-version nie zna wbudowanego
    # BaseExceptionGroup (3.11+), a record.py dziala na Pythonie >= 3.13.
    while hasattr(exc, "exceptions") and len(exc.exceptions) == 1:
        exc = exc.exceptions[0]
    return exc


def _error_payload(exc: Exception) -> dict[str, Any]:
    """Wynik bledu klienta MCP: ``error_type``/``message``/``http_status`` (kontrakt T3a)."""
    inner = _unwrap_single(exc)
    if isinstance(inner, httpx.HTTPStatusError):
        status: int | None = inner.response.status_code
    else:
        status = getattr(inner, "status_code", None)
    return {
        "error_type": type(inner).__name__,
        "message": str(inner),
        "http_status": status,
    }


def _run_http_step(
    client: httpx.Client,
    step: dict,
    variables: dict[str, Any],
    fixture_root: Path,
    session: RagflowSession,
    ids: IdRegistry,
) -> None:
    """Krok pomocniczy HTTP (op: http) — reuzywa runner._run_step/_capture; bez zlota."""
    headers = auth_headers(session, step.get("auth", "key"))
    response = _run_step(client, step, variables, fixture_root, headers)
    parsed = runner._parse_body(response)
    if step.get("expect") is None:
        if response.status_code >= 400:
            raise RuntimeError(
                f"krok {step['id']}: HTTP {response.status_code}: {response.text[:300]}"
            )
        if isinstance(parsed, dict) and parsed.get("code") not in (None, 0):
            raise RuntimeError(
                f"krok {step['id']}: code={parsed.get('code')}: "
                f"{str(parsed.get('message'))[:300]}"
            )
    else:
        runner.check_expect(step, response.status_code, parsed)
    for variable, dotted in (step.get("capture") or {}).items():
        raw = _capture(parsed, dotted)
        if not isinstance(raw, str):
            raise TypeError(f"krok {step['id']}: capture {variable} nie jest stringiem")
        variables[variable] = raw
        ids.token(kind_of(variable), raw)


def _run_mcp_step(
    step: dict, variables: dict[str, Any], session: RagflowSession, mcp_base_url: str
) -> tuple[str, dict, dict | None]:
    """Wykonuje krok MCP; zwraca ``(outcome, result, raw)`` (raw = wynik do capture)."""
    headers = _auth_headers(session, step.get("auth", "key"))
    raw_arguments = step.get("arguments")
    arguments = (
        _substitute(raw_arguments, variables) if raw_arguments is not None else None
    )
    expect_error = bool(step.get("expect_error"))
    try:
        outcome = asyncio.run(_execute_mcp(step, headers, mcp_base_url, arguments))
    # celowo szeroko: kontrakt T3a — blad klienta/HTTP jest wynikiem kroku, nie krachem
    except Exception as exc:
        if not expect_error:
            raise
        return "error", _error_payload(exc), None
    dumped = outcome.model_dump(mode="json", by_alias=True, exclude_none=True)
    if step["op"] == "call_tool" and dumped.get("isError") and not expect_error:
        raise RuntimeError(f"krok {step['id']}: CallToolResult.isError=true")
    return "ok", dumped, dumped


def run_mcp_scenario(
    session: RagflowSession,
    scenario: dict,
    out_root: Path,
    mcp_base_url: str,
) -> int:
    """Wykonuje scenariusz MCP; zwraca liczbe zapisanych plikow golden.

    Wyjatek przy bledzie kroku (scenariusz FAIL). Kroki ``op: http`` sa pomocnicze i nie
    zapisuja zlota. ``record: false`` na kroku MCP pomija zapis, ale wykonuje krok i capture.
    """
    ids = IdRegistry()
    variables: dict[str, Any] = {}
    name = scenario["name"]
    fixture_root = Path(__file__).resolve().parent
    saved = 0
    with httpx.Client(
        base_url=session.base_url, timeout=runner._REQUEST_TIMEOUT_S
    ) as client:
        for number, step in enumerate(scenario["steps"], start=1):
            if step["op"] == "http":
                _run_http_step(client, step, variables, fixture_root, session, ids)
                continue
            outcome, result, raw = _run_mcp_step(step, variables, session, mcp_base_url)
            if raw is not None:
                for variable, dotted in (step.get("capture") or {}).items():
                    value = _dig(raw, dotted)
                    if not isinstance(value, str):
                        raise TypeError(
                            f"krok {step['id']}: capture {variable} nie jest stringiem"
                        )
                    variables[variable] = value
                    ids.token(kind_of(variable), value)
            if not step.get("record", True):
                continue
            raw_arguments = step.get("arguments")
            payload = {
                "request": {
                    "transport": step["transport"],
                    "op": step["op"],
                    "tool": step.get("tool"),
                    "arguments": (
                        _snapshot_value(raw_arguments, variables, ids)
                        if raw_arguments is not None
                        else None
                    ),
                    "auth": step.get("auth", "key"),
                },
                "outcome": outcome,
                "result": normalize_mcp_result(result, ids),
            }
            target = mcp_golden_path(out_root, name, number, step["id"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            saved += 1
    return saved
