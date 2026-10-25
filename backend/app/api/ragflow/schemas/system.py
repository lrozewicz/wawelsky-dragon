"""Modele OpenAPI system (C1, C3): config publiczny, zdrowie, status, statystyki, klucz API (C9)."""

from typing import Any

from app.api.ragflow.schemas.common import RequestModel, ResponseModel

# Trasy system nie mają ciał JSON (C1) — krotka pusta.
REQUEST_MODELS: tuple[type[RequestModel], ...] = ()


class SystemConfig(ResponseModel):
    """Data system_config (07 §3.4, złoto system--03.json) — dwie flagi publiczne instancji.

    registerEnabled jako liczba (upstream REGISTER_ENABLED = 1/0), nie bool.
    """

    registerEnabled: int
    disablePasswordLogin: bool


class Language(ResponseModel):
    """Data /language (upstream v0.27.2 system_api.py:66) — backend w Pythonie."""

    language: str


class SystemHealthz(ResponseModel):
    """Surowe ciało /system/healthz (bez koperty; złoto system--04.json)."""

    db: str
    doc_engine: str
    redis: str
    status: str
    storage: str


class DatabaseProbe(ResponseModel):
    """Blok database w /system/status (upstream v0.27.2 system_api.py:112)."""

    database: str
    status: str
    elapsed: str


class DocEngineProbe(ResponseModel):
    """Blok doc_engine w /system/status — 1:1 z sondą Elasticsearch upstreamu."""

    type: str
    status: str
    cluster_name: str
    active_primary_shards: int
    active_shards: int
    active_shards_percent_as_number: float
    delayed_unassigned_shards: int
    initializing_shards: int
    number_of_data_nodes: int
    number_of_in_flight_fetch: int
    number_of_nodes: int
    number_of_pending_tasks: int
    relocating_shards: int
    task_max_waiting_in_queue_millis: int
    timed_out: bool
    unassigned_shards: int
    elapsed: str


class RedisProbe(ResponseModel):
    """Blok redis w /system/status (upstream v0.27.2 system_api.py:124)."""

    status: str
    elapsed: str


class StorageProbe(ResponseModel):
    """Blok storage w /system/status (upstream v0.27.2 system_api.py:104)."""

    storage: str
    status: str
    elapsed: str


class SystemStatus(ResponseModel):
    """Data /system/status (upstream system_api.py:73); heartbeaty workerów z K5 §2.6."""

    database: DatabaseProbe
    doc_engine: DocEngineProbe
    redis: RedisProbe
    storage: StorageProbe
    task_executor_heartbeats: dict[str, list[dict[str, Any]]]


class SystemStats(ResponseModel):
    """Data /system/stats (upstream stats_api.py:24) — serie statystyk konwersacji API."""

    pv: list[Any]
    uv: list[Any]
    speed: list[Any]
    tokens: list[Any]
    round: list[Any]
    thumb_up: list[Any]


class ApiToken(ResponseModel):
    """Klucz API z listy (token_dict, 07 §5.2); beta = 32 znaki tokenu (upstream).

    ``name`` (K20 §1) to nazwa zapisana przy tworzeniu; ``None`` dla kluczy bez nazwy.
    """

    token: str
    tenant_id: str
    name: str | None
    dialog_id: str | None
    source: str | None
    beta: str
    create_time: int
    create_date: str
    update_time: int
    update_date: str


class CreatedApiToken(ResponseModel):
    """Świeżo utworzony klucz API (created_token_dict, złoto system--08.json).

    ``name`` (K20 §1) odbija nazwę podaną przy tworzeniu (po przycięciu); ``None`` bez nazwy.
    """

    token: str
    tenant_id: str
    name: str | None
    beta: str
    create_time: int
    create_date: str
    update_time: None
    update_date: None
