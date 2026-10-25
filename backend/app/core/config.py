"""Konfiguracja aplikacji — `Settings` wg K8 część A i kontraktu C1.

Moduł nie czyta env przy imporcie — `Settings()` dopiero w chwili konstrukcji.
"""

import os
import re
from typing import Literal, Self

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SECRET_KEY_MIN_BYTES = 32


class Settings(BaseSettings):
    """Zmienne `WD_*` — pola w kolejności tabeli K8 część A, typy i domyślne dosłownie z tabeli."""

    model_config = SettingsConfigDict(env_prefix="WD_", extra="ignore")

    env: Literal["dev", "test", "prod"] = "prod"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    public_base_url: str = "http://localhost:8080"
    cors_origins: str = ""
    # Flaga Secure cookie sesji (K8 poprawka 2026-10-04b p. 2): auto = wg X-Forwarded-Proto w prod.
    cookie_secure: Literal["auto", "true", "false"] = "auto"
    api_workers: int = 2
    max_upload_mb: int = 1024
    max_uncompressed_mb: int = 2048
    max_archive_ratio: int = 100
    # Limit rozmiaru paczki `.wdkb.zip` (eksport i import) oraz sumy rozpakowanych wpisów (K19 §6).
    export_max_bytes: int = 2_147_483_648
    parse_timeout_s: int = Field(default=1800, ge=1)
    # Liczba procesów puli konwersji dokumentów workera (kontrakt C4; ~0,56 GB RSS/proces, E5-H2).
    parse_processes: int = Field(default_factory=lambda: min(4, os.cpu_count() or 1), ge=1)
    max_page_size: int = 1000
    db_host: str = "mariadb"
    db_port: int = 3306
    db_user: str = "wawelsky"
    db_password: SecretStr = SecretStr("")
    db_name: str = "wawelsky"
    db_pool_size: int = 10
    db_pool_overflow: int = 10
    db_echo: bool = False
    storage_root: str = "/data"
    secret_key: SecretStr = SecretStr("")
    crypto_key: SecretStr = SecretStr("")
    access_token_ttl_min: int = 15
    refresh_token_ttl_days: int = 14
    legacy_token_ttl_days: int = 30
    api_key_prefix: str = "ragflow-"
    hub_compat_api_secret: SecretStr = SecretStr("")
    hub_compat_routes: bool = True
    register_enabled: bool = False
    password_login_enabled: bool = True
    admin_email: str = ""
    admin_password: SecretStr = SecretStr("")
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: SecretStr = SecretStr("")
    oidc_audience: str = ""
    oidc_admin_roles: str = ""
    oidc_admin_groups: str = ""
    oidc_auto_register: bool = True
    oidc_logout_redirect: str = ""
    api_compat_default: Literal["ragflow_0_27", "ragflow_0_24"] = "ragflow_0_27"
    user_delete_mode: Literal["transfer", "cascade"] = "transfer"
    user_delete_transfer_to: str = ""
    expose_prompt: bool = True
    posthoc_citations: bool = True
    # Katalog dokumentów w prompcie czatu (K21 §3): limit tokenów sekcji; 0 = katalog wyłączony.
    chat_kb_catalog_tokens: int = 1500
    # Pełna mapa bazy przy pytaniu o bazę (K21 §4): limit tokenów mapy; 0 = mapa wyłączona.
    chat_kb_map_tokens: int = 6000
    llm_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_default_chat: str = "openai/gpt-4.1-mini"
    llm_default_embedding: str = "openai/text-embedding-3-large"
    llm_default_rerank: str = ""
    llm_default_vlm: str = "openai/gpt-4.1-mini"
    llm_timeout_s: float = 120.0
    llm_max_retries: int = 3
    embed_batch_size: int = 64
    # Równoległość żądań w zadaniu, gdy model nie ma `extra.max_concurrency` (K8/C1, E5-H8b).
    vlm_concurrency: int = Field(default=3, ge=1, le=32)
    embed_concurrency: int = Field(default=4, ge=1, le=32)
    retrieval_fusion: Literal["weighted", "rrf"] = "weighted"
    min_vector_sim: float = 0.25
    min_rerank_score: float = 0.1
    worker_concurrency: int = 2
    worker_poll_s: float = 1.0
    task_heartbeat_s: int = 15
    task_stale_s: int = 120
    worker_enable_scheduler: bool = True
    # Odstęp przeglądu dokumentów bez profilu spisu, w sekundach (K21 §2 p. 4); 0 = wyłączony.
    outline_sweep_s: int = 600
    ocr_engine: Literal["none", "tesseract", "vlm"] = "vlm"
    ocr_langs: str = "pol+eng"
    rate_limit_login: str = "10/min"
    metrics_enabled: bool = False
    feature_agents: bool = False
    feature_memory: bool = False
    integrations_enabled: bool = True
    integrations_tick_seconds: int = Field(default=30, ge=1)
    integrations_stale_lock_minutes: int = Field(default=15, ge=1)
    integrations_wait_timeout: int = Field(default=600, ge=1)
    integrations_cancel_wait: int = Field(default=10, ge=0)
    integrations_events_retention_days: int = Field(default=90, ge=1)
    sp_delete_docs_on_integration_delete: bool = False
    sp_purge_excluded_containers: bool = False
    sp_link_cache_ttl_seconds: int = Field(default=3600, ge=0)
    sp_login_base_url: str = "https://login.microsoftonline.com"  # WD_SP_LOGIN_BASE_URL
    sp_graph_base_url: str = "https://graph.microsoft.com/v1.0"  # WD_SP_GRAPH_BASE_URL

    @field_validator("parse_processes", mode="before")
    @classmethod
    def _empty_parse_processes(cls, value: object) -> object:
        """Pusty `WD_PARSE_PROCESSES` lub None → domyślna liczba procesów (kontrakt C4)."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return min(4, os.cpu_count() or 1)
        return value

    @field_validator("sp_login_base_url", "sp_graph_base_url")
    @classmethod
    def _check_sp_base_url(cls, value: str, info: ValidationInfo) -> str:
        """URL bazowy SharePoint musi być absolutny http(s) i bez końcowego `/`."""
        if not value.startswith(("http://", "https://")) or value.endswith("/"):
            name = f"WD_{str(info.field_name).upper()}"
            raise ValueError(
                f"{name}: must start with http:// or https:// and must not end with '/'"
            )
        return value

    @field_validator("cors_origins")
    @classmethod
    def _reject_wildcard_cors(cls, value: str) -> str:
        """`*` na liście CORS odrzucone we wszystkich trybach."""
        if any(origin.strip() == "*" for origin in value.split(",")):
            raise ValueError("WD_CORS_ORIGINS: '*' is not allowed, list origins explicitly")
        return value

    @model_validator(mode="after")
    def _check_prod_secrets(self) -> Self:
        """W `prod` wymagane sekrety; w `dev`/`test` puste są dozwolone."""
        if self.env != "prod":
            return self
        problems: list[str] = []
        if not self.db_password.get_secret_value():
            problems.append("WD_DB_PASSWORD must be set")
        if len(self.secret_key.get_secret_value().encode()) < SECRET_KEY_MIN_BYTES:
            problems.append("WD_SECRET_KEY must be at least 32 bytes")
        if re.fullmatch(r"[0-9a-fA-F]{64}", self.crypto_key.get_secret_value()) is None:
            problems.append("WD_CRYPTO_KEY must be exactly 64 hex characters")
        if not self.llm_base_url:
            problems.append("WD_LLM_BASE_URL must be set")
        if problems:
            raise ValueError("invalid production settings: " + "; ".join(problems))
        return self
