# M5c — chunker i `html_to_blocks` (stan po E1-5, 2026-09-27)

## Co robi
`html_to_blocks` zamienia znormalizowany HTML (05 §7) na listę `Block`: nagłówki z breadcrumbem, akapity, listy, tabele z `TableData`, kod, figury, notatki,
sekcje stron/slajdów/arkuszy i pozycje w formacie RAGFlow. `chunk_blocks` to czysta domena, która dzieli bloki na `ChunkDraft` zgodnie z semantyką metod RAGFlow
(naive, manual, book, laws, paper, presentation, one, picture, qa, table, email). Tokeny liczy wstrzyknięty `cfg.count_tokens`, więc domena nie importuje `app.llm`.

## Publiczny interfejs
Kontrakty: K5 §5 (typy i funkcje publiczne) + `work/wp/E1-5/CONTRACT.md` C1–C11 (pola wewnętrzne i dokładna semantyka).
```python
# backend/app/domain/chunking/__init__.py — __all__
Block, BlockKind, ChunkConfig, ChunkDraft, ChunkPreset, ChunkType, DelimiterSpec, TableData,
UnsupportedChunkMethod, DocumentTooLarge, chunk_blocks, parse_delimiter_field, preset_for

def preset_for(chunk_method: str) -> ChunkPreset                      # presets.py; tag/knowledge_graph/resume/audio/nieznane → UnsupportedChunkMethod (code 101)
def parse_delimiter_field(delimiter: str) -> DelimiterSpec           # delimiter.py; 1:1 z upstream rag/nlp/delim.py (v0.27.0)
def chunk_blocks(blocks: Sequence[Block], preset: ChunkPreset, cfg: ChunkConfig) -> list[ChunkDraft]   # chunker.py

# backend/app/parsing/blocks.py
def html_to_blocks(html: str) -> list[Block]                          # stdlib html.parser, bez nowych zależności
```
`ChunkPreset` (types.py) ma pola wewnętrzne `mode` (`general|presentation|one|qa|table`), `boundary_patterns`, `strip_page_furniture`.
`DelimiterSpec(delimiters: tuple[str, ...], has_wrapped: bool)`.
Błędy (errors.py): `UnsupportedChunkMethod(chunk_method)` — „chunk_method X is not supported by this server”; `DocumentTooLarge(tokens, max_tokens)` —
„document too large for 'one'” (obie to podklasy `ValidationFailed`, code 101).

Moduły wewnętrzne: `general.py` (`chunk_general`), `tables.py` (`row_text`, `table_text`, `chunk_table`), `finalize.py` (`merge_small`, `apply_overlap`, `finalize`,
`MIN_CHUNK_TOKENS=8`), `limits.py` (`SENTENCE_RE`, `split_sentences`, `split_to_limit`), `special.py` (`chunk_presentation`, `chunk_one`, `chunk_qa`,
`chunk_table_rows`, `strip_page_furniture`).

Użycie (E1-6):
```python
from app.domain.chunking import ChunkConfig, chunk_blocks, preset_for
from app.llm.tokens import count_tokens
from app.parsing.blocks import html_to_blocks

drafts = chunk_blocks(html_to_blocks(html), preset_for(chunk_method),
                      ChunkConfig(count_tokens=count_tokens, chunk_token_num=512, delimiter="\n"))
```

## Jak uruchomić i przetestować
- `cd backend && uv run --frozen pytest -q tests/unit/domain/chunking tests/unit/parsing/test_blocks.py --cov=app.domain.chunking --cov=app.parsing.blocks -p no:cacheprovider`
  → 195 passed; line-rate `app.domain.chunking` 0.9906, `app/parsing/blocks.py` 1.0 (special.py 0.976, tables.py 0.987, reszta 1.0).
- Testy delimitera: przykłady table-driven z upstream `test/unit_test/rag/test_delim.py` l. 64–259.
- Testy przekrojowe HTML → chunki: `tests/unit/domain/chunking/test_pipeline.py` (wszystkie presety, deterministyczność, tabela dzielona z `<thead>`).
- `lint-imports` → `Domena bez I/O KEPT`.

