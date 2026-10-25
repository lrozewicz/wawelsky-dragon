#!/usr/bin/env bash
# Generuje fixtures starszych formatów biurowych dla testów binaries (kontrakt C12/T9).
# - sample.doc: tworzymy python-docx (tekst kontrolny „Sprawozdanie”/„zażółć”), konwertujemy
#   do Word 97 LibreOffice-em w kontenerze debian:trixie-slim (na hoście tylko uv).
# - sample.ppt: eksport LibreOffice do PowerPoint 97 zawsze osadza w SummaryInformation
#   miniaturę WMF (~575 KB; GenerateThumbnail=false działa tylko dla ODF — sprawdzone 2×),
#   więc plik przekracza limit 200 KB. Zgodnie z briefem używamy małego pliku testowego
#   Apache POI: test-data/slideshow/slide_master.ppt (https://github.com/apache/poi/tree/trunk/test-data,
#   licencja Apache-2.0); tekst kontrolny w teście pochodzi z tego pliku („Slide Masters”).
# Pliki pośrednie (.docx) są usuwane; wyniki ≤ 200 KB.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$(cd "$DIR/../../.." && pwd)"
POI_URL="https://raw.githubusercontent.com/apache/poi/trunk/test-data/slideshow/slide_master.ppt"

# 1) sample.docx zależnością backendu (python-docx), konwersja do Word 97 w kontenerze.
#    Pliki przekazywane przez docker cp — daemon Dockera działa na hoście i nie zna ścieżek
#    /host/... kontenera agenta (zob. tools/dev/up.sh), więc bind-mount niczego nie przeniesie.
cd "$BACKEND"
uv run --frozen python - "$DIR" <<'PY'
"""Tworzy sample.docx z nagłówkiem i akapitem kontrolnym dla konwersji wvHtml."""
import sys
from pathlib import Path

from docx import Document

out = Path(sys.argv[1])
document = Document()
document.add_heading("Sprawozdanie", level=1)
paragraph = (
    "Podsumowanie kwartału: zażółć gęślą jaźń, a następnie pchnąć łódź w małą "
    "zatokę starego portu, gdzie czeka już załoga przygotowana na dłuższy rejs "
    "wzdłuż wybrzeża. Wszystkie zapiski z wyprawy trafią do archiwum zamkowego, "
    "a kopie otrzymają także uczestnicy wyprawy."
)
assert len(paragraph) >= 200
document.add_paragraph(paragraph)
document.save(out / "sample.docx")
PY
CID="wd-legacy-office-$$"
docker run -d --name "$CID" debian:trixie-slim sleep 300 >/dev/null
trap 'docker rm -f "$CID" >/dev/null 2>&1 || true' EXIT
docker cp "$DIR/sample.docx" "$CID":/tmp/sample.docx
docker exec "$CID" sh -c "
  apt-get update -qq \
  && apt-get install -y -qq --no-install-recommends libreoffice-writer-nogui \
  && cd /tmp \
  && soffice --headless --convert-to doc sample.docx
"
docker cp "$CID":/tmp/sample.doc "$DIR/sample.doc"
rm -f "$DIR/sample.docx"

# 2) sample.ppt z test-data Apache POI (patrz komentarz nagłówkowy)
curl -sL "$POI_URL" -o "$DIR/sample.ppt"

ls -l "$DIR/sample.doc" "$DIR/sample.ppt"
