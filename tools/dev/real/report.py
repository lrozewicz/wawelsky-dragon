#!/usr/bin/env python3
"""Scalanie raportu wyroczni verify-real (CONTRACT WP E5-H5 §2, T1).

Czyta <report_dir>/real-corpus.json (specy e2e-real) i <report_dir>/worker-mem.tsv (mem-sampler.sh),
dopisuje do JSON szczyt pamięci workera i regeneruje <report_dir>/real-corpus.md (to samo na stdout).
Tylko stdlib: brak real-corpus.json → komunikat i rc 0.
"""

import json
import sys
from pathlib import Path


def read_peak_mb(tsv: Path):
    """Szczyt pamięci workera w MB (1 miejsce) z kolumny bajtów TSV; brak próbek → None."""
    if not tsv.is_file():
        return None
    peak = 0
    seen = False
    for line in tsv.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        try:
            value = int(parts[1])
        except ValueError:
            continue
        peak = max(peak, value)
        seen = True
    return round(peak / 1048576, 1) if seen else None


def main() -> int:
    if len(sys.argv) != 2:
        print("użycie: report.py <report_dir>", file=sys.stderr)
        return 2
    report_dir = Path(sys.argv[1])
    json_path = report_dir / "real-corpus.json"
    if not json_path.is_file():
        print(f"report.py: brak {json_path} — nic do scalenia")
        return 0

    data = json.loads(json_path.read_text(encoding="utf-8"))
    peak = read_peak_mb(report_dir / "worker-mem.tsv")
    if peak is not None:
        data["worker_peak_mb"] = peak
    else:
        print("report.py: brak próbek w worker-mem.tsv — worker_peak_mb pominięte", file=sys.stderr)
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "| plik | KB | status | czas parsowania s | chunki | ścieżka uploadu |",
        "|---|---|---|---|---|---|",
    ]
    for doc in data.get("docs", []):
        kb = round(doc.get("bytes", 0) / 1024, 1)
        lines.append(
            f"| {doc.get('name', '')} | {kb} | {doc.get('status', '')} "
            f"| {doc.get('parse_seconds', '')} | {doc.get('chunks', '')} | {doc.get('path', '')} |"
        )
    lines.append("")
    lines.append(f"Szczyt pamięci workera: {peak if peak is not None else 0.0} MB")
    text = "\n".join(lines) + "\n"
    (report_dir / "real-corpus.md").write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
