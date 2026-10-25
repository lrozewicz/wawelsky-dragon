"""Modele pydantic tras systemowych WD (kontrakt E3-6a §3; T4 audyt, T5 stats).

``AuditEntry`` to pojedynczy wpis dziennika audytu w odpowiedzi ``GET /audit``; ``details``
pochodzą z trasy już po usunięciu kluczy wrażliwych (``password|token|secret``). Modele
``Probe``…``Stats`` opisują odpowiedź ``GET /stats``.
"""

from pydantic import BaseModel, Field


class AuditEntry(BaseModel):
    """Wpis dziennika audytu (kontrakt §3)."""

    id: int = Field(description="Identyfikator wpisu")
    ts: str | None = Field(description="Czas zdarzenia (ISO 8601)")
    actor_id: str | None = Field(description="Identyfikator aktora")
    actor: str = Field(description="Etykieta aktora (e-mail)")
    action: str = Field(description="Akcja audytu")
    target_type: str = Field(description="Typ zasobu, którego dotyczy akcja")
    target_id: str = Field(description="Identyfikator zasobu, którego dotyczy akcja")
    details: dict[str, object] | None = Field(description="Szczegóły akcji bez pól wrażliwych")
    ip: str | None = Field(description="Adres IP klienta")


class Probe(BaseModel):
    """Sonda komponentu systemu WD (kontrakt E3-6a §3)."""

    ok: bool = Field(description="Czy sonda się powiodła")
    elapsed_ms: float = Field(description="Czas trwania sondy w milisekundach")


class Worker(BaseModel):
    """Tętno pojedynczego workera (kontrakt E3-6a §3)."""

    worker_id: str = Field(description="Identyfikator workera")
    version: str | None = Field(description="Wersja workera z tętna albo null")
    started_at: str | None = Field(description="Czas startu procesu (ISO 8601) albo null")
    heartbeat_at: str | None = Field(description="Czas ostatniego tętna (ISO 8601) albo null")
    active: bool = Field(description="Czy tętno jest świeższe niż 60 sekund")
    capabilities: object | None = Field(description="Możliwości workera albo null")


class WorkersInfo(BaseModel):
    """Workery WD wraz z liczbą aktywnych (kontrakt E3-6a §3)."""

    active: int = Field(description="Liczba workerów z aktywnym tętnem")
    items: list[Worker] = Field(description="Workery z odczytanym tętnem")


class QueueInfo(BaseModel):
    """Stan kolejki zadań (kontrakt E3-6a §3)."""

    queued: int = Field(description="Zadania oczekujące na pobranie")
    running: int = Field(description="Zadania w trakcie realizacji")
    dead: int = Field(description="Zadania porzucone po wyczerpaniu prób")


class Stats(BaseModel):
    """Statystyki systemu WD: wersja, sondy, workery i kolejka (kontrakt E3-6a §3)."""

    version: str = Field(description="Wersja aplikacji")
    database: Probe = Field(description="Sonda bazy danych")
    storage: Probe = Field(description="Sonda magazynu plików")
    workers: WorkersInfo = Field(description="Workery i ich tętna")
    queue: QueueInfo = Field(description="Stan kolejki zadań")
