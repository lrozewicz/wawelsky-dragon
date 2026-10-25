"""Modele pydantic eksportu/importu paczki ``.wdkb.zip`` — dosłownie z K19 §3.

Wszystkie kształty z sekcji „Schematy (``data`` koperty)” kontraktu K19: ``TaskRef``,
``WdTask`` (z unią ``result``), ``ExportResult``, ``ImportResult``, ``ExportPreview``,
``DatasetImport`` i ``ImportSummary``. Modele zagnieżdżone (``EmbeddingRef``, ``TaskError``,
``ImportTarget``…) odpowiadają obiektom bez nazwy w K19 — trasy 1-2 i 6-10 dopisują E7-1a/E7-1b,
te modele są wspólne dla obu.
"""

from typing import Literal

from pydantic import BaseModel, Field

# Stały rozmiar porcji uploadu (K19 §3, trasa 7) — nie da się go nadpisać z env.
IMPORT_CHUNK_SIZE = 8_388_608

WdTaskKind = Literal["export", "import"]
WdTaskStatus = Literal["queued", "running", "done", "failed", "cancelled"]
WdTaskStage = Literal["files", "documents", "chunks", "vectors", "embedding", "finalize"]
ImportState = Literal["uploading", "ready", "invalid", "started", "expired"]


class TaskRef(BaseModel):
    """Odniesienie do zleconego zadania (K19 §3) — status nowego zadania to zawsze ``queued``."""

    task_id: str = Field(description="Identyfikator zadania (32 hex)")
    status: Literal["queued"] = Field(default="queued", description="Status nowego zadania")


class TaskError(BaseModel):
    """Błąd zadania w kopercie ``WdTask`` (K19 §3)."""

    code: str = Field(description="Slug błędu (np. task_failed albo kod walidacji paczki)")
    message: str = Field(description="Komunikat błędu")


class ExportResult(BaseModel):
    """Wynik zakończonego eksportu — link podpisany (K19 §3)."""

    download_url: str = Field(description="Adres pobrania paczki z podpisem")
    expires_at: int = Field(description="Wygaśnięcie linku (ms epoki)")
    size_bytes: int = Field(description="Rozmiar paczki w bajtach")
    file_name: str = Field(description="Nazwa pliku paczki")


class ImportResult(BaseModel):
    """Wynik zakończonego importu (K19 §3)."""

    dataset_id: str = Field(description="Identyfikator utworzonego datasetu")
    dataset_name: str = Field(description="Nazwa utworzonego datasetu")
    documents: int = Field(description="Liczba zaimportowanych dokumentów")
    chunks: int = Field(description="Liczba zaimportowanych chunków")
    reembedded: bool = Field(description="Czy wektory zostały przeliczone")


class WdTask(BaseModel):
    """Stan zadania eksportu/importu widziany przez użytkownika (K19 §3)."""

    task_id: str = Field(description="Identyfikator zadania (32 hex)")
    kind: WdTaskKind = Field(description="Rodzaj zadania: export albo import")
    dataset_id: str | None = Field(description="Dataset źródłowy (eksport) albo null")
    status: WdTaskStatus = Field(description="Status zadania (wewnętrzne dead → failed)")
    stage: WdTaskStage | None = Field(description="Etap pracy albo null, gdy nieznany")
    done: int = Field(description="Elementy przetworzone w bieżącym etapie")
    total: int = Field(description="Elementy etapu do przetworzenia")
    progress: float = Field(description="Postęp zadania 0..1")
    message: str = Field(description="Komunikat postępu po polsku (np. „Pliki 12/40”)")
    error: TaskError | None = Field(description="Błąd zadania albo null")
    created_at: int = Field(description="Utworzenie zadania (ms epoki)")
    finished_at: int | None = Field(description="Zakończenie zadania (ms epoki) albo null")
    result: ExportResult | ImportResult | None = Field(
        description="Wynik zadania dla statusu done (eksport albo import)"
    )


