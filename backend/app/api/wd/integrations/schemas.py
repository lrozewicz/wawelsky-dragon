"""Modele pydantic powierzchni WD integracji (kontrakt WP E4-3b §2).

Klucze modeli odpowiedzi pokrywają się 1:1 ze słownikami DTO SVC
(``app.api.hub_compat.sharepoint.dto``), a ``Integration`` dokłada ``type`` — dlatego trasy walidują
odpowiedź przez ``Model.model_validate(dto_dict)`` i żadne pole spoza kontraktu nie wycieka
(kontrakt §0 p. 1, §0 p. 7: w odpowiedziach jest wyłącznie maska sekretu).
"""

from typing import Literal

from pydantic import BaseModel, Field, StrictBool, StrictInt

from app.services.integration_input import (
    DEFAULT_EXCLUDED_LIBRARY_NAMES,
    DEFAULT_IGNORED_EXTENSIONS,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_SCAN_INTERVAL_SECONDS,
)


def _default_excluded_library_names() -> list[str]:
    """Kopia domyślnej listy wykluczonych bibliotek (mutowalna wartość domyślna)."""
    return list(DEFAULT_EXCLUDED_LIBRARY_NAMES)


def _default_ignored_extensions() -> list[str]:
    """Kopia domyślnej listy ignorowanych rozszerzeń (mutowalna wartość domyślna)."""
    return list(DEFAULT_IGNORED_EXTENSIONS)


class Envelope[T](BaseModel):
    """Koperta sukcesu WD: ``{"data": …}`` (K3)."""

    data: T


class Page[T](BaseModel):
    """Strona listy w pamięci: elementy i licznik (kontrakt §0 p. 4)."""

    items: list[T] = Field(description="Elementy bieżącej strony")
    total: int = Field(description="Łączna liczba elementów")
    page: int = Field(description="Numer strony (od 1)")
    page_size: int = Field(description="Rozmiar strony")


class CursorPage[T](BaseModel):
    """Strona kursorowa: elementy i id następnego kursora albo ``None`` (kontrakt §0 p. 5)."""

    items: list[T] = Field(description="Elementy bieżącej strony")
    next_after_id: int | None = Field(description="Id kursora następnej strony albo null")


class WdErrorDetail(BaseModel):
    """Treść koperty błędu przestrzeni wd (K3)."""

    code: str = Field(description="Slug błędu")
    message: str = Field(description="Komunikat błędu")
    details: object | None = Field(description="Szczegóły błędu albo null")


class WdErrorResponse(BaseModel):
    """Koperta błędu WD w dokumentacji OpenAPI (kontrakt §0 p. 10)."""

    error: WdErrorDetail


class Integration(BaseModel):
    """Integracja SharePoint: ``integration_dto`` + ``type`` (20 kluczy, kontrakt §0 p. 1)."""

    id: int = Field(description="Identyfikator integracji")
    type: Literal["sharepoint"] = Field(description="Typ integracji")
    name: str = Field(description="Nazwa integracji")
    dataset_id: str = Field(description="Identyfikator datasetu docelowego")
    tenant_id: str = Field(description="Identyfikator dzierżawy Entra ID")
    client_id: str = Field(description="Identyfikator aplikacji w Entra ID")
    client_secret_masked: str = Field(description="Maska sekretu klienta (ostatnie 4 znaki)")
    site_url: str = Field(description="Adres witryny SharePoint")
    site_id: str | None = Field(description="Identyfikator rozwiązanej witryny")
    excluded_library_names: list[str] = Field(description="Wykluczone biblioteki dokumentów")
    max_file_size_bytes: int = Field(description="Maksymalny rozmiar pliku w bajtach")
    ignored_extensions: list[str] = Field(description="Ignorowane rozszerzenia plików")
    scan_interval_seconds: int = Field(description="Odstęp między skanami w sekundach")
    delete_propagation: bool = Field(description="Czy usuwać dokumenty po zniknięciu pliku")
    is_active: bool = Field(description="Czy integracja jest aktywna")
    is_running: bool = Field(description="Czy trwa przebieg synchronizacji")
    last_sync_at: str | None = Field(description="Czas ostatniej synchronizacji (ISO 8601)")
    last_sync_status: str | None = Field(description="Status ostatniej synchronizacji")
    created_at: str | None = Field(description="Czas utworzenia (ISO 8601)")
    updated_at: str | None = Field(description="Czas ostatniej zmiany (ISO 8601)")


class IntegrationRun(BaseModel):
    """Przebieg synchronizacji (kontrakt §2)."""

    id: int = Field(description="Identyfikator przebiegu")
    integration_id: int = Field(description="Identyfikator integracji")
    integration_type: str = Field(description="Typ integracji")
    started_at: str | None = Field(description="Czas rozpoczęcia (ISO 8601)")
    finished_at: str | None = Field(description="Czas zakończenia (ISO 8601)")
    status: str = Field(description="Status przebiegu")
    added: int = Field(description="Liczba dodanych dokumentów")
    updated: int = Field(description="Liczba zaktualizowanych dokumentów")
    deleted: int = Field(description="Liczba usuniętych dokumentów")
    failed: int = Field(description="Liczba błędów")


