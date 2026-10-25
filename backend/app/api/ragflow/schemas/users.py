"""Modele OpenAPI users (C1, C3, C10): profil /users/me, domyślne modele, żądania."""

from typing import Any

from pydantic import ConfigDict

from app.api.ragflow.schemas.common import RequestModel, ResponseModel


def _drop_property_defaults(schema: dict[str, Any]) -> None:
    """Usuwa ``default`` z właściwości JSON Schema (kontrakt E3-6a §3, T5).

    ``openapi-typescript`` (``defaultNonNullable``) traktuje pole z ``default`` jako wymagane,
    więc generowanym typem ``UpdateMeRequest`` rządzi brak ``default``, nie brak ``required``.
    Zachowanie modelu (``= None``) zostaje bez zmian — to tylko dokumentacja.
    """
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for field in properties.values():
            if isinstance(field, dict):
                field.pop("default", None)


class DefaultModels(ResponseModel):
    """Domyślne modele instancji (C10): klucze DefaultModelsService.get, wartości str."""

    llm_id: str
    embd_id: str
    img2txt_id: str
    rerank_id: str
    asr_id: str
    tts_id: str


class RegisterRequest(RequestModel):
    """Ciało users_register; brak pola → code 101 (handler rzuca, ciało wymagane)."""

    nickname: str
    email: str
    password: str


class UpdateMeRequest(RequestModel):
    """Ciało users_me_update: hasła z patch_me + PROFILE_FIELDS; puste ciało → code 0."""

    # ``json_schema_extra`` usuwa ``default`` z właściwości, żeby pola były opcjonalne
    # w ``schema.gen.ts`` (kontrakt E3-6a §3, T5); model zachowuje ``= None``.
    model_config = ConfigDict(json_schema_extra=_drop_property_defaults)

    password: str | None = None
    new_password: str | None = None
    nickname: str | None = None
    avatar: str | None = None
    language: str | None = None
    timezone: str | None = None


class UpdateDefaultModelsRequest(RequestModel):
    """Ciało users_me_models_update: klucze FIELD_TYPES; puste ciało → code 0 (get())."""

    llm_id: str | None = None
    embd_id: str | None = None
    img2txt_id: str | None = None
    rerank_id: str | None = None


REQUEST_MODELS: tuple[type[RequestModel], ...] = (
    RegisterRequest,
    UpdateMeRequest,
    UpdateDefaultModelsRequest,
)
