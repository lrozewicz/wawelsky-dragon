"""Modele OpenAPI tras /dify/retrieval (K6 §3-§4; brief OD p. 1, upstream v0.27.2).

Wyłącznie opisowe (K6 §1): kształty pól z ``normalize/dify.py`` i ``present/dify.py``
oraz z docstringu trasy upstreamu (``dify_retrieval_api.py:118-180``).
"""

from typing import Any

from pydantic import Field

from app.api.ragflow.schemas.common import RequestModel, ResponseModel


class DifyRetrievalSetting(RequestModel):
    """``retrieval_setting`` żądania (upstream :174-190)."""

    score_threshold: float = Field(default=0.0, description="Próg podobieństwa wyników")
    top_k: int = Field(default=1024, description="Liczba wyników do zwrócenia")


class DifyMetadataCondition(RequestModel):
    """``metadata_condition`` żądania — filtr dokumentów po metadanych (upstream :192-206)."""

    logic: str = Field(default="and", description="Sposób łączenia warunków: and | or")
    conditions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Warunki: name, comparison_operator, value",
    )


class DifyRetrievalRequest(RequestModel):
    """Ciało POST /dify/retrieval (upstream :164-206)."""

    knowledge_id: str = Field(description="Id bazy wiedzy (dataset) do przeszukania")
    query: str = Field(description="Treść zapytania")
    use_kg: bool = Field(
        default=False,
        description="Żądanie użycia grafu wiedzy — WD go nie ma (02-api §5.6), pole ignorowane",
    )
    retrieval_setting: DifyRetrievalSetting | None = Field(
        default=None, description="Konfiguracja retrievalu"
    )
    metadata_condition: DifyMetadataCondition | None = Field(
        default=None, description="Filtr metadanych dokumentów"
    )


class DifyRecord(ResponseModel):
    """Jeden rekord odpowiedzi (upstream :288)."""

    content: str = Field(description="Treść fragmentu")
    score: float = Field(description="Podobieństwo fragmentu")
    title: str = Field(description="Nazwa dokumentu")
    metadata: dict[str, Any] = Field(description="Metadane dokumentu + doc_id/document_id")


class DifyRecords(ResponseModel):
    """Ciało 200 POST/GET /dify/retrieval — surowe, bez koperty ``code`` (upstream :290)."""

    records: list[DifyRecord] = Field(description="Fragmenty spełniające zapytanie")


REQUEST_MODELS: tuple[type[RequestModel], ...] = (DifyRetrievalRequest,)
