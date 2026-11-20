/**
 * Domyślna waga wektorów w wyszukiwaniu WD (UI): 0.8 — hybryda z pełnotekstowym.
 *
 * Pomiar 05.11.2026 na 262 pytaniach spoza treningu: 0.3 z RAGFlow istotnie gorsze (top-6 194
 * vs 205 przy 1.0, p=0,035), 0.7–1.0 równoważne. Pomiar 20.11.2026: same wektory (1.0) gubią
 * zapytania o identyfikator — skrót, numer tablicy, „poz. 1270”: fragment w top-10 w 94/245,
 * przy 0.8 w 220/245 (z premią identyfikatorów w backendzie); pytania opisowe bez zmian.
 * API zgodne z RAGFlow zostaje przy 0.3 — wagę ustawia klient (tu: UI).
 */
export const DEFAULT_VECTOR_WEIGHT = 0.8

/**
 * Domyślna liczba fragmentów kontekstu w czacie WD (UI): 10 zamiast 6 z RAGFlow.
 *
 * Pomiar 05.11.2026 na 293 pytaniach spoza treningu (trafność odpowiedzi): gpt-4.1-mini 231 → 246,
 * Qwen3.5-9B 220 → 234 (p≤0,001), Bielik 212 → 221; top_n=4 dawał gorzej (201). Koszt: ok.
 * +1000 tokenów wejścia, Bielik na GX10 +1,3 s mediany. API zgodne z RAGFlow zostaje przy 6.
 */
export const DEFAULT_TOP_N = 10