class IntegrationEvent(BaseModel):
    """Zdarzenie przebiegu (kontrakt §2)."""

    id: int = Field(description="Identyfikator zdarzenia")
    run_id: int = Field(description="Identyfikator przebiegu")
    integration_id: int = Field(description="Identyfikator integracji")
    integration_type: str = Field(description="Typ integracji")
    level: str = Field(description="Poziom zdarzenia")
    message: str = Field(description="Treść zdarzenia")
    file_path: str | None = Field(description="Ścieżka pliku w witrynie")
    drive_id: str | None = Field(description="Identyfikator biblioteki")
    drive_name: str | None = Field(description="Nazwa biblioteki")
    created_at: str | None = Field(description="Czas zdarzenia (ISO 8601)")


class IntegrationDrive(BaseModel):
    """Biblioteka dokumentów integracji (kontrakt §2)."""

    drive_id: str = Field(description="Identyfikator biblioteki")
    drive_name: str = Field(description="Nazwa biblioteki")
    has_delta: bool = Field(description="Czy zapisano kursor delty")
    last_sync_at: str | None = Field(description="Czas ostatniej synchronizacji (ISO 8601)")
    discovered_at: str | None = Field(description="Czas odkrycia biblioteki (ISO 8601)")


class IntegrationLatestRun(BaseModel):
    """Skrót ostatniego przebiegu w statusie integracji (kontrakt §2)."""

    id: int = Field(description="Identyfikator przebiegu")
    started_at: str | None = Field(description="Czas rozpoczęcia (ISO 8601)")
    finished_at: str | None = Field(description="Czas zakończenia (ISO 8601)")
    status: str = Field(description="Status przebiegu")
    added: int = Field(description="Liczba dodanych dokumentów")
    updated: int = Field(description="Liczba zaktualizowanych dokumentów")
    deleted: int = Field(description="Liczba usuniętych dokumentów")
    failed: int = Field(description="Liczba błędów")


class IntegrationStatus(BaseModel):
    """Stan integracji i jej ostatni przebieg (kontrakt §2)."""

    id: int = Field(description="Identyfikator integracji")
    is_active: bool = Field(description="Czy integracja jest aktywna")
    is_running: bool = Field(description="Czy trwa przebieg synchronizacji")
    last_sync_at: str | None = Field(description="Czas ostatniej synchronizacji (ISO 8601)")
    last_sync_status: str | None = Field(description="Status ostatniej synchronizacji")
    latest_run: IntegrationLatestRun | None = Field(description="Ostatni przebieg albo null")


class ConnectionTest(BaseModel):
    """Raport testu połączenia — klucze z ``build_report`` (kontrakt §2)."""

    graph_auth: str = Field(description="Wynik uwierzytelnienia w Graph")
    graph_auth_error: str | None = Field(default=None, description="Błąd uwierzytelnienia w Graph")
    site_resolution: str = Field(description="Wynik rozwiązania witryny")
    site_resolution_error: str | None = Field(default=None, description="Błąd rozwiązania witryny")
    site_id: str | None = Field(default=None, description="Identyfikator rozwiązanej witryny")
    site_display_name: str | None = Field(default=None, description="Nazwa rozwiązanej witryny")
    drives_visible: int | None = Field(default=None, description="Liczba widocznych bibliotek")
    drives_after_exclusion: int | None = Field(
        default=None, description="Liczba bibliotek po wykluczeniach"
    )
    drive_names: list[str] | None = Field(
        default=None, description="Nazwy uwzględnionych bibliotek"
    )
    dataset_exists: str = Field(description="Wynik sprawdzenia datasetu")
    dataset_name: str | None = Field(default=None, description="Nazwa datasetu")


class SyncQueued(BaseModel):
    """Potwierdzenie zlecenia synchronizacji bez oczekiwania (kontrakt §4)."""

    queued: bool = Field(description="Czy przebieg został zakolejkowany")


class CancelResult(BaseModel):
    """Wynik anulowania przebiegu (kontrakt §4)."""

    cancelled: bool = Field(description="Czy cokolwiek anulowano")


class DriveList(BaseModel):
    """Lista bibliotek integracji (kontrakt §2)."""

    items: list[IntegrationDrive] = Field(description="Biblioteki dokumentów")


class SourceLink(BaseModel):
    """Link do dokumentu źródłowego w SharePoint (kontrakt §4)."""

    web_url: str = Field(description="Adres dokumentu w SharePoint")
    name: str | None = Field(description="Nazwa pliku")
    path: str | None = Field(description="Ścieżka pliku w bibliotece")
    drive_name: str | None = Field(description="Nazwa biblioteki")


