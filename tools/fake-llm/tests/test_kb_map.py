"""Testy reguły pełnej mapy bazy wiedzy w fake-llm (K21 §6a): treść, priorytet, scenariusze."""

import json
from typing import Any

import httpx

HTTP_OK = 200
CHAT_MODEL = "fake-chat"
THINK_MODEL = "fake-chat-think"
STRICT_MODEL = "fake-chat-strict"
MAP_HEADER = (
    "## Zawartość bazy wiedzy (pełna mapa)\n"
    "Użytkownik pyta o zawartość bazy. Wymień wszystkie dokumenty i ich działy z poniższej "
    "listy — nie ograniczaj się do fragmentów wiedzy."
)
SYS_KB = "Kontekst:\nID: 1\nPierwszy fragment o umowie najmu.\n"


def _body(model: str, messages: list[dict[str, Any]], stream: bool = False) -> dict[str, Any]:
    return {"model": model, "messages": messages, "stream": stream}


def _user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text}


def _system(text: str) -> dict[str, Any]:
    return {"role": "system", "content": text}


async def test_map_answer_brief_example(client: httpx.AsyncClient) -> None:
    """Wiersz tabeli briefu: dokument z sufiksem bazy, dział z sufiksem strony i podrzędny."""
    system = MAP_HEADER + "\n### a.pdf [GUS]\n- DZIAŁ I GEOGRAFIA (s. 5)\n  - Podrzędny\n- DZIAŁ II"
    response = await client.post(
        "/v1/chat/completions",
        json=_body(CHAT_MODEL, [_system(system), _user("co zawiera twoja baza wiedzy?")]),
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "Baza zawiera: a.pdf. Działy: DZIAŁ I GEOGRAFIA; DZIAŁ II"


async def test_map_two_documents_with_and_without_dataset(client: httpx.AsyncClient) -> None:
    """Dwa dokumenty; sufiks ` [nazwa bazy]` ścinany (SC-V13-02 k4), dział podrzędny pomijany."""
    system = MAP_HEADER + (
        "\n### pierwszy.pdf [Mix]\n"
        "- DZIAŁ A (s. 1)\n"
        "  - podrzędny A (s. 2)\n"
        "- DZIAŁ B\n"
        "### drugi.docx\n"
        "- Rozdział I (s. 9)\n"
        "(brak spisu treści)\n"
    )
    response = await client.post(
        "/v1/chat/completions",
        json=_body(CHAT_MODEL, [_system(system), _user("jakie dokumenty masz w bazie?")]),
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "Baza zawiera: pierwszy.pdf; drugi.docx. Działy: DZIAŁ A; DZIAŁ B; Rozdział I"


async def test_map_long_list_of_sections(client: httpx.AsyncClient) -> None:
    """28 działów najwyższego poziomu — wszystkie trafiają do odpowiedzi."""
    titles = [f"DZIAŁ {index}" for index in range(1, 29)]
    body = "\n".join(f"- {title} (s. {index})" for index, title in enumerate(titles, start=1))
    system = f"{MAP_HEADER}\n### rocznik.pdf [GUS]\n{body}"
    response = await client.post(
        "/v1/chat/completions",
        json=_body(CHAT_MODEL, [_system(system), _user("co zawiera twoja baza wiedzy?")]),
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert "Baza zawiera: rocznik.pdf. Działy: " + "; ".join(titles) in content
    assert "(s. " not in content


async def test_map_skips_truncation_line(client: httpx.AsyncClient) -> None:
    """Linia przycięcia limitu mapy nie jest działem (K21 §4 p. 2)."""
    system = MAP_HEADER + "\n### a.pdf\n- DZIAŁ I\n- … i 3 kolejnych dokumentów"
    response = await client.post(
        "/v1/chat/completions",
        json=_body(CHAT_MODEL, [_system(system), _user("czym jest baza?")]),
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "Baza zawiera: a.pdf. Działy: DZIAŁ I"


async def test_map_beats_knowledge_block(client: httpx.AsyncClient) -> None:
    """Ta sama wiadomość system z mapą i blokiem wiedzy — mapa ma pierwszeństwo (§6a)."""
    system = SYS_KB + MAP_HEADER + "\n### a.pdf\n- DZIAŁ I\n"
    response = await client.post(
        "/v1/chat/completions",
        json=_body(CHAT_MODEL, [_system(system), _user("co jest w bazie")]),
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "Baza zawiera: a.pdf. Działy: DZIAŁ I"
    assert "[ID:" not in content


async def test_map_section_scope_excludes_surrounding_lists(client: httpx.AsyncClient) -> None:
    """Linie `- `/`### ` poza sekcją mapy nie są dokumentami ani działami (§6a).

    Blok wiedzy PRZED mapą z własną listą `- …` oraz nagłówek `## ` PO mapie z własnym
    `### `/`- ` — zbierane są wyłącznie linie między nagłówkiem mapy a następnym `## `.
    """
    system = (
        "Kontekst:\nID: 1\nWykaz przed mapą:\n- pozycja bloku wiedzy\n"
        + MAP_HEADER
        + "\n### a.pdf\n- DZIAŁ I\n"
        "## Dalsze instrukcje\n"
        "### z.pdf\n"
        "- nie dział\n"
    )
    response = await client.post(
        "/v1/chat/completions",
        json=_body(CHAT_MODEL, [_system(system), _user("co zawiera twoja baza wiedzy?")]),
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "Baza zawiera: a.pdf. Działy: DZIAŁ I"


async def test_map_header_alone_question_uses_map(client: httpx.AsyncClient) -> None:
    """Pytanie o bazę + sama mapa bez dokumentów → pusta formuła (linia nagłówka wystarcza)."""
    response = await client.post(
        "/v1/chat/completions",
        json=_body(CHAT_MODEL, [_system(MAP_HEADER), _user("what documents do you have?")]),
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "Baza zawiera: . Działy: "


async def test_no_map_falls_back_to_knowledge_block(client: httpx.AsyncClient) -> None:
    """Bez linii pełnej mapy działa dotychczasowa reguła bloków wiedzy."""
    response = await client.post(
        "/v1/chat/completions",
        json=_body(CHAT_MODEL, [_system(SYS_KB), _user("pytanie")]),
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "Na podstawie źródeł: Pierwszy fragment o umowie najmu. [ID:1]"


async def test_catalog_header_does_not_change_behavior(client: httpx.AsyncClient) -> None:
    """Katalog §3 (nagłówek bez „(pełna mapa)”) nie zmienia zachowania fake-llm (§6a)."""
    catalog = (
        "Kontekst:\nID: 1\nPierwszy fragment o umowie najmu.\n"
        "## Zawartość bazy wiedzy\n"
        "Masz dostęp do następujących dokumentów (2):\n"
        "- a.pdf [GUS] — działy: DZIAŁ I GEOGRAFIA\n"
        "- b.docx\n"
    )
    response = await client.post(
        "/v1/chat/completions", json=_body(CHAT_MODEL, [_system(catalog), _user("pytanie")])
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content.startswith("Na podstawie źródeł: ")
    assert content.endswith("[ID:1]")
    assert "Baza zawiera: " not in content


async def test_think_model_keeps_think_prefix(client: httpx.AsyncClient) -> None:
    """`fake-chat-think` zachowuje blok myślenia także przy mapie (K21 §6a)."""
    system = MAP_HEADER + "\n### a.pdf [GUS]\n- DZIAŁ I (s. 5)\n- DZIAŁ II\n"
    reference = await client.post("/v1/chat/completions", json=_body(THINK_MODEL, [_user("x")]))
    think_prefix = reference.json()["choices"][0]["message"]["content"][
        : -len("Odpowiedź testowa: x")
    ]
    response = await client.post(
        "/v1/chat/completions",
        json=_body(THINK_MODEL, [_system(system), _user("co jest w bazie")]),
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == think_prefix + "Baza zawiera: a.pdf. Działy: DZIAŁ I; DZIAŁ II"


async def test_strict_model_uses_same_map_rule(client: httpx.AsyncClient) -> None:
    """`fake-chat-strict` odpowiada z mapy tak samo jak `fake-chat`."""
    system = MAP_HEADER + "\n### a.pdf\n- DZIAŁ I\n"
    chat = await client.post(
        "/v1/chat/completions", json=_body(CHAT_MODEL, [_system(system), _user("co jest w bazie")])
    )
    strict = await client.post(
        "/v1/chat/completions",
        json=_body(STRICT_MODEL, [_system(system), _user("co jest w bazie")]),
    )
    assert strict.status_code == HTTP_OK
    assert (
        strict.json()["choices"][0]["message"]["content"]
        == (chat.json()["choices"][0]["message"]["content"])
    )


async def test_map_streaming(client: httpx.AsyncClient) -> None:
    """Mapa działa także w strumieniu — złożone delty dają tę samą treść co JSON."""
    system = MAP_HEADER + "\n### a.pdf [GUS]\n- DZIAŁ I (s. 5)\n- DZIAŁ II\n"
    question = "jakie dokumenty masz w bazie?"
    streamed = await client.post(
        "/v1/chat/completions",
        json=_body(CHAT_MODEL, [_system(system), _user(question)], stream=True),
    )
    assert streamed.status_code == HTTP_OK
    frames = [frame for frame in streamed.text.split("\n\n") if frame]
    chunks = [json.loads(frame[len("data: ") :]) for frame in frames[:-1]]
    deltas = [chunk["choices"][0]["delta"].get("content") for chunk in chunks[1:-1]]
    non_stream = await client.post(
        "/v1/chat/completions", json=_body(CHAT_MODEL, [_system(system), _user(question)])
    )
    assert (
        "".join(delta for delta in deltas if delta)
        == (non_stream.json()["choices"][0]["message"]["content"])
    )


async def test_scenario_still_applies_with_map(client: httpx.AsyncClient) -> None:
    """`X-Fake-Scenario` działa dalej: `empty` opróżnia, `no_citations` nie zmienia mapy bez ID."""
    system = MAP_HEADER + "\n### a.pdf\n- DZIAŁ I\n"
    messages = [_system(system), _user("co jest w bazie")]
    empty = await client.post(
        "/v1/chat/completions",
        json=_body(CHAT_MODEL, messages),
        headers={"X-Fake-Scenario": "empty"},
    )
    assert empty.json()["choices"][0]["message"]["content"] == ""
    no_citations = await client.post(
        "/v1/chat/completions",
        json=_body(CHAT_MODEL, messages),
        headers={"X-Fake-Scenario": "no_citations"},
    )
    assert no_citations.json()["choices"][0]["message"]["content"] == (
        "Baza zawiera: a.pdf. Działy: DZIAŁ I"
    )
