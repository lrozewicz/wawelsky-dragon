"""Testy unit fundamentu OpenAPI (brief T1, wym. 7): build_openapi i eksport (K6 §4)."""

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from app.api import openapi
from app.api.openapi_export import STALE_MESSAGE, export_settings, main, render
from app.api.ragflow.schemas.common import RagflowError, RequestModel
from app.main import create_app


@pytest.fixture(autouse=True)
def _clean_wd_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Izolacja od WD_* z env procesu — Settings() czyta tylko to, co test ustawi."""
    for name in list(os.environ):
        if name.startswith("WD_"):
            monkeypatch.delenv(name)


def test_build_openapi_is_cached() -> None:
    """Drugie wywołanie app.openapi() zwraca ten sam obiekt (cache, C2.2)."""
    app = create_app(export_settings())
    assert app.openapi() is app.openapi()


def test_api_v1_errors_replace_422() -> None:
    """/api/v1: 422 znika, 401 i default wskazują RagflowError; walidacja z komponentów."""
    schema = create_app(export_settings()).openapi()
    responses = schema["paths"]["/api/v1/datasets/{dataset_id}"]["get"]["responses"]
    assert "422" not in responses
    ref = {"$ref": "#/components/schemas/RagflowError"}
    assert responses["401"]["content"]["application/json"]["schema"] == ref
    assert responses["default"]["content"]["application/json"]["schema"] == ref
    assert "HTTPValidationError" not in schema["components"]["schemas"]


def test_component_conflict_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model o nazwie RagflowError i innej treści → ValueError (C2.2 krok 2)."""

    class ModelA(BaseModel):
        other: int

    ModelA.__name__ = "RagflowError"
    monkeypatch.setattr(openapi, "REQUEST_MODELS", (ModelA,))
    app = create_app(export_settings())
    with pytest.raises(ValueError, match="konflikt komponentu RagflowError"):
        app.openapi()


def test_same_component_twice_is_not_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ta sama nazwa i identyczna treść → bez konfliktu (C2.2 krok 2)."""
    monkeypatch.setattr(openapi, "REQUEST_MODELS", (RagflowError,))
    app = create_app(export_settings())
    schema = app.openapi()
    assert "RagflowError" in schema["components"]["schemas"]


def test_validation_components_kept_when_referenced() -> None:
    """422 poza /api/v1: komponenty walidacji zostają, dopóki są cytowane (C2.2 krok 4)."""
    app = FastAPI()

    @app.get("/other/{item_id}")
    def other(item_id: int) -> dict[str, int]:
        """Trasa poza /api/v1 — jej 422 nadal cytuję schematy walidacji."""
        return {"item_id": item_id}

    schema = openapi.build_openapi(app)
    components = schema["components"]["schemas"]
    assert "HTTPValidationError" in components
    assert "ValidationError" in components


def test_nested_defs_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model żądania z polem-modelu: $defs trafiają do komponentów razem z nim."""

    class Inner(RequestModel):
        x: int

    class Outer(RequestModel):
        inner: Inner

    monkeypatch.setattr(openapi, "REQUEST_MODELS", (Outer,))
    schema = create_app(export_settings()).openapi()
    components = schema["components"]["schemas"]
    assert "Outer" in components
    assert "Inner" in components
    assert components["Outer"]["properties"]["inner"]["$ref"] == "#/components/schemas/Inner"


def test_export_writes_file(tmp_path: Path) -> None:
    """main bez --check: zapisuje plik == render() i zwraca 0 (C2.3)."""
    path = tmp_path / "openapi.json"
    assert main([], path=path) == 0
    assert path.read_text(encoding="utf-8") == render()


def test_export_check_current(tmp_path: Path) -> None:
    """--check na aktualnym pliku → 0."""
    path = tmp_path / "openapi.json"
    main([], path=path)
    assert main(["--check"], path=path) == 0


def test_export_check_stale(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """--check po dryfie → 1 i STALE_MESSAGE na stderr."""
    path = tmp_path / "openapi.json"
    main([], path=path)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(" ")
    assert main(["--check"], path=path) == 1
    assert STALE_MESSAGE in capsys.readouterr().err


def test_export_check_missing(tmp_path: Path) -> None:
    """--check na brakującym pliku → 1."""
    assert main(["--check"], path=tmp_path / "brak.json") == 1


def test_files_create_declares_multipart_and_json_body() -> None:
    """C3: ``files_create`` przyjmuje multipart upload ORAZ JSON folderu (``FolderCreateBody``)."""
    schema = create_app(export_settings()).openapi()
    content = schema["paths"]["/api/v1/files"]["post"]["requestBody"]["content"]
    assert content["multipart/form-data"]["schema"] == {
        "$ref": "#/components/schemas/FileUploadForm"
    }
    assert content["application/json"]["schema"] == {
        "$ref": "#/components/schemas/FolderCreateBody"
    }


def test_folder_create_body_schema_matches_contract() -> None:
    """C3: ``FolderCreateBody`` — ``name``/``type`` wymagane, ``type`` = ``["folder"]``."""
    node = create_app(export_settings()).openapi()["components"]["schemas"]["FolderCreateBody"]
    assert node["required"] == ["name", "type"]
    assert node["properties"]["type"]["enum"] == ["folder"]
    assert node["additionalProperties"] is False
    assert "default" not in node["properties"]["parent_id"]
