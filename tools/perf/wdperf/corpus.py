"""Deterministyczny generator korpusu: tekstów, nazw dokumentów, zapytań i wektorów.

Czyste funkcje, bez I/O i bez zależności poza stdlib. Ten sam `(seed, index)` daje
zawsze ten sam wynik, co pozwala odtworzyć korpus bez zapisywania go na dysku.
"""

import math
import random
import struct

SEED_DEFAULT: int = 20261001
CHUNKS_PER_DOC: int = 100

# 20 tematów po 20 wyrazów (razem 400) + wyrazy wspólne (spójniki i przyimki).
# Temat chunka `index` to `TOPICS[index % len(TOPICS)]`.
# Dane słownika trzymamy w kolumnach (czytelność); ruff format je pomija.
# fmt: off
TOPICS: tuple[tuple[str, ...], ...] = (
    (
        "słońce", "chmura", "deszcz", "wiatr", "burza", "śnieg", "mróz", "upał",
        "mgła", "tęcza", "grad", "szron", "wichura", "chłodny", "ciepły",
        "pochmurno", "słonecznie", "wilgotność", "ciśnienie", "prognoza",
    ),
    (
        "las", "łąka", "góra", "rzeka", "jezioro", "drzewo", "kwiat", "trawa",
        "liść", "korzeń", "gałąź", "ptak", "owad", "kamień", "dolina",
        "wzgórze", "strumień", "bagno", "polana", "mech",
    ),
    (
        "komputer", "program", "serwer", "dane", "algorytm", "sieć", "procesor",
        "pamięć", "ekran", "klawiatura", "system", "aplikacja", "kod", "baza",
        "łączność", "robot", "czujnik", "kabel", "moduł", "sygnał",
    ),
    (
        "lekarz", "pacjent", "choroba", "zdrowie", "lek", "szpital", "badanie",
        "diagnoza", "objaw", "terapia", "wirus", "bakteria", "szczepienie",
        "rana", "ból", "nerw", "krew", "serce", "płuco", "kość",
    ),
    (
        "piłka", "mecz", "zawodnik", "drużyna", "trening", "bieganie",
        "siłownia", "rower", "pływanie", "stadion", "sędzia", "bramka",
        "rekord", "medal", "olimpiada", "kosz", "siatka", "tenis", "maraton",
        "rozgrzewka",
    ),
    (
        "potrawa", "zupa", "pieczywo", "mięso", "warzywo", "owoc", "przyprawa",
        "cukier", "mąka", "masło", "ser", "jajko", "ciasto", "piekarnik",
        "garnek", "łyżka", "widelec", "talerz", "smak", "przepis",
    ),
    (
        "podróż", "pociąg", "samolot", "hotel", "walizka", "bilet", "mapa",
        "lotnisko", "dworzec", "wycieczka", "przewodnik", "granica", "paszport",
        "plaża", "góry", "nocleg", "autokar", "trasa", "kierunek", "przygoda",
    ),
    (
        "melodia", "rytm", "orkiestra", "gitara", "fortepian", "skrzypce",
        "nuta", "akord", "koncert", "śpiew", "chór", "bęben", "trąbka", "flet",
        "zespół", "piosenka", "dźwięk", "rytmiczny", "kompozytor", "słuchacz",
    ),
    (
        "książka", "powieść", "autor", "wiersz", "bohater", "rozdział",
        "opowiadanie", "wydanie", "biblioteka", "czytelnik", "proza", "dramat",
        "metafora", "fabuła", "narracja", "tytuł", "strona", "tekst", "pisarz",
        "gatunek",
    ),
    (
        "wiek", "wojna", "król", "imperium", "rewolucja", "traktat", "zamek",
        "rycerz", "dynastia", "kronika", "powstanie", "granica", "epoka",
        "źródło", "wykopalisko", "muzeum", "pamiątka", "dawny", "średniowiecze",
        "nowożytność",
    ),
    (
        "ustawa", "sąd", "sędzia", "adwokat", "wyrok", "przepis", "umowa",
        "kodeks", "paragraf", "wniosek", "apelacja", "dowód", "świadek", "kara",
        "grzywna", "prawo", "obowiązek", "konstytucja", "rozprawa", "orzeczenie",
    ),
    (
        "rynek", "cena", "podatek", "budżet", "inwestycja", "zysk", "strata",
        "bank", "kredyt", "waluta", "handel", "eksport", "import", "gospodarka",
        "firma", "praca", "płaca", "oszczędność", "dług", "inflacja",
    ),
    (
        "szkoła", "uczeń", "nauczyciel", "lekcja", "egzamin", "ocena",
        "podręcznik", "zadanie", "klasa", "wiedza", "nauka", "wykład", "student",
        "uczelnia", "dyplom", "ćwiczenie", "matura", "świadectwo", "temat",
        "talent",
    ),
    (
        "samochód", "silnik", "koło", "droga", "kierowca", "paliwo", "hamulec",
        "skrzynia", "opona", "garaż", "warsztat", "zderzak", "reflektor",
        "prędkość", "mandat", "autostrada", "parking", "przyczepa", "benzyna",
        "akumulator",
    ),
    (
        "dom", "ściana", "dach", "cegła", "beton", "fundament", "okno", "drzwi",
        "schody", "piętro", "budowa", "dźwig", "rusztowanie", "zaprawa",
        "izolacja", "komin", "podłoga", "sufit", "balkon", "elewacja",
    ),
    (
        "pole", "zboże", "pszenica", "żyto", "traktor", "plon", "gleba", "nawóz",
        "siew", "żniwa", "kombajn", "obora", "krowa", "owca", "kurczak",
        "mleko", "wieś", "gospodarstwo", "siano", "pastwisko",
    ),
    (
        "gwiazda", "planeta", "księżyc", "rakieta", "orbita", "galaktyka",
        "teleskop", "astronauta", "satelita", "próżnia", "meteoryt", "kometa",
        "mgławica", "wszechświat", "grawitacja", "stacja", "lot", "misja",
        "sonda", "niebo",
    ),
    (
        "morze", "fala", "ryba", "rekin", "wieloryb", "rafa", "głębina", "prąd",
        "port", "statek", "żagiel", "kotwica", "latarnia", "brzeg", "piasek",
        "muszla", "krab", "delfin", "sztorm", "wir",
    ),
    (
        "obraz", "malarz", "rzeźba", "galeria", "płótno", "farba", "pędzel",
        "wystawa", "kolor", "forma", "dzieło", "artysta", "szkic", "portret",
        "pejzaż", "abstrakcja", "kompozycja", "rama", "estetyka", "wernisaż",
    ),
    (
        "pies", "kot", "koń", "wilk", "lis", "niedźwiedź", "sarna", "jeleń",
        "wiewiórka", "mysz", "sokół", "sowa", "wąż", "żaba", "pszczoła",
        "motyl", "pająk", "borsuk", "łoś", "zając",
    ),
)

