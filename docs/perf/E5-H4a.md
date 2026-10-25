# E5-H4a — smoke live: Xiaomi-OCR-0 (vLLM) → chunki tabel GUS

Data: 2026-10-04. WP `E5-H4a`, gałąź `wp/E5-H4a`. Wynik pomiaru lokalnego (bez kosztów API).

## Środowisko
- GPU: NVIDIA GeForce RTX 4070 Ti SUPER (16 GB; ~1,4 GB zajęte przez inne procesy przed startem; po starcie vLLM ~8,7 GB użyte).
- Obraz: `vllm/vllm-openai:v0.30.0`, kontener `wd-e5h4a-ocr` (`docker run --gpus all --ipc host`), argumenty jak usługa `ocr` w `docker-compose.yml`:
  `--model SeerRay-Lab/Xiaomi-OCR-0 --served-model-name xiaomi-ocr-0 --max-model-len 16384 --gpu-memory-utilization 0.5 --limit-mm-per-prompt '{"image":1,"video":0}'`.
- Cache modelu: wolumen Dockera **`wd-e5h4a-hf-cache`** (zostawiony dla E5-H4b); kontener usunięty po biegu.
- Plik: `dataset/documents/pl/pdf/gus_rocznik_statystyczny_rp_2024.pdf` (poza repo). Strony (1-based w PDF): TABL. 17 (160) = **243** (druk s. 241), TABL. 14 (157) = **240** (druk s. 238).

## Komendy (powtarzalne)
Test: `backend/tests/live/test_ocr_xiaomi.py` (`-m live`; zmienne `WD_OCR_BASE_URL`, `WD_OCR_PDF`, opcjonalnie `WD_OCR_REPORT`).
Z powodu izolacji sieci kontenera agenta test uruchomiono w kontenerze współdzielącym sieć z vLLM:
```
docker run --rm --network container:wd-e5h4a-ocr -v <repo>/backend:/work:ro -v <gus.pdf>:/gus.pdf:ro -w /work \
  -e PYTHONPATH=/work -e PYTHONDONTWRITEBYTECODE=1 -e WD_OCR_BASE_URL=http://127.0.0.1:8000/v1 -e WD_OCR_PDF=/gus.pdf \
  --entrypoint pytest wawelsky/backend-test-ocr:e5-h2 tests/live/test_ocr_xiaomi.py -m live -s -p no:cacheprovider -q
```
(przy dostępie z hosta do `http://127.0.0.1:18000/v1` wystarczy `cd backend && uv run pytest tests/live/test_ocr_xiaomi.py -m live -s`).

## Wynik
`2 passed in 34 s`.

| strona | czas konwersji (render 200 DPI + model + OTSL→HTML) | chunków | znaków HTML |
|---|---|---|---|
| 243 (TABL. 17) | 6,4 s (kolejne biegi 8,2 s) | 9 | 1868 |
| 240 (TABL. 14) | 5,0 s (kolejne biegi 5,1 s) | 4 | 2017 |

- **TABL. 17**: wiersz „15—24 lata” — wszystkie 6 par (rok, kolumna) → wartość poprawnych: 2019 ogółem 9,9 / kobiety 10,3; 2022 ogółem **10,8** / kobiety **11,3**; 2023 ogółem 11,3 / kobiety 11,1 (także 2020: 10,9 / 11,6). Przykład tekstu chunka:
  `WYSZCZEGÓLNIENIE: 15—24 lata; 2019 / ogólem total / w % in %: 9,9; 2019 / w tym kobiety of which women / w % in %: 10,3; … 2022 / ogólem total / w % in %: 10,8; 2022 / w tym kobiety of which women / w % in %: 11,3; …`
- **TABL. 14**: porównanie ciągu liczb (jak `numcmp.py`, z HTML chunków po zdjęciu tagów) z warstwą tekstu strony: GT=88, dopasowane 86 → **0,9773** (próg 0,95). Różnice: rok „238” (numer strony) po stronie GT oraz „6,8”/lata nagłówka po stronie OCR.
- Pierwotna wersja testu liczyła liczby z `chunk.text` → 0,943 (powtórzenia nazw kolumn w każdym wierszu zaniżają dopasowanie, nie jest to błąd OCR); zmieniono na HTML chunków (jak `numcmp.py`).

## Czego nie zmierzono
Cała książka (745 stron), współbieżność, wpływ `WD_OCR_GPU_UTIL`. Czas na stronę ~5–8 s dotyczy pojedynczej strony przez kolejną ścieżkę (pierwsze żądanie po starcie bywa wolniejsze); benchmark właściciela (`../ocr-bench/xiaomi-ocr-0/conc_result.txt`): 1,18 s/stronę przy 10 równoległych.
