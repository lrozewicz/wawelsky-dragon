/**
 * Domyślna waga wektorów w wyszukiwaniu WD (UI): 1.0 zamiast 0.3 z RAGFlow.
 *
 * Pomiar 05.11.2026 na 262 pytaniach spoza treningu: waga 0.3 → właściwy fragment w top-6
 * w 194 przypadkach, 1.0 → 205 (McNemar p=0,035; top-1: 119 vs 143, p=0,001). Przy 1.0 backend
 * pomija zapytanie pełnotekstowe (nie zmienia rankingu), co skraca wyszukiwanie o sekundy.
 * API zgodne z RAGFlow zostaje przy 0.3 — wagę ustawia klient (tu: UI).
 */
export const DEFAULT_VECTOR_WEIGHT = 1.0

/**
 * Domyślna liczba fragmentów kontekstu w czacie WD (UI): 10 zamiast 6 z RAGFlow.
 *
 * Pomiar 05.11.2026 na 293 pytaniach spoza treningu (trafność odpowiedzi): gpt-4.1-mini 231 → 246,
 * Qwen3.5-9B 220 → 234 (p≤0,001), Bielik 212 → 221; top_n=4 dawał gorzej (201). Koszt: ok.
 * +1000 tokenów wejścia, Bielik na GX10 +1,3 s mediany. API zgodne z RAGFlow zostaje przy 6.
 */
export const DEFAULT_TOP_N = 10