# Wyrazy wspólne (spójniki i przyimki) — mieszane z wyrazami tematycznymi.
COMMON_WORDS: tuple[str, ...] = (
    "i", "oraz", "ale", "że", "się", "jest", "być", "tak", "jak", "nie",
    "to", "na", "do", "od", "w", "z", "pod", "nad", "dla", "przez",
)
# fmt: on

# Pełny słownik: 400 wyrazów tematycznych + wyrazy wspólne.
WORDS: tuple[str, ...] = tuple(w for topic in TOPICS for w in topic) + COMMON_WORDS

_TEXT_WORDS: int = 80
_TEXT_TOPIC_RATIO: float = 0.9


def _rng(seed: int, index: int, salt: int = 0) -> random.Random:
    """Deterministyczny RNG dla pary `(seed, index)` (plus sól dla różnych zastosowań)."""
    return random.Random(seed * 1_000_003 + index * 7_919 + salt)


def chunk_text(seed: int, index: int) -> str:
    """Tekst chunka `index` (~80 wyrazów, ok. 450-600 znaków)."""
    topic = TOPICS[index % len(TOPICS)]
    rng = _rng(seed, index)
    words = [
        rng.choice(topic) if rng.random() < _TEXT_TOPIC_RATIO else rng.choice(COMMON_WORDS)
        for _ in range(_TEXT_WORDS)
    ]
    return " ".join(words)


def doc_name(index: int) -> str:
    """Nazwa dokumentu dla `index`, np. `perf-doc-00042.txt`."""
    return f"perf-doc-{index:05d}.txt"


def queries(seed: int, n: int) -> list[str]:
    """`n` deterministycznych zapytań po 3-5 wyrazów ze słownika (mieszanka tematów)."""
    rng = _rng(seed, 0, salt=101)
    result: list[str] = []
    for _ in range(n):
        length = rng.randint(3, 5)
        words = [rng.choice(TOPICS[rng.randrange(len(TOPICS))]) for _ in range(length)]
        result.append(" ".join(words))
    return result


def vector_pool(seed: int, dim: int, size: int = 1024) -> list[bytes]:
    """`size` wektorów jednostkowych float32 LE (rozkład normalny, znormalizowane)."""
    rng = random.Random(seed + dim)
    pool: list[bytes] = []
    for _ in range(size):
        values = [rng.gauss(0.0, 1.0) for _ in range(dim)]
        norm = math.sqrt(sum(v * v for v in values))
        if norm == 0.0:
            norm = 1.0
        pool.append(struct.pack(f"<{dim}f", *(v / norm for v in values)))
    return pool


def chunk_vector(pool: list[bytes], seed: int, index: int) -> bytes:
    """Wektor z puli z nadpisanymi pierwszymi 4 floatami (unikalny dla `index`)."""
    base = bytearray(pool[index % len(pool)])
    rng = random.Random(hash((seed, index)))
    jitter = [rng.uniform(-0.05, 0.05) for _ in range(4)]
    struct.pack_into("<4f", base, 0, *jitter)
    return bytes(base)
