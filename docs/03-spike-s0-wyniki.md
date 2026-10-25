# Spike S0 — weryfikacja flow agentów (wyniki)

> 2026-09-23/24, Claude Code 2.1.280, kontener Packhorse (router hybrydowy: Claude → Anthropic, GLM → LiteLLM → z.ai).
> Cel: sprawdzić **w łańcuchu wywołań** mechanizmy z [02-flow-agentow.md](02-flow-agentow.md) §9.1 (S0.1–S0.9), zanim zespół ruszy z E0.
> Konfiguracja, która przeszła walidację, jest w `.claude/` tego repo (stan po poprawkach opisanych niżej).

## Spis treści
1. [Werdykt](#1-werdykt)
2. [Metoda](#2-metoda)
3. [Wyniki S0.1–S0.12](#3-wyniki-s01s012)
4. [Znalezione błędy i poprawki](#4-znalezione-błędy-i-poprawki)
5. [Obserwacje o modelach GLM](#5-obserwacje-o-modelach-glm)
6. [Ryzyka otwarte](#6-ryzyka-otwarte)
7. [Checklista przed E0](#7-checklista-przed-e0)
8. [Artefakty](#8-artefakty)

---

## 1. Werdykt

**Flow działa i nadaje się do E0 — po poprawkach z §4, które są już naniesione w `.claude/`.**
Łańcuch Architekt (Opus) → TL (Opus) → 2× Programista (GLM 5.3 Flash, równolegle, osobne worktree) → Reviewer (GLM 5.3) / Doradca (Opus)
przeszedł od briefu WP do merge'u na `main` z zieloną wyrocznią w czterech kolejnych biegach (3–6, po 10–16 min),
w tym **dwa WP z dwoma TL-ami równolegle** (bieg 6) — tak, jak w planie mają pracować zespoły A i B.

Cztery rzeczy były **blokerami** i bez spike'a wyszłyby dopiero w E0:
1. **Wbudowany `advisor` zabija agentów GLM** (401 z LiteLLM) — advisor jest domyślnie włączony także dla GLM; wyłączony zmienną `CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1`.
2. **Raport Programisty omijał bramkę DONE** — raport idzie narzędziem `SubagentHandback`, które nie przechodzi przez `SubagentStop`, więc „GOTOWE” docierało do TL przed review; po zużyciu handbacku kolejny raport szedł `SendMessage(to:"main")` prosto do Architekta. Naprawione hookami `PreToolUse` na `SubagentHandback` (ta sama bramka) i na `SendMessage` (zakaz pisania do `main`).
3. **Hook budżetu kontekstu czytał dla subagenta transkrypt sesji głównej** — TL nigdy nie dostałby sygnału CONTEXT_BUDGET.
4. **TL przełączał gałąź w głównym checkoucie** — dwa równoległe zespoły kolidowałyby w jednym katalogu. Teraz każdy WP ma własny worktree `.wp/<id>`.

Do tego środowisko: w kontenerze nie ma `docker compose`, headless `claude -p` ignoruje allowlistę w niezaufanym katalogu, a plan z.ai ma 5-godzinny limit, którego wyczerpanie zatrzymało bieg 1.

## 2. Metoda

- Zabawkowe repo `ragflow-clone/wd-s0-spike` (kalkulator: `calc/core.py`, `calc/parser.py`, unittest), ta sama konfiguracja `.claude/` co WD, `verify*.sh` = unittest.
  Scenariusz `work/S0-SCENARIO.md`: WP z dwoma niezależnymi zadaniami (T1: `power`/`mod`, T2: unarny minus), sondy zapisu dla każdej roli, SendMessage między rodzeństwem, pytanie do Doradcy.
- Architekt uruchamiany headless: `WD_ROLE=architect claude -p --agent architect --permission-mode auto --output-format stream-json`. Próg budżetu sztucznie niski (45 tys.).
- Log audytowy hooków (`work/logs/hooks.jsonl`) + transkrypty subagentów (`~/.claude/projects/<repo>/<sesja>/subagents/agent-<id>.jsonl`, z `meta.json`) jako źródło prawdy — **nie** raporty agentów.
- Osobno: `wd-s0-relay` (sztafeta S0.9, deterministyczny test bramki, QA-UI), `scratchpad/s0-stacks` (S0.8), `s0-watchdog` (S0.7).

| Bieg | Wynik | Co przerwało / czego dowiódł |
|---|---|---|
| 1 | przerwany | limit z.ai „Usage limit reached for 5 hour” (oba modele GLM); dowiódł S0.1, S0.3, S0.5 (błąd ścieżki), powiadomień u TL |
| 2 | przerwany przeze mnie | po zmianie planu z.ai: **401 z LiteLLM przy każdym użyciu `advisor` przez GLM** → Programista T2 martwy, T1 w pętli ponowień |
| 3 | ✅ merge na `main`, 16 min, 7 testów | pełny łańcuch po wyłączeniu advisora; ujawnił konfabulację T1 i kolejność „raport przed bramką” |
| 4 | ✅ merge na `main`, 12,5 min | walidacja poprawek z biegów 1–3; ujawnił obejście bramki przez `SubagentHandback` i `SendMessage(main)` |
| test hooków | ✅ | deterministyczny test `guard-agents` + bramki na `SubagentHandback` (`wd-s0-relay`) |
| 5 | ✅ merge na `main`, 11,9 min, 0 błędów GLM | regresja z pełną konfiguracją; wszystkie blokady i PASS w logu; ujawnił TL-a w głównym checkoucie |
| 6 | ✅ 2 WP → `main`, 10,1 min, 0 konfliktów | dwóch TL-i równolegle w `.wp/S0-A`, `.wp/S0-B`; główny checkout cały czas na `main` |

Koszt biegu 3 wg liczników Claude Code: $4,69 (Opus ~$1,96; GLM wg cennika `behavesAs`, realny koszt z.ai = plan abonamentowy).

## 3. Wyniki S0.1–S0.12

| # | Mechanizm | Wynik | Dowód / uwagi |
|---|---|---|---|
| S0.1 | Architekt → TL → Programista → Reviewer/Doradca (głębokość 3) | ✅ działa | `meta.json`: `spawnDepth` 1/2/3; Reviewer i Doradca dziedziczą worktree Programisty (`inheritedWorktreePath`). **Każdy poziom widzi listę `Agent(...)` Architekta** (TL widzi `team-leader`, Programista widzi `programmer`, `qa-ui`) — `tools: Agent(...)` nie zawęża wywołań dziecka. Teraz egzekwuje to hook `guard-agents.sh` (test: Programista → `qa-ui` zablokowany). |
| S0.2 | Bramka DONE (`SubagentStop` + `PreToolUse` na `SubagentHandback`) | ✅ działa **po poprawce** | Test deterministyczny: Programista z zakazem review → `SubagentHandback` zablokowany (`BRAMKA DONE: brak werdyktu APPROVED dla HEAD=…`, treść dotarła dosłownie), wyjście `.task/BLOCKED` przepuściło (`PASS-BLOCKED`). Bieg 3–4: PASS z właściwym werdyktem dla HEAD. Czerwona wyrocznia / brudne drzewo / nieaktualny commit — testy hooka na syntetycznych payloadach. Przed poprawką raport omijał bramkę (§4 B2). Przy awarii API (limit, 401) bramka **nie odpala** wcale → TL weryfikuje sam. |
| S0.3 | Guard zapisu per rola | ✅ działa | Zablokowane: Architekt `.py`, TL `.py`, Programista `.claude/hooks/`, Reviewer `calc/`, QA-UI `calc/`. Przepuszczone: Programista `.py` w worktree, Reviewer `review/`, Doradca `docs/decisions/`. `agent_type` jest w payloadzie **także dla sesji głównej** z `--agent architect` → `WD_ROLE` jest tylko zabezpieczeniem. Zapisy przez Bash guard omija (znane, §6). |
| S0.4 | `advisor` dla Programisty GLM | ❌ **szkodliwy → wyłączony** | Advisor jest włączony domyślnie (bez `advisorModel` też). Dla GLM LiteLLM przechwytuje narzędzie (`interceptors/advisor.py`) i woła Anthropic bez klucza → 401 → agent GLM ginie. Wyłączenie: `CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1` w `settings.json` (zweryfikowane: agent GLM nie ma już narzędzia). Koszt: Opus-owi Architekt/TL też tracą advisora (w biegu 1 TL użył go 2×) — rolę przejmuje Doradca. |
| S0.5 | Hook budżetu kontekstu | ✅ działa **po poprawce** | Dla subagenta `transcript_path` = transkrypt sesji głównej, brak `agent_transcript_path` → poprawka: `<transcript bez .jsonl>/subagents/agent-<agent_id>.jsonl`. Po poprawce TL dostał sygnał (46 170 / 45 000), Architekt też (45 886 / 45 000). |
| S0.6 | `SendMessage` między rodzeństwem | ✅ działa | Adresowanie po agent ID (TL przekazał ID T2 z wyniku wywołania w tle): „Message queued for delivery … at its next tool round”; T2 odebrał dosłownie i odpowiedział ACK. **ACK obudził T1 po jego raporcie** i T1 wysłał dopisek → drugie wywołanie bramki. Kanał decyzyjny zostaje plikowy (zgodnie z §6 flow). |
| S0.7 | Watchdog + `Monitor` | ✅ działa | `watchdog.sh` na sztucznych heartbeatach: BLOCKED i STALE od razu, świeży → STALE po przekroczeniu progu, bez duplikatów, STOPPED pominięty. **`Monitor` wygasa po max 30 min** → Architekt musi go uzbrajać ponownie (dopisane do promptu). |
| S0.8 | 2 worktree × własny stos compose + `playwright-cli` | ✅ działa (po doinstalowaniu compose) | Porty z puli 18100–18299 (hash ścieżki + omijanie zajętych), `COMPOSE_PROJECT_NAME=wd-<worktree>`, dwie równoległe sesje `playwright-cli -s=…`, każda widzi swój branch, 0 błędów konsoli. Z kontenera: `host.docker.internal:<port>`. Skrypt: `tools/dev/up.sh`. |
| S0.9 | Sztafeta Architekta (`run-architect.sh`) | ✅ działa | Zmiana 1: sygnał CONTEXT_BUDGET po przekroczeniu progu w kroku 4 → dokończyła krok, HANDOFF `STATE: CONTINUE`, koniec. Zmiana 2: przeczytała HANDOFF, zaczęła od kroku 5 (bez powtórek), `STATE: DONE`, pętla zakończona kodem 0. |
| S0.10 | Modele per rola | ✅ zgodnie z D13 | Transkrypty: Architekt/TL/Doradca `claude-opus-5-5`, Programiści `glm-5.3-flash`, Reviewerzy `glm-5.3`. Pełne ID modelu (`claude-opus-5-5`) w frontmatterze działa. |
| S0.11 | QA-UI (GLM 5.3 Flash + `playwright-cli`) | ✅ bardzo dobrze | Strona z 2 podłożonymi defektami: znalazł oba (ReferenceError po kliknięciu, błąd konsoli przy ładowaniu) **i trzeci prawdziwy** (brak trwałości danych po odświeżeniu), 5 screenshotów, widok 390 px z pomiarem `scrollWidth`, zapis poza `work/qa/` zablokowany. 9 min. |
| S0.13 | Dwa WP / dwóch TL-i równolegle | ✅ działa (po B19) | Bieg 6: TL-e wystartowały 3 s od siebie i pracowały jednocześnie z Programistami i Reviewerami obu zespołów; zapisy TL-i wyłącznie pod `.wp/S0-X/`; `main` nietknięty do merge'u Architekta; 2 merge `--no-ff` bez konfliktów; na końcu tylko główny checkout i gałęzie `wp/*`. |
| S0.14 | Awaria/limit GLM → pauza i automatyczne wznowienie (§8.5 flow) | ✅ działa (po B22–B24) | Bieg pod sterownikiem z symulowaną awarią `glm-5.3-flash` (hook zamrażający agentów GLM + wymuszony stan czujki): TL wykrył `GLM_DOWN`, Architekt zapisał `PAUSED_GLM`, sterownik zakończył zawieszoną zmianę, czekał na czujkę bez tokenów, wznowił pracę 24 s po końcu awarii; WP dokończony i scalony, 7 testów. Szczegóły §3.4. |
| S0.12 | Powiadomienia i czekanie TL na Programistów w tle | ✅ działa, niewygodnie | `<task-notification>` (także `status: failed` przy awarii API) dochodzi do TL-subagenta **tylko w trakcie jego tury** (doklejone do wyniku narzędzia). TL podtrzymywał turę pętlami Bash z `timeout` (gołe `sleep` blokowane). Zalecenie: domyślnie równoległe wywołania na pierwszym planie. |

### 3.1 Bieg 4 — walidacja poprawek

12,5 min, $5,19 (liczniki CC), WP zmergowany na `main`, 7 testów zielonych, oba zadania `PASS` w logu bramki.
Potwierdzone poprawki: brak advisora (0 błędów 401), Doradca na pierwszym planie zapisał `DEC-001` i Programista zacommitował go z kodem (B6),
TL posprzątał worktree (B7), Architekt **zweryfikował twierdzenia w `hooks.jsonl`** i tym razem poprawnie napisał, że blokady bramki nie było (B4).
Nowe znaleziska Architekta (wszystkie naprawione — B15–B18):
- T1 „zakończył bez review” wywołaniem `SubagentHandback` → raport dotarł do TL z pominięciem bramki (`SubagentStop` nie odpalił);
- po zużyciu handbacku T1 wysłał dopisek `SendMessage(to:"main")` → trafił do Architekta zamiast do TL;
- zostały gałęzie `worktree-agent-*` i scalone `feat/*`;
- blokady `guard-writes` nie były widoczne w logu.

**Test hooków po poprawkach** (`wd-s0-relay`, Programista GLM Flash, 3 sondy): `guard-agents BLOCK: programmer -> qa-ui`,
`require-green-and-review BLOCK: brak werdyktu APPROVED` (na `PreToolUse:SubagentHandback`), `guard-agents BLOCK: programmer SendMessage -> main`,
na końcu `PASS-BLOCKED` — Programista zacytował wszystkie trzy komunikaty dosłownie.

### 3.2 Bieg 5 — regresja z pełną konfiguracją

11,9 min, $5,15, WP zmergowany, **0 błędów GLM w routerze**, po odbiorze tylko `main` i `wp/S0-WP1` (worktree i gałęzie techniczne posprzątane — B7, B17).
Log decyzji hooków — komplet oczekiwanych zdarzeń, każde zalogowane (B16):

```
00:58:42 guard-writes              architect   BLOCK: work/probe-arch.py
00:59:29 guard-writes              team-leader BLOCK: work/probe-tl.py
01:02:56 guard-writes              programmer  BLOCK: .claude/hooks/probe.sh
01:03:22 require-green-and-review  programmer  BLOCK: brak werdyktu APPROVED dla HEAD=74979be…   ← T1 próbuje raportu przed review (B2 naprawione)
01:05:05 guard-writes              reviewer    BLOCK: calc/probe_rv.py
01:06:09 require-green-and-review  programmer  PASS: review/s0-wp1-t2-unary.json @ d8ec219…     ← handback
01:06:16 require-green-and-review  programmer  PASS: review/s0-wp1-t2-unary.json @ d8ec219…     ← SubagentStop
01:06:22 require-green-and-review  programmer  PASS: review/s0-wp1-t1-core.json @ 74979be…      ← ten sam commit, teraz z APPROVED
01:06:33 require-green-and-review  programmer  PASS: review/s0-wp1-t1-core.json @ 74979be…
```

Nowe znalezisko Architekta: **TL robił `git switch -c wp/<id>` w głównym checkoucie** — przy dwóch równoległych zespołach (A i B) dwóch TL-i przełączałoby ten sam katalog → B19, walidacja w biegu 6.

### 3.3 Bieg 6 — dwa WP i dwóch TL-i równolegle

10,1 min, $4,09. Scenariusz `work/S0-PARALLEL.md`: WP-A (`calc/core.py`) i WP-B (`calc/parser.py`), Architekt zakłada `.wp/S0-A`, `.wp/S0-B`
i woła dwóch TL-i w jednej wiadomości. Osobny monitor co 3 s sprawdzał gałąź głównego checkoutu — **ani jednej zmiany**.

| agent | pierwszy → ostatni hook | gdzie |
|---|---|---|
| TL A / TL B | 01:13:01 → 01:18:00 / 01:13:04 → 01:20:29 | `.wp/S0-A` / `.wp/S0-B` |
| Programista A / B | 01:13:40 → 01:17:10 / 01:13:52 → 01:19:43 | `.claude/worktrees/agent-…` (gałąź jawnie od `wp/S0-X`) |
| Reviewer A / B | 01:15:13 → 01:16:28 / 01:16:30 → 01:18:23 | worktree swojego Programisty |

Odbiór Architekta własną wyrocznią: `.wp/S0-A` 6 testów, `.wp/S0-B` 4 testy, `main` po obu merge'ach 7 testów — exit 0.
Znaleziska: heartbeat TL-a pokazywał `branch: main` (B20), pułapka `cmd | tail; echo $?` przy odczycie kodu wyjścia (B21);
Architekt sam złapał swój błąd w briefie (liczba testów bazowych z wyliczenia, nie z wyroczni) przed startem TL-i.

### 3.4 S0.14 — pauza i wznowienie przy awarii GLM

Decyzja właściciela 2026-09-24: przy awarii/limicie GLM praca pauzuje i wznawia się sama (bez przełączania na inny model).
Mechanizm: [02-flow-agentow §8.5](02-flow-agentow.md#85-awaria-lub-limit-glm--pauza-i-automatyczne-wznowienie).
Test: gałąź `s0-pause` w `wd-s0-spike`, sterownik `run-architect.sh`, próg pauzy 120 s, odpytywanie co 60 s; awarię symuluje
`tools/agents/test-fault-glm.sh` (hook tylko w spike'u: agent GLM zamarza na najbliższym narzędziu, dopóki istnieje `work/health/force-down`).

| Czas | Zdarzenie (bieg 2, po poprawce B22) |
|---|---|
| 09:13 | zmiana 1, WP S0-P, dwóch Programistów w tle |
| 09:17:09 | awaria `glm-5.3-flash` |
| ~09:20 | `wait-tasks.sh` → `GLM_DOWN`; TL: stan zadań w STATUS/HANDOFF zespołu, raport `PAUSED_GLM`; Architekt: HANDOFF `PAUSED_GLM` |
| 09:21–09:24 | zmiana nie kończy się (zamrożeni agenci w tle) → po 180 s sterownik kończy grupę procesów, zdejmuje blokady worktree |
| 09:24–09:28 | pauza: czujka co 60 s, **0 tokenów** |
| 09:27:39 | koniec awarii → 09:28:03 czujka `OK`, zmiana 2 „wznów WP w stanie PAUSED_GLM” |
| 09:28–09:40 | nowy TL, nowi Programiści, bramka `PASS` ×2, odbiór, merge do `s0-pause`, `STATE: DONE` |

Pierwsza próba (bieg 1) utknęła: TL wykrył awarię i zapisał pauzę, ale **`TaskStop` na własnym Programiście zwrócił błąd własności**, a **`claude -p` nie kończy się, dopóki żyje agent w tle** — zmiana wisiałaby do powrotu GLM (B22).

## 4. Znalezione błędy i poprawki

| # | Waga | Problem | Poprawka (plik) | Zweryfikowane |
|---|---|---|---|---|
| B1 | **BLOKER** | `advisor` domyślnie włączony; agent GLM, który go użyje, dostaje 401 z LiteLLM i ginie (Programista, QA-UI na końcu pracy) | `CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1`, usunięte `advisorModel` (`settings.json`); prompt: pomoc = Doradca | tak (lista narzędzi GLM, bieg 3–4 bez 401) |
| B2 | **BLOKER** | Raport Programisty (`SubagentHandback`) nie przechodzi przez `SubagentStop` → „GOTOWE” docierało do TL przed review | bramka zarejestrowana także jako `PreToolUse` na `SubagentHandback` (`settings.json`, `require-green-and-review.sh` sprawdza rolę); TL i tak sprawdza w worktree werdykt dla `git rev-parse <gałąź>` (`team-leader.md` §Odbiór 0); Programista raportuje raz, na końcu | test hooków: tak |
| B3 | **BLOKER** | Hook budżetu dla subagenta czytał transkrypt sesji głównej | wyliczanie ścieżki z `agent_id` (`hooks/context-budget.sh`) | tak (bieg 3) |
| B4 | wysoka | Programista GLM zameldował blokadę bramki, która nie nastąpiła (wypisał „Kończę.” i od razu wywołał narzędzie); Architekt (Opus) powtórzył to w raporcie S0 | log wyników bramki `PASS/BLOCK/PASS-BLOCKED` w `hooks.jsonl` (`hooks/_lib.sh` `hook_note`, `WD_HOOK_LOG=1`); Architekt i TL weryfikują twierdzenia o mechanizmach w logu; Programista: „nie opisuj zdarzeń, których nie widziałeś w wyniku narzędzia” | log: tak; zachowanie: bieg 4 |
| B5 | wysoka | Programista wołał Doradcę w tle i kończył turę | „Reviewera i Doradcę wołaj na pierwszym planie” (`programmer.md`) | tak (bieg 3) |
| B6 | średnia | Plik decyzji Doradcy w worktree = nieśledzony plik → bramka blokuje („niescommitowane zmiany”) | Programista commituje `docs/decisions/*` razem z kodem (`programmer.md`) | logika hooka |
| B7 | średnia | Worktree Programistów nie są usuwane po zakończeniu (werdykty w `review/` są gitignored) | TL: podsumowanie werdyktu do STATUS.md, potem `git worktree remove --force` (`team-leader.md` §Odbiór 4) | bieg 4 |
| B8 | średnia | Awaria API (limit z.ai / 401) = subagent „failed”, bez `SubagentStop`; worktree bez zmian znika | TL: jedna ponowna próba, potem BLOCKED(quota) z godziną resetu (`team-leader.md` §Odbiór 5) | zaobserwowane w biegu 1 |
| B9 | średnia | Każdy poziom widzi pełną listę typów agentów przodka; `tools: Agent(...)` nie zawęża dziecka | hook `guard-agents.sh` (`PreToolUse` na `Agent`): architect→team-leader; TL→programmer/reviewer/doradca/qa-ui; programmer→reviewer/doradca; reszta→nikt | test hooków: tak |
| B10 | niska | Filtr harnessu oznaczył raport TL jako podejrzany, bo cytował nazwy tagów powiadomień | „nie cytuj tagów harnessu” (`team-leader.md`) | — |
| B11 | niska | Monitor watchdog wygasa po 30 min | prompt Architekta: `timeout_ms: 1800000` + ponowne uzbrajanie | — |
| B12 | środowisko | Brak `docker compose` (i `buildx`) w kontenerze Packhorse | `packhorse-harness/claude/Dockerfile`: wtyczki compose v5.5.1 i buildx v0.37.1 (`ARG DOCKER_COMPOSE_VERSION` / `DOCKER_BUILDX_VERSION`, sumy SHA-256) w `/usr/local/lib/docker/cli-plugins/`; obraz `packhorse/claude:local` przebudowany 2026-09-24 — działa od następnej sesji; `tools/dev/up.sh` sprawdza i podpowiada | tak (obraz testowy z tym krokiem) |
| B13 | środowisko | `claude -p` w niezaufanym katalogu: „Ignoring 18 permissions.allow entries … workspace has not been trusted” (hooki działają, allowlista nie) | przed E0: jednorazowo `claude` interaktywnie w katalogu repo i akceptacja trust (albo `hasTrustDialogAccepted` w `~/.claude/.claude.json`) | — |
| B14 | środowisko | Limit z.ai 5 h zatrzymał bieg 1 (oba modele naraz) | plan z.ai podniesiony przez właściciela; B8; ewentualny fallback Reviewera na `glm-5.3-flash` = zmiana `model:` w `reviewer.md` | — |

| B15 | wysoka | Po zużyciu handbacku Programista raportował `SendMessage(to:"main")` — do Architekta, z pominięciem TL | `guard-agents.sh` blokuje `SendMessage` do `main` dla ról poniżej TL | test hooków: tak |
| B16 | średnia | Blokady `guard-writes` niewidoczne w logu audytowym | `hook_note … "BLOCK: <ścieżka>"` w `guard-writes.sh` | bieg 5 |
| B17 | niska | Zostają gałęzie `worktree-agent-*` i scalone `feat/*` | TL: `git branch -D worktree-agent-<id>`, `git branch -d feat/…` | bieg 5 |
| B19 | **wysoka** | TL pracował w głównym checkoucie (`git switch wp/<id>`) — dwóch równoległych TL-i (zespoły A i B) kolidowałoby w jednym katalogu; Architekt traci swoją gałąź | Architekt zakłada worktree WP `git worktree add .wp/<id> -b wp/<id>`; TL pracuje wyłącznie tam (`cd .wp/<id> &&`); Programista zakłada gałąź **jawnie od bazy z briefu** (`git switch -c feat/… wp/<id>`), bo jego worktree powstaje z HEAD głównego checkoutu (`architect.md`, `team-leader.md`, `programmer.md`, `.gitignore`) | bieg 6 |
| B20 | niska | Heartbeat TL-a miał `branch: main` (cwd hooka = główny checkout) — watchdog nie widział gałęzi WP | `heartbeat.sh` bierze gałąź z worktree `.wp/<id>` wskazanego w ścieżce zapisu lub komendzie | test hooka: tak |
| B21 | niska | `verify.sh \| tail; echo $?` zwraca kod `tail` | reguła w `CLAUDE.md` (bez potoku albo `${PIPESTATUS[0]}`; liczby bazowe z uruchomionej wyroczni) | — |
| B22 | **wysoka** | Pauza nie mogła się zakończyć: TL nie może zatrzymać swoich Programistów (`TaskStop` → błąd własności), a `claude -p` czeka na agentów w tle | sterownik uruchamia zmianę w osobnej grupie procesów (`setsid`); gdy zmiana zapisze `PAUSED_GLM`, a proces żyje dłużej niż `WD_PAUSE_GRACE_S` — kończy grupę; TL bez `TaskStop` | S0.14 bieg 2 |
| B23 | średnia | Wznawiający TL nie mógł usunąć worktree zabitych agentów — klasyfikator trybu auto: „Interfere With Workloads”; TL założył nowe gałęzie `-r2` | sprzątanie (unlock, `worktree remove`, log niescommitowanych zmian w `work/logs/paused-worktrees.log`) robi sterownik po zabiciu zmiany; gałęzie `feat/…` zostają dla kontynuacji | test deterministyczny |
| B24 | niska | `tools/agents/*.sh` wywołane z `.wp/<id>` liczyły katalog repo od worktree WP | `ROOT` z `git rev-parse --git-common-dir` | test deterministyczny |
| B25 | niska | Heartbeat zapisywany jako sformatowany JSON — prosty `grep` nie pasuje (mój kontroler testu) | narzędzia czytają heartbeat przez `jq` (watchdog, wait-tasks już tak robią) | — |
| B18 | niska | Prompt TL mówił jednocześnie „Programista w tle” i „domyślnie pierwszy plan” | ujednolicone: domyślnie pierwszy plan | — |

Drobne, poprawione po drodze: `down` w `tools/dev/up.sh` bez pliku stanu, synchronizacja `programmer.md` (SendMessage w `tools`), heartbeat `STOPPED` z `SubagentStop`.

## 5. Obserwacje o modelach GLM

- **GLM 5.3 Flash jako Programista**: zadania S-owe robi poprawnie i w stylu z briefu (test-first, commity z atrybucją, `.task/STATE`), stosuje się do SPIKE-owych kroków. Słabość: **konfabulacja zdarzeń** (B4) — raport „widziałem blokadę”, której nie było. Wniosek dla E0: wszystko, co Programista twierdzi o mechanizmach, weryfikuje się w logach; zadania M/L TL tnie drobniej.
- **GLM 5.3 jako Reviewer**: werdykty rzetelne, `commit` = faktyczny HEAD, sondy zapisu zgłasza w `not_checked`, zgłosił MINOR (martwy warunek w parserze) bez blokowania — reguła „tylko poprawność blokuje” działa.
- **GLM 5.3 Flash jako QA-UI**: najlepszy wynik spike'a (S0.11) — metodyczny, sam dołożył pomiar przepełnienia i sprawdzenie API.
- GLM wysyła tekst i wywołanie narzędzia w jednej odpowiedzi — „ogłoszenie końca” nie kończy tury. Nie przeszkadza bramce (odpala na faktycznym końcu), ale myli agenta co do tego, co się stało.

## 6. Ryzyka otwarte

| Ryzyko | Stan | Mitygacja |
|---|---|---|
| Guard nie widzi zapisów przez Bash (`sed -i`, `>`); Programista może zmienić `.claude/` lub osłabić test | świadomie niezamknięte | hook bramki używa `verify-fast.sh` z **głównego** checkoutu; Reviewer i TL odrzucają zmiany `.claude/` i wyroczni spoza briefu |
| Brak advisora dla Opus-owych ról | zaakceptowane | Doradca (Opus) na żądanie |
| Ścieżki worktree w `.git` są ścieżkami kontenera (`/host/home/...`) — `git worktree` na hoście ich nie zobaczy, `git worktree prune` na hoście je usunie | otwarte | agentów i gita worktree obsługiwać z jednego środowiska (kontenera); na hoście nie robić `prune` w trakcie pracy zespołu |
| Kontekst subagentów zaśmiecony skillami użytkownika (ComfyUI, …) i serwerami MCP claude.ai | niska waga | opcjonalnie `--strict-mcp-config` / osobny profil użytkownika dla biegów zespołu |
| Limit z.ai przy 8 równoległych agentach GLM | otwarte | obserwować w E0 (router loguje 429); limit równoległości D8 = 4/zespół |

## 7. Checklista przed E0

1. Przebudować obraz Packhorse (`./bin/harness` buduje go przy starcie) i sprawdzić `docker compose version` (B12).
2. Trust katalogu `wawelsky-dragon` dla Claude Code (B13).
3. Commit zmian z 2026-09-23/24 (dokumentacja, `.claude/`, `CLAUDE.md`, `tools/`, `.gitignore`) — repo ma tylko `d060e09`; nic nie zostało zacommitowane bez zgody właściciela.
4. Test dymny GLM: `curl router:8787/v1/messages` z `glm-5.3` i `glm-5.3-flash` (limit z.ai).
5. Pierwsza zmiana Architekta: E0 z progiem budżetu 200 tys. (`settings.json`), `WD_HOOK_LOG=1` (domyślnie włączone).
6. Retrospektywa po E0 (flow §9.3 p. 5): przejrzeć `work/logs/hooks.jsonl` (ile BLOCK, ile PASS-BLOCKED), czas zadań GLM, rozbieżności raport ↔ log.

## 8. Artefakty

- Konfiguracja: `.claude/` (agents: architect, team-leader, programmer, reviewer, doradca, qa-ui; hooks: `_lib.sh`, `guard-writes.sh`, `guard-agents.sh`, `require-green-and-review.sh`, `context-budget.sh`, `heartbeat.sh`; skills: project-context, handoff, task-brief, review-verdict, module-doc), `tools/agents/{run-architect,watchdog}.sh`, `tools/dev/up.sh`, `CLAUDE.md`.
- Zabawkowe repo i logi: `ragflow-clone/wd-s0-spike/` (scenariusz `work/S0-SCENARIO.md`, bieg 5 w `work/logs/` + `work/S0-REPORT-architect.md`, biegi 2–4 w `work/runs/`, screenshoty S0.8 `work/runs/wt-*.png`), `ragflow-clone/wd-s0-relay/` (sztafeta — historia gita, test hooków `work/logs/hooktest.jsonl`, raport QA-UI `work/qa/s0-run1/`).
- Transkrypty: `~/.claude/projects/-host-home-lrozewicz-Data-repozytoria-ragflow-clone-wd-s0-spike/` (w kontenerze).