class IntegrationCreateRequest(BaseModel):
    """Ciało ``POST /integrations`` — pola wymagane + domyślne z ``integration_input`` (§2)."""

    type: Literal["sharepoint"] = Field(description="Typ integracji (na razie tylko sharepoint)")
    name: str = Field(min_length=1, description="Nazwa integracji")
    dataset_id: str = Field(min_length=1, description="Identyfikator datasetu docelowego")
    tenant_id: str = Field(min_length=1, description="Identyfikator dzierżawy Entra ID")
    client_id: str = Field(min_length=1, description="Identyfikator aplikacji w Entra ID")
    client_secret: str = Field(min_length=1, description="Sekret klienta aplikacji")
    site_url: str = Field(min_length=1, description="Adres witryny SharePoint")
    excluded_library_names: list[str] = Field(
        default_factory=_default_excluded_library_names,
        description="Wykluczone biblioteki dokumentów",
    )
    max_file_size_bytes: StrictInt = Field(
        DEFAULT_MAX_FILE_SIZE_BYTES, ge=1, description="Maksymalny rozmiar pliku w bajtach"
    )
    ignored_extensions: list[str] = Field(
        default_factory=_default_ignored_extensions,
        description="Ignorowane rozszerzenia plików",
    )
    scan_interval_seconds: StrictInt = Field(
        DEFAULT_SCAN_INTERVAL_SECONDS, ge=30, description="Odstęp między skanami w sekundach"
    )
    delete_propagation: StrictBool = Field(
        True, description="Czy usuwać dokumenty po zniknięciu pliku"
    )
    is_active: StrictBool = Field(True, description="Czy integracja jest od razu aktywna")


class IntegrationUpdateRequest(BaseModel):
    """Ciało ``PATCH /integrations/{id}`` — ``None``/pominięte pole oznacza brak zmiany (§2)."""

    type: Literal["sharepoint"] | None = Field(
        default=None, description="Typ integracji (niezmienialny)"
    )
    name: str | None = Field(default=None, min_length=1, description="Nazwa integracji")
    dataset_id: str | None = Field(
        default=None, min_length=1, description="Identyfikator datasetu docelowego"
    )
    tenant_id: str | None = Field(
        default=None, min_length=1, description="Identyfikator dzierżawy Entra ID"
    )
    client_id: str | None = Field(
        default=None, min_length=1, description="Identyfikator aplikacji w Entra ID"
    )
    client_secret: str | None = Field(default=None, min_length=1, description="Sekret klienta")
    site_url: str | None = Field(default=None, min_length=1, description="Adres witryny SharePoint")
    excluded_library_names: list[str] | None = Field(
        default=None, description="Wykluczone biblioteki dokumentów"
    )
    max_file_size_bytes: StrictInt | None = Field(
        default=None, ge=1, description="Maksymalny rozmiar pliku w bajtach"
    )
    ignored_extensions: list[str] | None = Field(
        default=None, description="Ignorowane rozszerzenia plików"
    )
    scan_interval_seconds: StrictInt | None = Field(
        default=None, ge=30, description="Odstęp między skanami w sekundach"
    )
    delete_propagation: StrictBool | None = Field(
        default=None, description="Czy usuwać dokumenty po zniknięciu pliku"
    )
    is_active: StrictBool | None = Field(default=None, description="Czy integracja jest aktywna")


class ConnectionTestRequest(BaseModel):
    """Ciało ``POST /integrations/test`` — jak ``test-connection`` SVC plus ``type`` (§2)."""

    type: Literal["sharepoint"] = Field(description="Typ integracji (na razie tylko sharepoint)")
    tenant_id: str = Field(min_length=1, description="Identyfikator dzierżawy Entra ID")
    client_id: str = Field(min_length=1, description="Identyfikator aplikacji w Entra ID")
    client_secret: str = Field(min_length=1, description="Sekret klienta aplikacji")
    site_url: str = Field(min_length=1, description="Adres witryny SharePoint")
    dataset_id: str | None = Field(
        default=None, description="Identyfikator datasetu do sprawdzenia (opcjonalny)"
    )
    excluded_library_names: list[str] = Field(
        default_factory=_default_excluded_library_names,
        description="Wykluczone biblioteki dokumentów",
    )


class SavedConnectionTestRequest(BaseModel):
    """Ciało ``POST /integrations/{id}/test`` — wszystkie pola opcjonalne (kontrakt §2)."""

    tenant_id: str | None = Field(
        default=None, min_length=1, description="Identyfikator dzierżawy Entra ID"
    )
    client_id: str | None = Field(
        default=None, min_length=1, description="Identyfikator aplikacji w Entra ID"
    )
    client_secret: str | None = Field(default=None, min_length=1, description="Sekret klienta")
    site_url: str | None = Field(default=None, min_length=1, description="Adres witryny SharePoint")
    dataset_id: str | None = Field(
        default=None, min_length=1, description="Identyfikator datasetu do sprawdzenia"
    )
    excluded_library_names: list[str] | None = Field(
        default=None, description="Wykluczone biblioteki dokumentów"
    )
