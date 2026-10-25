"""Typy wspólne etapów migracji (kontrakt §2, WP E4-6a)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.ids import IdGenerator
from app.core.timeutil import Clock
from app.storage.base import Storage
from app.tools.ragflow_migrate.model_map import ModelMap
from app.tools.ragflow_migrate.source import Source

Severity = Literal["info", "warning", "critical"]


@dataclass
class Issue:
    """Uwaga etapu; komunikat bez haseł, tokenów i kluczy."""

    severity: Severity
    code: str
    message: str
    ids: list[str]


@dataclass
class StageInventory:
    """Wynik ``plan``: co jest w źródle i co zostanie pominięte."""

    stage: str
    source_counts: dict[str, int]
    issues: list[Issue]
    not_migrated: dict[str, int]


@dataclass
class StageResult:
    """Wynik ``run``: liczniki zapisu w celu."""

    stage: str
    source_count: int
    created: int
    updated: int
    skipped: int
    target_count: int
    issues: list[Issue]


@dataclass
class PhaseResult:
    """Wynik jednej fazy etapu wielofazowego (kontrakt E4-6b1 §5)."""

    source_count: int
    created: int
    updated: int
    skipped: int
    target_count: int
    issues: list[Issue]


@dataclass
class RunContext:
    """Zależności biegu migracji wspólne dla etapów."""

    model_map: ModelMap
    settings: Settings
    clock: Clock
    id_gen: IdGenerator
    shared: dict[str, Any]
    storage: Storage | None = None  # CLI: FilesystemStorage(Path(settings.storage_root))
    src_files_dir: Path | None = None  # --src-files-dir; układ DIR/<bucket>/<location>
    src_sp_crypto_key: SecretStr | None = None  # --src-sp-crypto-key; nigdy do logów/raportu
    dry_run: bool = False  # ustawia run_all(…, dry_run) na początku
    since_ms: int | None = None  # --since (ms UTC): etapy filtrują update_time przez rows_changed


class Stage(Protocol):
    """Etap migracji: ``plan`` nie pisze niczego, ``run`` pisze w podanej sesji."""

    name: str

    def plan(self, src: Source, ctx: RunContext) -> StageInventory: ...

    async def run(self, src: Source, session: AsyncSession, ctx: RunContext) -> StageResult: ...
