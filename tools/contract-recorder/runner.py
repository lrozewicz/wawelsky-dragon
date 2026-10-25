"""Runner scenariuszy YAML dla contract-recordera (SP-5, kontrakt C2).

Wykonuje kroki scenariusza przeciwko działającemu stosowi RAGFlow, podstawia
zmienne z ``capture``, normalizuje odpowiedzi (normalize.py) i zapisuje golden
files do ``<out_root>/<version>/<endpoint_dir>/<scenariusz>--<nr>.json|.sse``.
Zmiany tras między wersjami rozwiązuję polem ``versions`` w kroku.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import yaml
from normalize import IdRegistry, normalize_json, normalize_sse

if TYPE_CHECKING:
    from rf_bootstrap import RagflowSession

ALL_VERSIONS = ("v0.24.0", "v0.27.2")
METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
AUTH_MODES = ("key", "jwt", "second", "second_jwt", "none", "bad")
_EXPECT_KEYS = frozenset({"status", "code"})
BAD_KEY = "ragflow-invalid-key-0000"
_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_PLACEHOLDER_RE = re.compile(r"/\{[^}]*\}/?")
_DEFAULT_INTERVAL_S = 3.0
_DEFAULT_TIMEOUT_S = 600.0
_REQUEST_TIMEOUT_S = 120.0

JSON_SUFFIX = ".json"
SSE_SUFFIX = ".sse"


def kind_of(variable: str) -> str:
    """Rodzaj id dla IdRegistry: nazwa zmiennej bez sufiksu ``_id``."""
    return variable.removesuffix("_id")


def load_scenario(path: Path) -> dict:
    """Wczytuje i waliduje scenariusz YAML (name == nazwa pliku, unikalne id kroków)."""
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
        if str(step.get("method", "")).upper() not in METHODS:
            raise ValueError(
                f"{path.name}/{step_id}: zła metoda {step.get('method')!r}"
            )
        if not isinstance(step.get("path"), str):
            raise TypeError(f"{path.name}/{step_id}: brak 'path'")
        if step.get("auth", "key") not in AUTH_MODES:
            raise ValueError(
                f"{path.name}/{step_id}: zły tryb auth {step.get('auth')!r}"
            )
        expect = step.get("expect")
        valid_expect = (
            expect is None
            or expect == "any"
            or (
                isinstance(expect, dict)
                and set(expect) <= _EXPECT_KEYS
                and all(isinstance(value, int) for value in expect.values())
            )
        )
        if not valid_expect:
            raise ValueError(f"{path.name}/{step_id}: złe 'expect' {expect!r}")
        if "binary" in step and not isinstance(step["binary"], bool):
            raise ValueError(
                f"{path.name}/{step_id}: 'binary' musi być bool {step['binary']!r}"
            )
    return data


def endpoint_dir(path_template: str) -> str:
    """Ścieżka -> nazwa katalogu golden.

    ``/api/v1/datasets/{dataset_id}/documents`` -> ``datasets___documents``;
    ścieżki spoza ``/api/v1/`` tracą tylko wiodący ukośnik
    (``/v1/system/healthz`` -> ``v1__system__healthz``).
    """
    if path_template.startswith("/api/v1/"):
        relative = path_template.removeprefix("/api/v1/")
    else:
        relative = path_template.removeprefix("/")
    return _PLACEHOLDER_RE.sub("___", relative).replace("/", "__")


def auth_headers(session: Any, mode: str) -> dict[str, str]:
    """Nagłówki żądania dla trybu ``auth`` kroku (C1/C2)."""
    if mode == "key":
        return {"Authorization": f"Bearer {session.api_key}"}
    if mode == "jwt":
        return {"Authorization": session.auth}
    if mode == "second":
        return {"Authorization": f"Bearer {session.api_key_2}"}
    if mode == "second_jwt":
        return {"Authorization": session.auth_2}
    if mode == "none":
        return {}
    if mode == "bad":
        return {"Authorization": f"Bearer {BAD_KEY}"}
    raise ValueError(f"nieznany tryb auth: {mode!r}")


def check_expect(step: dict, status_code: int, parsed: Any) -> None:
    """Sprawdza ``expect`` kroku (C1); ``any`` nic nie sprawdza, brak -> nic."""
    expect = step.get("expect")
    if expect is None or expect == "any":
        return
    if "status" in expect and status_code != expect["status"]:
        raise RuntimeError(
            f"krok {step['id']}: HTTP {status_code} != oczekiwane {expect['status']}"
        )
    if "code" in expect:
        code = parsed.get("code") if isinstance(parsed, dict) else None
        if code != expect["code"]:
            raise RuntimeError(
                f"krok {step['id']}: code={code} != oczekiwane {expect['code']}"
            )


def binary_body(content: bytes) -> dict[str, Any]:
    """Payload złota dla kroku ``binary``: długość i skrót treści (C2)."""
    return {"length": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def _substitute(value: Any, variables: dict[str, str]) -> Any:
    """Podstawia zmienne {nazwa} wartościami przechwyconymi z wcześniejszych kroków."""
    if isinstance(value, str):
        return _VAR_RE.sub(lambda m: variables[m.group(1)], value)
    if isinstance(value, dict):
        return {key: _substitute(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, variables) for item in value]
    return value


def _snapshot_value(value: Any, variables: dict[str, str], ids: IdRegistry) -> Any:
    """Podstawia zmienne {nazwa} tokenami id — snapshot bez surowych identyfikatorów."""
    if isinstance(value, str):
        return _VAR_RE.sub(
            lambda m: ids.token(kind_of(m.group(1)), variables[m.group(1)]), value
        )
    if isinstance(value, dict):
        return {
            key: _snapshot_value(item, variables, ids) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_snapshot_value(item, variables, ids) for item in value]
    return value


def _dig(obj: Any, dotted: str) -> Any:
    current = obj
    for part in dotted.split("."):
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _capture(response_json: Any, path: str) -> Any:
    value = _dig(response_json, path)
    if value is None:
        raise RuntimeError(f"capture: brak {path} w odpowiedzi")
    return value


def _target_path(
    out_root: Path,
    version: str,
    step: dict,
    scenario_name: str,
    number: int,
    suffix: str,
) -> Path:
    return (
        out_root
        / version
        / endpoint_dir(step["path"])
        / f"{scenario_name}--{number:02d}{suffix}"
    )


def _request(
    client: httpx.Client,
    step: dict,
    path: str,
    query: dict,
    body: dict | None,
    fixture_root: Path,
    headers: dict[str, str],
) -> httpx.Response:
    """Pojedyncze żądanie HTTP; dla stream=True czyta cały strumień do pamięci."""
    if step.get("stream"):
        with client.stream(
            "POST", path, params=query or None, json=body, headers=headers
        ) as response:
            response.read()
            return response
    if "multipart" in step:
        files = []
        for field, relative in step["multipart"].items():
            file_path = fixture_root / relative
            files.append((field, (file_path.name, file_path.read_bytes())))
        return client.request(
            step["method"].upper(),
            path,
            params=query or None,
            files=files,
            headers=headers,
        )
    return client.request(
        step["method"].upper(),
        path,
        params=query or None,
        json=body,
        headers=headers,
    )


def _run_step(
    client: httpx.Client,
    step: dict,
    variables: dict[str, str],
    fixture_root: Path,
    headers: dict[str, str],
) -> httpx.Response:
    """Wykonuje krok (z poll, jeśli jest) i zwraca ostatnią odpowiedź."""
    path = _substitute(step["path"], variables)
    query = _substitute(step.get("query") or {}, variables)
    body = _substitute(step.get("json"), variables) if "json" in step else None
    poll = step.get("poll")
    if poll is None:
        return _request(client, step, path, query, body, fixture_root, headers)
    until = poll["until"]
    interval_s = float(poll.get("interval_s", _DEFAULT_INTERVAL_S))
    timeout_s = float(poll.get("timeout_s", _DEFAULT_TIMEOUT_S))
    deadline = time.monotonic() + timeout_s
    while True:
        response = _request(client, step, path, query, body, fixture_root, headers)
        parsed = _parse_body(response)
        if _dig(parsed, until["path"]) == until["equals"]:
            return response
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"poll: {until['path']} != {until['equals']!r} po {timeout_s}s; "
                f"ostatnia odpowiedź: {str(parsed)[:300]}"
            )
        time.sleep(interval_s)


def _parse_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def run_scenario(
    session: RagflowSession, scenario: dict, version: str, out_root: Path
) -> int:
    """Wykonuje scenariusz dla jednej wersji; zwraca liczbę zapisanych plików golden.

    Wyjątek przy dowolnym błędzie kroku (scenariusz FAIL). W biegu pomija kroki
    z polem ``versions`` niewskazującym tej wersji (numer kroku i tak zajęty).
    """
    ids = IdRegistry()
    variables: dict[str, str] = {}
    name = scenario["name"]
    fixture_root = Path(__file__).resolve().parent
    saved = 0
    with httpx.Client(base_url=session.base_url, timeout=_REQUEST_TIMEOUT_S) as client:
        for number, step in enumerate(scenario["steps"], start=1):
            if version not in step.get("versions", ALL_VERSIONS):
                continue
            binary = bool(step.get("binary"))
            step_headers = auth_headers(session, step.get("auth", "key"))
            response = _run_step(client, step, variables, fixture_root, step_headers)
            content_type = response.headers.get("content-type", "")
            # kroku binary nie parsuję JSON-em, chyba że odpowiedź jest JSON-em
            parsed = (
                _parse_body(response) if not binary or "json" in content_type else None
            )
            if step.get("expect") is None:
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"krok {step['id']}: HTTP {response.status_code}: "
                        f"{response.text[:300]}"
                    )
                if isinstance(parsed, dict) and parsed.get("code") not in (None, 0):
                    raise RuntimeError(
                        f"krok {step['id']}: code={parsed.get('code')}: "
                        f"{str(parsed.get('message'))[:300]}"
                    )
            else:
                check_expect(step, response.status_code, parsed)
            for variable, dotted in (step.get("capture") or {}).items():
                raw = _capture(parsed, dotted)
                if not isinstance(raw, str):
                    raise TypeError(
                        f"krok {step['id']}: capture {variable} nie jest stringiem"
                    )
                variables[variable] = raw
                ids.token(kind_of(variable), raw)
            if not step.get("record", True):
                continue
            if step.get("stream"):
                content = normalize_sse(response.content, ids)
                target = _target_path(out_root, version, step, name, number, SSE_SUFFIX)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            else:
                payload_headers = {"content-type": content_type}
                payload_body = normalize_json(parsed, ids)
                if binary:
                    payload_headers["content-length"] = str(len(response.content))
                    payload_body = binary_body(response.content)
                payload = {
                    "request": {
                        "method": step["method"].upper(),
                        "path": _snapshot_value(step["path"], variables, ids),
                        "query": _snapshot_value(
                            step.get("query") or {}, variables, ids
                        ),
                        "body": (
                            _snapshot_value(step.get("json"), variables, ids)
                            if "json" in step
                            else None
                        ),
                    },
                    "status": response.status_code,
                    "headers": payload_headers,
                    "body": payload_body,
                }
                target = _target_path(
                    out_root, version, step, name, number, JSON_SUFFIX
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            saved += 1
    return saved