## Odstępstwa od docs/architecture/05-ingestion.md
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| §10.1 `Block.tokens`, §10.5 `ChunkDraft.image_key` | brak pól | K5 §5.1 (wiążący) ich nie ma; tokeny liczone w chunkerze, `image_id` slajdu — poza E1-5 |
| §10.3 p. 2 vs upstream `naive_merge` (`OVER_CAP`) | scalanie ze sprawdzaniem „suma ≤ limit” (odpowiednik `UNDER_CAP`) + podział akapitu po zdaniach/słowach | tekst 05 wiąże; upstream v0.27.0 domyślnie przekracza limit o jedną jednostkę |
| §10.3 p. 6 overlap | limit scalania = `chunk_token_num·(100−p)/100` (jak upstream l. 1218), overlap = sufiks całych zdań poprzednika ≤ ceil(p% tokenów); tylko do `text`, `html` bez zmian | granica zdania z 05; rezerwa jak upstream |
| §10.3 p. 7 „nigdy w środku słowa” | słowo dłuższe niż limit zostaje całe (może przekroczyć limit) | pierwszeństwo reguły „nie tnij słowa” |
| §10.3 p. 8 scalanie < 8 tokenów | z poprzednim, inaczej z następnym, nie z tabelą; pozycje małego chunku kasowane | jak RAGFlow |
| §10.4 `laws` | wzorce (`Art. n`, `§ n`, `Rozdział`, `Article n`, `Section n`, bez rozróżniania wielkości liter poza `§`) = granica chunku; akapit zostaje treścią, breadcrumb bez artykułu | minimum kodu; artykuł jest pierwszą linią chunku |
| §10.4 `paper` | tytuły sekcji (Abstract/Introduction/…, PL) jako granice (nie nagłówki breadcrumbu); stopki: numery stron + powtarzające się akapity (≤ 12 słów, ≥ 3 sekcje) | heurystyka bez layoutu |
| §10.4 `table` | tekst wiersza `"kol: wart; …"` (05), upstream v0.27.0 ma `"- kol: wart"` w liniach; role tylko przy `table_column_mode="manual"` (upstream table.py l. 520–524); wiersze z pustym tekstem pomijane | 05 wiąże |
| §10.4 `qa` | pary z tabel (także pierwszy wiersz — jak upstream Excel), potem `Q:/A:` (także `Question/Pytanie`, `Answer/Odpowiedź`), bez nich — nagłówek = pytanie; brak par → ścieżka naive; `chunk_type="qa"` | K5 `ChunkType` zawiera `qa` |
| §10.3 p. 5 `html4excel` | `False` → tekst tabeli `"kol: wart; …"` dla WSZYSTKICH tabel (nie tylko XLSX); `True` → `"a | b"` z powieloną linią nagłówka | chunker nie odróżnia źródła tabeli |
| §7 `colspan/rowspan` | komórki nie rozwijane | minimum kodu; dług niżej |

## Znane ograniczenia i dług
- `colspan`/`rowspan` nie są rozwijane — kolumny w `row_text` mogą się przesunąć przy scalonych komórkach.
- Overlap nie trafia do `html` (`content_llm`).
- Gdy breadcrumb sam przekracza `chunk_token_num`, budżet treści wynosi 1 token (chunki po jednym słowie + scalanie < 8) — limit przekroczony przez breadcrumb.
- `strip_page_furniture`: próg „≥ 3 sekcje” liczony po wszystkich sekcjach akapitów, nie tylko `page:*` (MINOR z review T4).
- Brak testu fallbacku „same nagłówki” wywołanego z trybu specjalnego (MINOR z review T4).
- W wyroczni pokrycia forma `--cov=app/parsing/blocks` (ścieżka) nie zbiera danych dla modułu-pliku — używaj `--cov=app.parsing.blocks`.
- `section[data-slide]` nie daje `positions` (brak strony) — cytowanie slajdów wymaga `section` w E1-6.

## Historia
| WP | data | zmiana |
|---|---|---|
| E1-5 | 2026-09-27 | powstanie: `app/domain/chunking/*`, `app/parsing/blocks.py`, 195 testów unit |