class EmbeddingRef(BaseModel):
    """Model embeddingów z manifestu paczki (K19 §3)."""

    model_name: str = Field(description="Nazwa modelu embeddingów")
    dimension: int = Field(description="Wymiar wektorów")


class ExportPreview(BaseModel):
    """Szacunek eksportu datasetu (K19 §3, trasa 1)."""

    dataset_id: str = Field(description="Identyfikator datasetu")
    name: str = Field(description="Nazwa datasetu")
    documents: int = Field(description="Liczba dokumentów")
    chunks: int = Field(description="Liczba chunków")
    estimated_bytes: int = Field(description="Szacowany rozmiar paczki bez wektorów")
    estimated_bytes_with_vectors: int = Field(description="Szacowany rozmiar paczki z wektorami")
    embedding: EmbeddingRef = Field(description="Model embeddingów datasetu")
    max_bytes: int = Field(description="Limit rozmiaru paczki (WD_EXPORT_MAX_BYTES)")


class ImportEmbedding(BaseModel):
    """Model embeddingów paczki importu wraz z informacją o wektorach (K19 §3)."""

    model_name: str = Field(description="Nazwa modelu embeddingów z paczki")
    dimension: int = Field(description="Wymiar wektorów z paczki")
    included: bool = Field(description="Czy paczka niesie wektory")


class TargetModel(BaseModel):
    """Model embeddingów dostępny aktorowi importu (K19 §3)."""

    name: str = Field(description="Nazwa modelu")
    dimension: int = Field(description="Wymiar modelu")


class ImportTarget(BaseModel):
    """Docelowy model importu: zgodność z paczką i dostępne modele (K19 §3)."""

    compatible: bool = Field(description="Czy model paczki jest dostępny w tej samej postaci")
    default_model: str | None = Field(description="Model domyślny dla importu albo null")
    models: list[TargetModel] = Field(description="Modele embeddingów dostępne aktorowi")


class ImportSummary(BaseModel):
    """Podsumowanie paczki po walidacji (K19 §3)."""

    name: str = Field(description="Nazwa datasetu z paczki")
    description: str | None = Field(description="Opis datasetu z paczki albo null")
    documents: int = Field(description="Liczba dokumentów w paczce")
    chunks: int = Field(description="Liczba chunków w paczce")
    schema_version: int = Field(description="Wersja schematu paczki")
    wd_version: str = Field(description="Wersja Wawelsky Dragon, która paczkę utworzyła")
    created_at: str = Field(description="Czas utworzenia paczki (ISO 8601)")
    embedding: ImportEmbedding = Field(description="Model embeddingów paczki")
    target: ImportTarget = Field(description="Docelowy model importu i dostępne modele")
    suggested_name: str = Field(description="Nazwa proponowana dla importowanego datasetu")
    name_taken: bool = Field(description="Czy nazwa z paczki jest już zajęta")
    estimated_reembed_tokens: int = Field(
        description="Łączna liczba tokenów do ponownego embeddingu"
    )


class DatasetImport(BaseModel):
    """Sesja uploadu paczki importu (K19 §3, trasy 6-8)."""

    import_id: str = Field(description="Identyfikator sesji importu (32 hex)")
    file_name: str = Field(description="Nazwa wysyłanego pliku")
    size_bytes: int = Field(description="Zadeklarowany rozmiar paczki")
    received_bytes: int = Field(description="Liczba przyjętych bajtów")
    chunk_size: int = Field(default=IMPORT_CHUNK_SIZE, description="Maksymalny rozmiar porcji")
    state: ImportState = Field(description="Stan sesji importu")
    errors: list[TaskError] = Field(description="Błędy walidacji paczki (state=invalid)")
    summary: ImportSummary | None = Field(description="Podsumowanie paczki albo null")
    task_id: str | None = Field(description="Zadanie importu po starcie albo null")
    expires_at: int = Field(description="Wygaśnięcie sesji (ms epoki)")
