"""Modele pydantic tras użytkowników WD (kontrakt WP E3-6a §3).

Model konta nie ma pól wrażliwych (``password_hash``, ``token_version``, ``oidc_sub``,
``is_service``) — zbiór kluczy odpowiedzi jest dokładnie ten z kontraktu §3. Pola sekretów
(``password``, ``new_password``) to zwykłe ``str`` z ``min_length=1`` — po K3 §5 handler
walidacji nie odsyła ``input`` w treści błędu.

Nazwa klasy to ``WdUser``, choć kontrakt §3 nazywa model ``User``: komponent OpenAPI o tej
samej nazwie co model RAGFlow (``app/api/ragflow/schemas/auth.py::User``, używany przez
``/api/v1/users/me``) koliduje, a pydantic rozstrzyga kolizję, rozwijając **oba** komponenty
do nazw z modułem — przez co ``frontend/src/features/auth/authState.ts`` (``schemas["User"]``)
przestaje się kompilować, a plików frontendu poza ``schema.gen.ts`` nie zmieniamy.
"""

from pydantic import BaseModel, Field, StrictBool


class WdUser(BaseModel):
    """Konto użytkownika w odpowiedziach tras WD (kontrakt §3)."""

    id: str = Field(description="Identyfikator użytkownika")
    email: str = Field(description="Adres e-mail konta")
    nickname: str = Field(description="Nazwa wyświetlana")
    auth_source: str = Field(description="Źródło uwierzytelnienia (local, keycloak)")
    is_superuser: bool = Field(description="Czy konto jest administratorem")
    is_active: bool = Field(description="Czy konto jest aktywne")
    language: str = Field(description="Język interfejsu")
    timezone: str | None = Field(description="Strefa czasowa albo null")
    avatar: str | None = Field(description="Awatar albo null")
    last_login_at: str | None = Field(description="Czas ostatniego logowania (ISO 8601) albo null")
    created_at: str | None = Field(description="Czas utworzenia konta (ISO 8601) albo null")
    updated_at: str | None = Field(description="Czas ostatniej zmiany (ISO 8601) albo null")


class UserCreateRequest(BaseModel):
    """Ciało ``POST /api/wd/v1/users`` (kontrakt §3)."""

    email: str = Field(min_length=1, max_length=254, description="Adres e-mail nowego konta")
    password: str | None = Field(
        default=None, min_length=1, description="Hasło początkowe (opcjonalne)"
    )
    nickname: str | None = Field(default=None, description="Nazwa wyświetlana (opcjonalna)")
    is_superuser: StrictBool = Field(default=False, description="Czy konto ma być administratorem")


class UserUpdateRequest(BaseModel):
    """Ciało ``PATCH /api/wd/v1/users/{user_id}``; brak pola oznacza brak zmiany (kontrakt §3)."""

    nickname: str | None = Field(default=None, description="Nowa nazwa wyświetlana")
    is_superuser: StrictBool | None = Field(
        default=None, description="Nowa rola administratora (brak = bez zmian)"
    )
    is_active: StrictBool | None = Field(
        default=None, description="Nowy stan aktywności (brak = bez zmian)"
    )


class PasswordRequest(BaseModel):
    """Ciało ``POST /api/wd/v1/users/{user_id}/password`` (kontrakt §3)."""

    new_password: str = Field(min_length=1, description="Nowe hasło konta")
