"""Modele OpenAPI datasetów (odpowiedzi C3, żądania) — kształty v0.27.2."""

from typing import Any, Literal

from app.api.ragflow.normalize.datasets import (
    CreateDataset,
    DeleteDatasets,
    UpdateDataset,
)
from app.api.ragflow.schemas.common import RequestModel, ResponseModel


class Dataset(ResponseModel):
    """Podstawa 46 kluczy złota POST /datasets (present.datasets.dataset, C3)."""

    avatar: str | None
    chunk_count: int
    chunk_method: str
    create_date: str
    create_time: int
    created_by: str
    description: str | None
    document_count: int
    embedding_model: str
    id: str
    language: str
    name: str
    pagerank: int
    parser_config: dict[str, Any]
    permission: Literal["me", "team"]
    pipeline_id: None
    similarity_threshold: float
    status: str
    tenant_embd_id: None
    tenant_id: str
    token_num: int
    update_date: str
    update_time: int
    vector_similarity_weight: float
    graphrag_task_id: None
    graphrag_task_finish_at: None
    mindmap_task_id: None
    mindmap_task_finish_at: None
    raptor_task_id: None
    raptor_task_finish_at: None
    session_essence_task_id: None
    session_essence_task_finish_at: None
    session_graph_task_id: None
    session_graph_task_finish_at: None
    skill_task_id: None
    skill_task_finish_at: None
    structure_graph_task_id: None
    structure_graph_task_finish_at: None
    structure_mindmap_task_id: None
    structure_mindmap_task_finish_at: None
    structure_task_id: None
    structure_task_finish_at: None
    timeline_task_id: None
    timeline_task_finish_at: None
    wiki_task_id: None
    wiki_task_finish_at: None


class DatasetDetail(Dataset):
    """Kształt GET/PUT /datasets/{id}: dataset() + connectors (C3 p. 4).

    ``size`` (suma rozmiarów dokumentów) występuje tylko w GET /datasets/{id}
    (upstream DAS:276); PUT zwraca sam ``dataset_updated`` (DAS:405-407) — stąd
    pole opcjonalne.
    """

    connectors: list[Any]
    size: int | None = None


class DatasetListed(Dataset):
    """Element listy GET /datasets: dataset() + 3 pola właściciela/modelu (C3 p. 4)."""

    nickname: str
    tenant_avatar: None
    embedding_model_name: str


class DatasetListOk(ResponseModel):
    """Koperta GET /datasets: data + total_datasets (present i ok_result(total=), C3 p. 4)."""

    code: Literal[0]
    message: str
    data: list[DatasetListed]
    total_datasets: int


class SuccessCount(ResponseModel):
    """data handlerów zwracających {"success_count"} (DELETE /datasets, parse; C3 p. 4)."""

    success_count: int


class CreateDatasetRequest(RequestModel, CreateDataset):
    """Ciało POST /datasets (normalize.datasets.CreateDataset; pola odziedziczone)."""


class UpdateDatasetRequest(RequestModel, UpdateDataset):
    """Ciało PUT /datasets/{id} (normalize.datasets.UpdateDataset; pola odziedziczone)."""


class DeleteDatasetsRequest(RequestModel, DeleteDatasets):
    """Ciało DELETE /datasets (normalize.datasets.DeleteDatasets; pola odziedziczone)."""


REQUEST_MODELS: tuple[type[RequestModel], ...] = (
    CreateDatasetRequest,
    UpdateDatasetRequest,
    DeleteDatasetsRequest,
)
