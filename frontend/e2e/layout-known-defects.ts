// Znane wady układu (strażnik helpers/layout.ts, pierwszy bieg 2026-10-09 na `main` @ 367eefd1).
// To NIE jest lista wyjątków na zawsze: każda pozycja to defekt do naprawy w najbliższym WP z UI
// (docs/scenarios, work/INBOX-architect.md 2026-10-09). Poprawka = usunięcie pozycji; nowe pozycje
// dopisuje wyłącznie TL z powodem i WP naprawy — Reviewer odrzuca dopisanie przez Programistę.
export type KnownLayoutDefect = { spec: string; contains: string; reason: string }

export const KNOWN_LAYOUT_DEFECTS: KnownLayoutDefect[] = []
