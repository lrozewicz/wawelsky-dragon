"""Konfiguracja parsera datasetu — port modeli upstream ``validation_utils`` (VU:346-499).

Wydzielone z ``normalize.datasets`` (limit rozmiaru pliku); używane wyłącznie przez trasę
``POST /datasets``. Shape'y są wierne upstreamowi, bo komunikaty pydantic są częścią
odpowiedzi 101 (``test_parser_config_invalid``).
"""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints
from pydantic_core import PydanticCustomError

from app.api.ragflow.normalize.common import Command

# Upstream VU:350-355 (``RaptorConfig.prompt``) — domyślny prompt streszczenia RAPTOR.
DEFAULT_RAPTOR_PROMPT = (
    "Summarize the paragraphs below without inventing facts or changing numbers.\n"
    "Output exactly two parts in the same language as the source:\n"
    "1. First line: a concise title only.\n"
    "2. Following lines: a concise summary of the content.\n"
    "Do not output labels, Markdown headings, bullet points, or any other commentary.\n"
    "\n"
    "Paragraphs:\n"
    "{cluster_content}"
)
# Upstream VU:746 — maksymalny rozmiar zserializowanej konfiguracji parsera.
PARSER_CONFIG_MAX_CHARS = 65535


class RaptorConfig(Command):
    """``RaptorConfig`` upstream (VU:346-384) — strict, nadmiarowe klucze → 101."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    use_raptor: bool = False
    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = (
        DEFAULT_RAPTOR_PROMPT
    )
    max_token: int = Field(default=512, ge=512, le=2048)
    clustering_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    clustering_ratio: float = Field(default=0.5, ge=0.0, le=1.0)
    max_cluster: int = Field(default=64, ge=1, le=1024)
    random_seed: int = Field(default=0, ge=0)
    scope: Literal["file", "dataset"] = "file"
    auto_disable_for_structured_data: bool = True


class GraphragConfig(Command):
    """``GraphragConfig`` upstream (VU:387-404) — strict, nadmiarowe klucze → 101."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    use_graphrag: bool = False
    entity_types: list[str] = Field(
        default_factory=lambda: ["organization", "person", "geo", "event", "category"]
    )
    method: Literal["light", "general", "ner"] = "light"
    community: bool = False
    resolution: bool = False
    batch_chunk_token_size: int = Field(default=4096, ge=512, le=8196)
    retry_attempts: int = Field(default=2, ge=1, le=10)
    retry_backoff_seconds: float = Field(default=2.0, ge=0.0, le=600.0)
    retry_backoff_max_seconds: float = Field(default=60.0, ge=0.0, le=3600.0)
    build_subgraph_timeout_per_chunk_seconds: int = Field(default=300, ge=1, le=86400)
    build_subgraph_min_timeout_seconds: int = Field(default=600, ge=1, le=86400)
    merge_timeout_seconds: int = Field(default=180, ge=0, le=86400)
    resolution_timeout_seconds: int = Field(default=1800, ge=0, le=86400)
    community_timeout_seconds: int = Field(default=1800, ge=0, le=86400)
    lock_acquire_timeout_seconds: int = Field(default=600, ge=0, le=86400)


class ParentChildConfig(Command):
    """``ParentChildConfig`` upstream (VU:407-411) — strict."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    use_parent_child: bool = False
    children_delimiter: str = Field(default="\n", min_length=1)


class ParserConfig(Command):
    """``ParserConfig`` upstream (VU:433-499) — ``extra="allow"``, klucze nierozpoznane przechodzą.

    Instancję tej klasy dostaje usługa jako dict (``model_dump``) — jak upstream, gdzie
    ``parser_config`` idzie do zapisu już z domyślnymi ``raptor``/``graphrag``/``parent_child``
    (stąd ``test_parser_config_missing_raptor_and_graphrag``).
    """

    model_config = ConfigDict(extra="allow", strict=True, frozen=True)

    auto_keywords: int = Field(default=0, ge=0, le=32)
    auto_questions: int = Field(default=0, ge=0, le=10)
    chunk_token_num: int = Field(default=512, ge=1, le=2048)
    delimiter: str = Field(default="\n", min_length=1)
    graphrag: GraphragConfig = Field(default_factory=lambda: GraphragConfig(use_graphrag=False))
    html4excel: bool = False
    layout_recognize: str = "DeepDOC"
    parent_child: ParentChildConfig = Field(
        default_factory=lambda: ParentChildConfig(use_parent_child=False)
    )
    enable_children: bool = False
    children_delimiter: str = ""
    raptor: RaptorConfig = Field(default_factory=lambda: RaptorConfig(use_raptor=False))
    tag_kb_ids: list[str] = Field(default_factory=list)
    topn_tags: int = Field(default=1, ge=1, le=10)
    filename_embd_weight: float | None = Field(default=0.1, ge=0.0, le=1.0)
    task_page_size: int | None = Field(default=None, ge=1)
    pages: list[list[int]] | None = None
    compilation_template_group_id: list[str] = Field(default_factory=list)
    table_column_mode: Literal["auto", "manual"] | None = None
    table_column_roles: dict[str, Literal["indexing", "metadata", "both"]] | None = None
    table_column_names: list[str] | None = None


def check_parser_config_size(value: ParserConfig | None) -> ParserConfig | None:
    """Limit rozmiaru serializowanego ``parser_config`` (upstream ``…json_length``, VU:723-748)."""
    if value is None:
        return None
    serialized = value.model_dump_json()
    if len(serialized) > PARSER_CONFIG_MAX_CHARS:
        raise PydanticCustomError(
            "string_too_long",
            "Parser config exceeds size limit (max 65,535 characters). Current size: {actual}",
            {"actual": len(serialized)},
        )
    return value
