# M10 — Frontend (SPA na MUI z architekturą informacji RAGFlow)

> Moduł M10 z [ARCHITECTURE.md](../ARCHITECTURE.md). ADR-y: 17 (SPA), 18 (OpenAPI → typy TS), 13 (auth).
> Źródła: inwentaryzacja UI RAGFlow (`ragflow/web`), szablony MUI (`material-ui/docs/data/material/getting-started/templates/{dashboard,sign-in,crud-dashboard,shared-theme}`), frontend bety, hub-compat.

## Spis treści
1. [Zasady](#1-zasady)
2. [Stos i wersje](#2-stos-i-wersje)
3. [Struktura projektu](#3-struktura-projektu)
4. [Motyw i layout (szablony MUI)](#4-motyw-i-layout-szablony-mui) — w tym §4.4 Reguły UX
5. [Autoryzacja w przeglądarce](#5-autoryzacja-w-przeglądarce)
6. [Architektura informacji: RAGFlow → Wawelsky Dragon](#6-architektura-informacji-ragflow--wawelsky-dragon)
7. [Specyfikacja stron](#7-specyfikacja-stron)
8. [Inwentarz pól formularzy (KEEP / ADV / DROP)](#8-inwentarz-pól-formularzy-keep--adv--drop)
9. [Klient API, SSE i stan serwera](#9-klient-api-sse-i-stan-serwera)
10. [i18n, dostępność, wydajność](#10-i18n-dostępność-wydajność)
11. [Testy i scenariusze S6](#11-testy-i-scenariusze-s6)
12. [Pułapki znane z bety](#12-pułapki-znane-z-bety)
13. [Uwagi do Big Picture](#13-uwagi-do-big-picture)

---

## 1. Zasady

1. **Ta sama architektura informacji co RAGFlow**: te same pozycje menu w tej samej kolejności, te same URL-e, te same kluczowe akcje w tych samych miejscach. Zmienia się **orientacja** nawigacji (górny pasek → lewe SideMenu) i wygląd (MUI), nie mapa.
2. **Jeden system UI**: MUI + `sx` + motyw. Bez Tailwind, bez LESS, jeden zestaw ikon (`@mui/icons-material`).
3. **Mniej opcji na wierzchu**: pola z werdyktem ADV siedzą w akordeonie „Zaawansowane”, DROP nie istnieją w UI (API je nadal przyjmuje).
4. **Jeden klient HTTP**, typy generowane z OpenAPI backendu (ADR-18). Żadnych ręcznie pisanych typów odpowiedzi.
5. **Stan serwera tylko w TanStack Query**. Stan klienta: URL (search params z zod) > lokalny stan komponentu > kontekst. Bez zustand/redux w v1.
6. **Strony pełnoekranowe (czat, chunki, canvas) nie usuwają nawigacji** — SideMenu zwija się do trybu mini (64 px).

---

## 2. Stos i wersje

Wersje przypięte **dokładnie** (bez `^`), `bun.lock` w repo. Sprawdzone 2026-09-23.

| Pakiet | Wersja | Uwagi |
|---|---|---|
| bun | 1.4.2 | runtime, menedżer pakietów, serwer produkcyjny (`serve.ts`) |
| react / react-dom | 19.3.0 | |
| @mui/material, @mui/icons-material | 9.4.0 | MUI 8 nie istnieje; migracja v7→v9: `slots/slotProps`, brak system props (tylko `sx`), `Grid` z `size` |
| @mui/x-data-grid | 9.14.0 | tabele plików, dokumentów, logów, użytkowników (wersja darmowa — nie `-pro`) |
| @emotion/react / @emotion/styled | 11.14.0 / 11.14.1 | |
| @tanstack/react-router | 1.170.38 | file-based routing |
| @tanstack/router-plugin | 1.168.40 | eksport **`tanstackRouter`** (nie przestarzały `TanStackRouterVite`) |
| @tanstack/react-query (+ devtools) | 5.103.2 | |
| @tanstack/react-form | 1.33.5 | formularze + walidacja zod |
| @tanstack/zod-adapter | 1.167.0 | `validateSearch` |
| zod | 4.6.5 | API v4 (`z.email()` itd.) |
| vite | 8.3.0 | Rolldown + Oxc |
| @vitejs/plugin-react | 6.1.1 | bez Babel |
| typescript | **6.0.3** | TS 7 nie ma API dla typescript-eslint (do 7.1) |
| eslint / @eslint/js | 10.11.0 / 10.0.1 | flat config (jak hub-compat) |
| typescript-eslint | 8.70.1 | |
| eslint-plugin-react-hooks / eslint-plugin-react | 7.1.1 / 7.37.5 | |
| prettier | 3.9.8 | `semi:false, singleQuote, trailingComma:all, printWidth:100` (jak hub-compat) |
| vitest / @vitest/coverage-v8 | 5.0.1 | |
| @testing-library/react / jest-dom / user-event | 16.3.3 / 7.0.1 / 14.6.7 | |
| jsdom | 30.1.1 | środowisko testów |
| msw | 2.15.0 | mock API w testach i w trybie „demo” |
| @playwright/test | 1.63.0 | e2e |
| react-markdown / remark-gfm | 10.1.0 / 4.0.1 | odpowiedzi czatu, podsumowanie wyszukiwania |
| openapi-typescript / openapi-fetch | 7.13.0 / 0.17.0 | typy i klient z `/openapi.json` |
| eventsource-parser | aktualna 3.x (zweryfikować) | parser SSE po `fetch` |
| i18next / react-i18next | 26.4.2 / 17.0.15 | |
| oidc-client-ts | 3.5.0 | tylko jeśli wybrany Keycloak PKCE z refresh w przeglądarce (patrz §5) |
| dayjs | aktualna 1.x | daty (MUI X date pickers tylko gdy potrzebne) |
| @xyflow/react | — | **dopiero z modułem Agent (E6)** |

**Skrypty `package.json`** (kontrakt dla wyroczni):

```json
{
  "scripts": {
    "dev": "vite",
    "gen:api": "openapi-typescript ../backend/openapi.json -o src/api/schema.gen.ts",
    "gen:routes": "tsr generate",
    "build": "vite build",
    "typecheck": "tsr generate && tsc --noEmit",
    "lint": "eslint . --max-warnings=0",
    "format:check": "prettier --check .",
    "test": "vitest run",
    "test:cov": "vitest run --coverage",
    "e2e": "playwright test",
    "check": "bun run typecheck && bun run lint && bun run test:cov && bun run build"
  }
}
```

`typecheck` sam generuje `routeTree.gen.ts` (`tsr generate` z `@tanstack/router-cli`), więc nie zależy od kolejności z buildem — to usuwa pułapkę z bety (§12).
`openapi.json` jest **commitowany** w `backend/openapi.json` (generowany skryptem backendu, sprawdzany w teście kontraktu, że jest aktualny). Frontend nie potrzebuje działającego backendu, żeby się zbudować.

---

## 3. Struktura projektu

```
frontend/
  index.html
  serve.ts                    # Bun: statyka dist/ + fallback index.html + reverse proxy /api… (M12)
  public/env-config.js        # window.__ENV__ (runtime config, jak hub-compat/beta)
  vite.config.ts  vitest.config.ts  playwright.config.ts  eslint.config.js  tsconfig.json
  src/
    main.tsx                  # QueryClient, Router, AppTheme, I18nProvider
    app/
      router.tsx              # createRouter({ routeTree, context: { auth, queryClient }, defaultPreload: 'intent' })
      queryClient.ts
      env.ts                  # odczyt window.__ENV__ z walidacją zod
    routes/                   # TanStack file routes — WYŁĄCZNIE katalogi + route.tsx dla layoutów
      __root.tsx
      login.tsx
      auth/callback.tsx
      _app/route.tsx          # layout zalogowany: SideMenu + AppNavbar + Header + <Outlet/>, beforeLoad guard
      _app/index.tsx          # Home  "/"
      _app/datasets/index.tsx                     # /datasets
      _app/dataset/route.tsx                      # layout szczegółów datasetu (sub-menu)
      _app/dataset/files/$id.tsx                  # /dataset/files/:id
      _app/dataset/retrieval/$id.tsx              # /dataset/retrieval/:id
      _app/dataset/logs/$id.tsx                   # /dataset/logs/:id
      _app/dataset/configuration/$id.tsx          # /dataset/configuration/:id
      _app/chunk/parsed/chunks.tsx                # /chunk/parsed/chunks?id=&doc_id=
      _app/chats/index.tsx                        # /chats
      _app/chat/$id.tsx                           # /chat/:id?conversationId=
      _app/searches/index.tsx  _app/search/$id.tsx
      _app/agents/index.tsx                       # flaga FEATURE_AGENT
      _app/files/index.tsx                        # /files?folder=
      _app/user-setting/route.tsx                 # layout ustawień (sub-menu)
      _app/user-setting/index.tsx                 # redirect → model
      _app/user-setting/model.tsx  profile.tsx  api.tsx
      _app/admin/route.tsx  _app/admin/users.tsx  _app/admin/status.tsx  _app/admin/access.tsx
      _app/document/$id.tsx                       # podgląd dokumentu pełnoekranowo
    features/                 # logika i komponenty per obszar (bez tras)
      auth/  home/  datasets/  documents/  chunks/  retrieval/  chats/  chat-stream/
      search/  files/  settings/  admin/  agents/
      <obszar>/{api.ts, queries.ts, components/*, hooks/*, *.test.tsx}
    components/               # współdzielone: layout/, PageContainer, EmptyState, ConfirmDialog, …
    hooks/                    # useDialogs, useNotifications (z crud-dashboard), useDebounce, usePolling
    lib/                      # sse.ts, citations.ts, download.ts, format.ts, featureFlags.ts
    api/
      schema.gen.ts           # openapi-typescript (generowany, commitowany)
      client.ts               # openapi-fetch + middleware: Authorization, refresh 401, rozpakowanie koperty
      envelope.ts             # {code,message,data} → data | ApiError
    i18n/  locales/{pl,en}.json  index.ts
    theme/  (kopia shared-theme + dashboard/theme/customizations + dataGrid.ts z crud-dashboard)
  e2e/  (Playwright, scenariusze S6)
```

Reguły:
- **Routes są cienkie**: `loader` (prefetch `queryClient.ensureQueryData`), `validateSearch` (zod), render komponentu z `features/`. Żadnej logiki biznesowej w plikach tras.
- **Każdy wspólny prefiks tras ma plik `route.tsx`** (layout z `<Outlet/>`) — patrz pułapka §12.2.
- `features/<obszar>/queries.ts` eksportuje fabryki `queryOptions()` i hooki mutacji; klucze zapytań jako stałe (`datasetKeys.list(params)`), inwalidacja tylko przez nie.
- Limit ~300 LOC na plik komponentu (dialogi w osobnych plikach, jak w hub-compat).

---

## 4. Motyw i layout (szablony MUI)

### 4.1 Co bierzemy z szablonów

| Źródło | Plik(i) | Użycie w WD |
|---|---|---|
| `shared-theme/` | `AppTheme.tsx`, `themePrimitives.ts`, `customizations/{inputs,dataDisplay,feedback,navigation,surfaces}`, `ColorModeIconDropdown.tsx`, `ColorModeSelect.tsx` | kopiujemy do `src/theme/`; **`brand` w `themePrimitives.ts` zamieniamy na paletę Wawelsky Dragon** |
| `dashboard/` | `components/{SideMenu,MenuContent,AppNavbar,SideMenuMobile,Header,NavbarBreadcrumbs,OptionsMenu,MenuButton,CardAlert}.tsx`, `theme/customizations/{dataGrid,datePickers}` | szkielet layoutu `_app/route.tsx` |
| `crud-dashboard/` | `components/PageContainer.tsx`, `DashboardSidebar*` (logika zwijania mini-variant), `hooks/useDialogs`, `hooks/useNotifications`, `theme/customizations/dataGrid.ts` | nagłówek stron (breadcrumbs + tytuł + akcje), dialogi potwierdzeń jako Promise, kolejka snackbarów; **`dataGrid.ts` bierzemy stąd**, bo w `dashboard/theme/customizations/` jest tylko wersja `.js` |
| `sign-in/` | `SignIn.tsx`, `components/{ForgotPassword,CustomIcons}.tsx` | strona `/login` |

Adaptacje obowiązkowe:
- `dashboard/theme/customizations/dataGrid` importuje augmentację z `x-data-grid-pro` — zamienić na `@mui/x-data-grid`.
- `crud-dashboard` używa react-router (`createHashRouter`) — przenosimy tylko komponenty/hooki, linki zamieniamy na `Link` z TanStack Router (`createLink(ListItemButton)`).
- Szablony są pisane pod MUI 7 — przy kopiowaniu przejść checklistę migracji v9 (system props → `sx`, `componentsProps` → `slotProps`, `GridLegacy` → `Grid size`).

### 4.2 Paleta i tryb ciemny
- `themePrimitives.ts`: `brand` = czerwień smocza (np. hsl 355°, skala 50–900), `gray` bez zmian; kolory statusów parsowania stałe w motywie: `pending` = grey, `running` = info/blue, `cancel` = warning/orange, `done` = success/green, `fail` = error/red.
- `cssVariables: { colorSchemeSelector: 'data-mui-color-scheme' }`, schematy light/dark; przełącznik `ColorModeIconDropdown` (System/Light/Dark) w Header i w AppNavbar; wybór pamiętany przez MUI (`localStorage`).
- Font Inter (jak szablon), `shape.borderRadius = 8`.
- Logo: SVG smoka w `SitemarkIcon`-owym komponencie `BrandLogo`.

### 4.3 Layout zalogowany (`_app/route.tsx`)

```
┌───────────────┬──────────────────────────────────────────────────────────┐
│ SideMenu      │ Header (md+): Breadcrumbs │ [Search] │ Język │ Motyw      │
│ 240px / mini  ├──────────────────────────────────────────────────────────┤
│ 64px          │ <Outlet/> — strona w PageContainer (tytuł, akcje)         │
│ Logo WD       │                                                          │
│ ───────────── │                                                          │
│ Home          │                                                          │
│ Datasets      │                                                          │
│ Chat          │                                                          │
│ Search        │                                                          │
│ Agent (flaga) │                                                          │
│ Memory(ukryte)│                                                          │
│ Files         │                                                          │
│   …           │                                                          │
│ Settings      │                                                          │
│ Admin (superu)│                                                          │
│ Help ↗        │                                                          │
│ [CardAlert:   │                                                          │
│  brak modeli] │                                                          │
│ Avatar+menu ⋮ │                                                          │
└───────────────┴──────────────────────────────────────────────────────────┘
< md: AppNavbar (logo, tytuł, motyw, hamburger → SideMenuMobile)
```

- Stan zwinięcia SideMenu: `localStorage` + automatycznie mini na trasach `/chat/*`, `/chunk/*`, `/agent/*` (`staticData: { fullBleed: true }` w definicji trasy).
- `CardAlert` z szablonu zmienia przeznaczenie: pokazuje się, gdy `GET /api/v1/users/me/models` nie ma domyślnego LLM lub embeddingu („Skonfiguruj modele” → `/user-setting/model`).
- Menu użytkownika (`OptionsMenu`, stopka SideMenu): Profil, Ustawienia, Język ▸, Wyloguj.

---

### 4.4 Reguły UX (obowiązują każdy ekran — analiza 2026-10-09)
Źródło: usterki z testów właściciela (v1, Q34) i defekty QA-UI E3–E5-H. Sprawdzają je automatycznie
`frontend/e2e/helpers/layout.ts` (`expectNoLayoutDefects`, także na końcu każdego testu e2e) i `e2e/visual.spec.ts`;
QA-UI i Reviewer — na zrzutach ekranu.

| # | Reguła | Jak sprawdzane |
|---|---|---|
| U1 | **Nic nie nachodzi na siebie** — tekst na tekście, etykieta pola na wpisanej wartości, menu ⋮ na nazwie. | `overlap`, `label-over-value`, `covered` |
| U2 | **Długi tekst**: jednowierszowy → wielokropek + pełna treść w `title`/podpowiedzi; wielowierszowy → zawijanie (`overflow-wrap: anywhere`). Nigdy ucięcie bez wielokropka. | `clipped`, fixture „długie dane” |
| U3 | **Strona nie przewija się poziomo** (także 390 px). Szerokie tabele przewijają się wewnątrz własnego kontenera, a pierwsza kolumna (nazwa + menu ⋮) zostaje widoczna. | `overflow-page`, S6-14 |
| U4 | **Popover tylko dla krótkich treści** (≤ ~3 linie, podpowiedź, menu). Treść dłuższa lub przewijalna (fragment cytowania, log zadania, podgląd) → **modal albo szuflada**. Każde okno nakładkowe mieści się w całości w oknie przeglądarki (auto-pozycjonowanie, `max-height` + przewijanie wewnątrz). | `off-screen`, usterka #7 |
| U5 | **Każdy ekran ma 4 stany**: ładowanie (szkielet, nie pusty ekran), pusty (co zrobić dalej + przycisk), błąd (przyczyna zrozumiała dla użytkownika + „Spróbuj ponownie”; nigdy „bad request”/stack trace), dane. | tabela §7.0, scenariusze |
| U6 | **Długa operacja pokazuje postęp, który się zmienia** (co ≤ 30 s: etap + liczba, np. „OCR 120/745 stron”), czas trwania i działający **Stop**. „1%” przez kilka minut = defekt. | scenariusze z budżetem czasu, usterka Q34-4 |
| U7 | **Akcja nie dubluje się** przy podwójnym kliknięciu (przycisk zablokowany w trakcie), a ponowne otwarcie dialogu startuje z czystym stanem. | wariant scenariusza „podwójny klik / ponowne otwarcie” (U2, U4 z E5-H) |
| U8 | **Każde pole konfiguracji mówi, co zmienia i na co działa** (podpowiedź/`helperText`): zwłaszcza czy zmiana dotyczy tylko nowych plików, czy wymaga ponownego parsowania istniejących. Etykieta = rzeczywiste znaczenie (nie „Max tokens”, gdy pole to okno kontekstu). | tabela §8.5, usterki Q34-2, Q34-5 |
| U9 | **Kontrast i etykiety w obu motywach** — przycisk bez widocznej etykiety w ciemnym motywie to defekt (E3-H4). | axe + `visual.spec.ts` (dark) |
| U10 | **Upuszczony plik, którego nie da się odczytać** (0 B, brak dostępu przeglądarki) → komunikat z przyczyną i alternatywą („użyj Wybierz plik”), nie cicha porażka. | e2e `DataTransfer`, usterka Q34-3 |
| U11 | **Walidacja formularzy jednakowa wszędzie** (Architekt, zmiana 27): przycisk główny aktywny; klik przy pustym polu wymaganym → komunikat pod polem + fokus na pierwszym błędnym polu, etykieta zostaje nad polem; błędy formatu/unikalności na bieżąco po opuszczeniu pola. Fokus i włączone kontrolki w kolorze akcentu (`secondary`), nigdy w kolorze błędu. | SC-E5-H9-01/02, `visual.spec.ts` (fokus vs błąd) |
| U12 | **Dialogi na telefonie (390 px, Q60, v1.3)**: krótkie dialogi (potwierdzenia, zmiana nazwy, „Nowy czat”, „Nowy klucz API”, „Odrzucić zmiany?”, podgląd fragmentu cytowania — doprecyzowanie V13-z) — dopasowane wysokością do treści, nie pełny ekran, marginesy ≥ 16 px; pełny ekran tylko długie formularze/kreatory (import, eksport, integracje) z nagłówkiem i akcjami zawsze widocznymi (przewija się treść). Szuflady ustawień: nieaktywny „Zapisz” zawsze z widocznym powodem („Brak zmian do zapisania”). | SC-V13-11, SC-V13-12, `visual.spec.ts` 390 |

Makiety: dla każdego ekranu z §7 obowiązuje zrzut wzorcowy z `frontend/e2e/visual.spec.ts-snapshots/` (stan „jest”);
nowy ekran — makieta ASCII albo zrzut RAGFlow z adnotacjami w §7 **przed** pierwszym WP tego ekranu (Architekt).

## 5. Autoryzacja w przeglądarce

### 5.1 Model tokenów (kontrakt z M3)
- `POST /api/v1/auth/login {email, password}` → body: profil użytkownika (kształt RAGFlow) + `data.access_token` (JWT 15 min — **tego używa SPA**), nagłówek `Authorization: <token legacy>` (dla klientów w stylu web UI RAGFlow; SPA go ignoruje), **cookie `wd_refresh`** (httpOnly, Secure, SameSite=Strict, Path=`/api/v1/auth`).
- Access token (15 min) trzymany **wyłącznie w pamięci** (moduł `features/auth/tokenStore.ts`), nigdy w `localStorage`.
- `POST /api/v1/auth/refresh` (cookie) → nowy access token. Wywoływany: przy starcie aplikacji (odtworzenie sesji po F5), w middleware klienta przy 401 (jedno równoległe odświeżenie — współdzielony Promise), proaktywnie 60 s przed `exp`.
- `POST /api/v1/auth/logout` → czyści cookie i unieważnia refresh w DB.
- Nagłówek do API: `Authorization: Bearer <access>` (backend akceptuje też bez `Bearer`, ale my zawsze wysyłamy z prefiksem).

### 5.2 Keycloak (OIDC)
- `GET /api/v1/auth/login/channels` → lista kanałów (np. `[{channel:"keycloak", display_name:"hub-compat SSO", icon}]`); przyciski na stronie logowania w miejscu „Sign in with Google/Facebook” z szablonu.
- Przepływ: **Authorization Code + PKCE po stronie backendu** (`GET /api/v1/auth/login/keycloak` → redirect do KC → `GET /api/v1/auth/oauth/keycloak/callback` → backend wymienia kod, zakłada/aktualizuje użytkownika, ustawia `wd_refresh`, redirect do `/auth/callback`) → frontend na `/auth/callback` robi `refresh` i przechodzi do `redirect` z query.
  - Zaleta: frontend nie trzyma tokenów Keycloak ani client secret; jeden model sesji dla kont lokalnych i SSO. Helper PKCE z bety nie jest potrzebny w przeglądarce (przenosi się do backendu).
  - Zgodne z ADR-13 i 07-auth §3.3 (rozstrzygnięte). `redirect` przekazywany jako `GET /api/v1/auth/login/keycloak?redirect=<ścieżka>` (tylko ścieżki względne).
- Strona logowania ukrywa formularz e-mail/hasło, gdy `GET /api/v1/system/config` zwraca `disablePasswordLogin: true`; link „Sign up” tylko gdy `registerEnabled`.

### 5.3 Router context i guardy

```ts
// src/routes/__root.tsx
export const Route = createRootRouteWithContext<{ auth: AuthState; queryClient: QueryClient }>()({ … })

// src/routes/_app/route.tsx
beforeLoad: async ({ context, location }) => {
  const session = await context.auth.ensureSession()   // refresh przy pierwszym wejściu
  if (!session) throw redirect({ to: '/login', search: { redirect: location.href } })
}
// src/routes/_app/admin/route.tsx
beforeLoad: ({ context }) => { if (!context.auth.user?.is_superuser) throw redirect({ to: '/' }) }
```

- `AuthState` = `{ user, ensureSession(), login(), logout(), hasRole() }`; po `login/logout` → `router.invalidate()` i `queryClient.clear()` przy wylogowaniu.
- 401 po nieudanym refresh → `logout()` lokalny + redirect na `/login?redirect=…`.

---

## 6. Architektura informacji: RAGFlow → Wawelsky Dragon

### 6.1 Nawigacja główna (kolejność = RAGFlow)

| # | RAGFlow (górny pasek) | WD SideMenu | Ikona MUI | URL | Aktywna dla | Stan w v1 |
|---|---|---|---|---|---|---|
| 1 | Home (ikona) | Home / Start | `HomeRounded` | `/` | `/` | ✅ |
| 2 | Dataset | Datasets / Bazy wiedzy | `LibraryBooksRounded` | `/datasets` | `/datasets`, `/dataset/*`, `/chunk/*` | ✅ |
| 3 | Chat | Chat / Czat | `ChatRounded` | `/chats` | `/chats`, `/chat/*` | ✅ |
| 4 | Search | Search / Wyszukiwanie | `SearchRounded` | `/searches` | `/searches`, `/search/*` | ✅ (E4) |
| 5 | Agent | Agent | `AccountTreeRounded` | `/agents` | `/agents`, `/agent/*` | flaga `FEATURE_AGENT` (strona „wkrótce”, D1) |
| 6 | Memory | Memory | `PsychologyRounded` | `/memories` | — | ukryte (`FEATURE_MEMORY=false`) |
| 7 | File | Files / Pliki | `FolderRounded` | `/files` | `/files`, `/document/*` | ✅ (E4) |
| — | awatar → `/user-setting` | Settings / Ustawienia (dół) | `SettingsRounded` | `/user-setting/model` | `/user-setting/*` | ✅ |
| — | osobna aplikacja `/admin` | Admin (dół, tylko superuser) | `AdminPanelSettingsRounded` | `/admin/users` | `/admin/*` | ✅ |
| — | Help (zewn.) | Pomoc ↗ | `HelpOutlineRounded` | `window.__ENV__.DOCS_URL` | — | ✅ |

Etykiety w `locales/*.json` (`nav.home`, `nav.datasets`, …). Wersja angielska używa **dokładnie** etykiet RAGFlow (Dataset→„Datasets” w liczbie mnogiej jest dopuszczalną zmianą; reszta 1:1).

### 6.2 Zachowane schematy URL

| RAGFlow | WD | Uwagi |
|---|---|---|
| `/datasets` | `/datasets` | |
| `/dataset/files/:id`, `/dataset/retrieval/:id`, `/dataset/logs/:id`, `/dataset/configuration/:id` | identycznie | naprawiony podwójny slash upstream |
| `/dataset/knowledge-graph/:id`, `/dataset/compilation/:id` | — | DROP (404 → redirect na `files`) |
| `/chunk/parsed/chunks?id=<kb>&doc_id=<doc>` | identycznie | |
| `/chats`, `/chat/:id?conversationId=&isNew=` | identycznie | |
| `/searches`, `/search/:id` | identycznie | |
| `/agents`, `/agent-templates`, `/agent/:id` | `/agents` (reszta w E6) | |
| `/files?folder=` | identycznie | |
| `/document/:id` | identycznie | |
| `/user-setting/{model,profile,api}` | identycznie | `data-source`, `chat-channel`, `mcp`, `team` → DROP (team w v2) |
| `/login`, `/login-next` | `/login` (+ redirect z `/login-next`) | |
| `/admin/*` (osobna aplikacja) | `/admin/{users,access,status}` w tym samym shellu | |
| `?isCreate=true` na listach | identycznie | auto-otwiera dialog tworzenia (używane z Home) |

---

## 7. Specyfikacja stron

### 7.0 Stany ekranów (U5) i warianty obowiązkowe
| Ekran | Ładowanie | Pusty | Błąd | Długie dane (fixture `visual.spec.ts`) |
|---|---|---|---|---|
| Home `/` | szkielety kart | karty tworzenia | `Alert` + ponów | nazwa bazy 120 zn. — wielokropek + `title` |
| Datasets `/datasets` | szkielety kart | `EmptyState` | `Alert` + ponów | j.w. |
| Pliki datasetu | `DataGrid loading` | „Dodaj plik” + strefa upuszczania | `Alert`; błąd uploadu per plik z przyczyną | nazwa pliku 70 zn., 150 wierszy, 390 px: nazwa + ⋮ widoczne |
| Konfiguracja datasetu | szkielet formularza | — | błąd zapisu przy polu / `Alert` | opis 512 zn. |
| Chunki | szkielet listy | „Brak chunków — sparsuj dokument” | `Alert` | chunk 4000 zn. zawinięty, tabela HTML przewijana w karcie |
| Test retrievalu | wskaźnik w przycisku „Uruchom” | „Nie uruchomiono jeszcze testu…” / „Nie znaleziono…” | `Alert` | wynik 2000 zn. |
| Czat `/chat/:id` | szkielet sesji | „Zadaj pierwsze pytanie” | ramka błędu w wiadomości z przyczyną (np. model nie obsługuje parametru) | nazwa czatu 80 zn., odpowiedź z 10 cytowaniami, cytowanie 2000 zn. → modal (U4) |
| Ustawienia → Modele | szkielet siatki | „Dodaj dostawcę” | wynik „Weryfikuj” z przyczyną | nazwa modelu 60 zn. |
| Admin → Użytkownicy | `DataGrid loading` | — | `Alert` | e-mail 60 zn. |

Warianty obowiązkowe każdego ekranu: 1280 px i 390 px, jasny i ciemny motyw, PL i EN.

Wspólne wzorce (komponenty w `src/components`):
- **`PageContainer`** (crud-dashboard): breadcrumbs, tytuł, slot akcji.
- **`ListPage`**: nagłówek (tytuł+ikona, `SearchField` z debounce 300 ms, `FilterMenu` — Owner, przycisk „+ Utwórz …”) → `Grid` kart (`size={{ xs:12, sm:6, md:4, lg:3 }}`) → `Pagination`. Stan (page, keywords, owner) w search params.
- **`ResourceCard`**: awatar (inicjały, jeśli brak obrazka), nazwa, opis / „N plików”, chip właściciela, data aktualizacji, menu ⋮ (Zmień nazwę, Usuń).
- **`EmptyState`**: duża karta z przerywaną ramką „Nie utworzono jeszcze X — Dodaj” (otwiera dialog), wariant „Nic nie znaleziono” dla pustego wyszukiwania.
- **`useDialogs().confirm()`** przed każdym usunięciem; **`useNotifications().show()`** po mutacjach (sukces/błąd z `ApiError.message`).
- **`DetailShell`**: lewe sub-menu 220 px (`List` z `ListItemButton`), nagłówek z awatarem, nazwą i statystykami.

### 7.1 `/login`
Szablon `sign-in` 1:1: `SignInContainer` (gradient), `ColorModeSelect` w prawym górnym rogu, `Card` z logo WD, nagłówek „Zaloguj się”. Pola: E-mail, Hasło (przełącznik oka), „Zapamiętaj mnie” (wydłuża TTL refresh — kontrakt z M3), przycisk „Zaloguj się”; `Divider` „lub”; przyciski kanałów OIDC; przełącznik „Nie masz konta? Zarejestruj się” (formularz: E-mail, Nazwa, Hasło) tylko gdy `registerEnabled`. „Zapomniałeś hasła?” — ukryte w v1 (brak wsparcia backendu). Walidacja inline (TanStack Form + zod). Błąd logowania → `Alert` nad formularzem z komunikatem API.

### 7.2 Home `/`
- Baner powitalny „Witaj w Wawelsky Dragon, {nickname}”.
- Sekcja **Datasets**: poziomy rząd 4 ostatnich kart + karta „Zobacz wszystkie”; pusto → karta tworzenia (`/datasets?isCreate=true`).
- Sekcja **Aplikacje**: `ToggleButtonGroup` Chat | Search | (Agent — jeśli flaga) z 4 ostatnimi kartami + „Zobacz wszystkie”.
- API: `GET /datasets?page_size=4&orderby=update_time`, `GET /chats?page_size=4`, `GET /searches?page_size=4`.

### 7.3 Datasets `/datasets`
`ListPage`. Karta: „{document_count} plików”. Dialog „Utwórz dataset”: **Nazwa*** , **Model embeddingu*** (domyślny z `/users/me/models`), **Metoda chunkowania*** (select z opisem, domyślnie General). Zapis → `POST /datasets` → nawigacja do `/dataset/files/:id`. Menu karty: Zmień nazwę (`PUT /datasets/:id {name}`), Usuń (`DELETE /datasets {ids:[id]}`).

### 7.4 Szczegóły datasetu (layout `dataset/route.tsx`)
Sub-menu: **Pliki · Test retrievalu · Logi · Konfiguracja**. Nagłówek: awatar 64 px, nazwa, „N plików · rozmiar”, „Utworzono {data}”. `GET /datasets/:id` w loaderze.

**Pliki `/dataset/files/:id`**
- Podtytuł: „Poczekaj, aż pliki zostaną sparsowane, zanim zaczniesz czat”.
- Toolbar: szukaj, filtr (Typ pliku, Status: Oczekuje/Parsowanie/Anulowano/Sukces/Błąd), przycisk „+ Dodaj plik” (menu: Prześlij plik, Utwórz pusty plik).
- `DataGrid` (checkbox selection, server-side pagination/sort):

| Kolumna | Renderer |
|---|---|
| Nazwa (sort) | ikona typu + nazwa; klik → `/chunk/parsed/chunks?id=&doc_id=` |
| Data przesłania (sort) | `create_time` |
| Włączony | `Switch` → `PATCH …/documents/:doc {enabled}` (optymistycznie) |
| Chunki | `chunk_count` |
| Metoda parsowania | `Chip` z nazwą metody; klik → dialog „Metoda chunkowania” (per dokument) |
| Status | `ParsingStatusCell`: bezczynny ▶ (parsuj) / ↻ (ponownie); w toku `LinearProgress` + `%` + ⊗ (stop); w kolejce ⏱ „W kolejce”; hover → `Popover` (początek, czas trwania, log postępu); klik → `ProcessLogDialog` |
| Akcje (hover) | Zmień nazwę, Pobierz, Usuń (zablokowane w trakcie parsowania) |

- Pasek akcji zbiorczych po zaznaczeniu: Parsuj, Anuluj, Włącz, Wyłącz, Usuń.
- `ReparseDialog` (dokument ma już chunki): „Wyczyść istniejące N chunków” (checkbox, domyślnie zaznaczony).
- `UploadDialog`: strefa drag&drop (wiele plików), lista z paskami postępu (XHR upload — `onprogress`), przełącznik „Parsuj po przesłaniu” (domyślnie włączony) → po uploadzie `POST /datasets/:id/chunks {document_ids}`.
- **Polling**: `refetchInterval` = 3 s, gdy którykolwiek dokument na stronie ma `run ∈ {RUNNING, SCHEDULE}` lub `progress ∈ (0,1)`; inaczej wyłączony. Pauza przy ukrytej karcie przeglądarki (domyślne zachowanie Query).

**Test retrievalu `/dataset/retrieval/:id`** — `Grid` 5/7:
- Lewa `Card` „Ustawienia”: Próg podobieństwa (`Slider` 0–1, 0.2), Waga podobieństwa wektorowego (0–1, 0.3), Top N (1–100, 10), [ADV] Model rerank, [ADV] Wyszukiwanie międzyjęzykowe; pole pytania (`TextField multiline`), przycisk **Uruchom**.
- Prawa `Card` „Wyniki”: „Łącznie N”, filtr dokumentów (popover z licznikami z `doc_aggs`), karty wyników: chipy „Hybrydowe / Termowe / Wektorowe %”, treść z podświetleniem (`highlight`), nazwa dokumentu.
- Puste stany: „Nie uruchomiono jeszcze testu…”, „Nie znaleziono pasujących wyników…”.
- API: `POST /api/v1/retrieval {question, dataset_ids:[id], similarity_threshold, vector_similarity_weight, page_size:top_n, rerank_id, highlight:true}` (mutacja, nie query).

**Logi `/dataset/logs/:id`** — uproszczone: karty statystyk (Wszystkie pliki, W kolejce, Przetwarzane, Błędy) z `GET /datasets/:id/ingestions/summary`; `DataGrid` zadań (ID, Plik, Typ zadania, Start, Czas, Status, „Log”) z `GET /datasets/:id/ingestions`; filtr statusu. Zakładka „Dataset logs” z RAGFlow → DROP.

**Konfiguracja `/dataset/configuration/:id`** — `Card` z formularzem (max 768 px) + prawa `Card` „O tej metodzie chunkowania” (opis metody i przykładowy obrazek z `public/chunk-methods/<method>.png`). Pola wg §8.1; sekcja „Zaawansowane” w `Accordion`. Model embeddingu zablokowany, gdy `chunk_count > 0` (tooltip z wyjaśnieniem). Przyciski Anuluj / **Zapisz** (sticky na dole). Zmiana metody chunkowania przy istniejących chunkach → `confirm()` „Dokumenty wymagają ponownego parsowania”.

### 7.5 Strona chunków `/chunk/parsed/chunks?id=&doc_id=`
Pełna szerokość (SideMenu mini), przycisk Wstecz, breadcrumbs „Datasets › {dataset} › {dokument}”. Dwa panele z przeciągalnym dzielnikiem (40/60):
- **Lewy — Podgląd**: PDF/obraz → `<iframe>`/`<img>` z `GET /api/v1/documents/:doc_id/preview` (blob + Bearer, §9.4); dla DOCX/XLSX/itd. podgląd HTML z tego samego endpointu (backend zwraca znormalizowany HTML — kontrakt z M5/M7). Podświetlenie pozycji chunku (`positions`) tylko dla PDF — w v1 dopuszczalne przewinięcie do strony (`#page=N`) zamiast ramek.
- **Prawy — Wynik chunkowania**: toolbar (Pełny tekst / Skrócony, filtr Wszystkie/Włączone/Wyłączone, szukaj, „+” nowy chunk); pasek zaznaczenia (Zaznacz stronę, Włącz, Wyłącz, Usuń); lista kart chunków (wirtualizacja przy > 200 elementach): badge typu (Tekst/Tabela/Obraz), checkbox, treść (markdown/HTML tabeli sanitizowany), `Switch` dostępności. Klik → podświetlenie/przewinięcie podglądu, dwuklik → `ChunkDialog`. Paginacja 30/stronę.
- **`ChunkDialog`** („Nowy chunk” / „Edytuj chunk”): Treść* (`TextField multiline`), Typ (read-only), **Słowa kluczowe** (`Autocomplete freeSolo multiple` → `important_keywords`), **Pytania** (jw. → `questions`, z podpowiedzią „jeśli podano pytania, embedding chunku powstaje z nich”), Włączony.
- API: `GET /datasets/:kb/documents/:doc/chunks?page&page_size&keywords&available`, `POST`/`PATCH …/chunks[/:cid]`, `PATCH …/chunks {chunk_ids, available}`, `DELETE …/chunks {chunk_ids}`.

### 7.6 Chat — lista `/chats`
`ListPage`. „Utwórz czat”: **Nazwa** + opcjonalnie **Bazy wiedzy** (v1.3, Q59; makieta SC-V13-10 w `work/wp/V13/SCENARIOS.md`; bazy bez przetworzonych plików niewybieralne z dopiskiem) → `POST /chats {name, dataset_ids?, prompt_config}` → `/chat/:id`. Menu karty: Zmień nazwę, Usuń.

### 7.7 Chat — obszar roboczy `/chat/:id?conversationId=`
Trzy kolumny (SideMenu mini):
1. **Sesje** (280 px, zwijane): awatar i nazwa czatu, ikona „Osadź na stronie” (ADV, E4), „Rozmowy (N)” + **„+”** (nowa sesja tymczasowa — utrwalana przy pierwszym pytaniu, nazwa = pierwsze 50 znaków pytania), szukaj (lokalnie), tryb zaznaczania (usuń zbiorczo — ADV). Menu sesji: **Zmień nazwę** (brakowało w RAGFlow; `PATCH /chats/:id/sessions/:sid`), Usuń.
2. **Rozmowa**: nagłówek z nazwą sesji; lista wiadomości (auto-scroll, „przewiń na dół”); wiadomość asystenta:
   - sekcja **„Myślenie…”** (`Accordion`, domyślnie zwinięta po zakończeniu, rozwinięta w trakcie streamu) z treścią `<think>`;
   - treść markdown (react-markdown + remark-gfm) ze **znacznikami cytowań** `[ID:n]` zamienionymi na małe `Chip`/superskrypt „n+1”; hover/focus → `Popover` z treścią chunku, nazwą dokumentu i procentem podobieństwa; klik w nazwę dokumentu → **szuflada podglądu** (`Drawer anchor="right"`, 560 px) z podglądem dokumentu;
   - pod odpowiedzią: chipy dokumentów źródłowych (z `doc_aggs`);
   - pasek akcji: Kopiuj, 👍/👎 (👎 → dialog z uzasadnieniem; `PUT …/messages/:mid/feedback`), Wygeneruj ponownie.
   - wiadomość użytkownika: Kopiuj.
   - Pole wprowadzania: `TextField multiline` (auto-wysokość, Enter = wyślij, Shift+Enter = nowa linia), przycisk Wyślij / **Stop** w trakcie streamu (abort `fetch`). ADV (za flagą): załączniki, przełącznik „Internet”.
3. **Ustawienia czatu** (ikona zębatki; stały `Drawer anchor="right"` 440 px): `Tabs` **Asystent · Silnik promptu · Model** (klasyczny układ RAGFlow) z polami z §8.2; Anuluj / Zapisz (`PATCH /chats/:id`).

Otwarcie z `?conversationId=` ładuje `GET /chats/:id/sessions/:sid` (wiadomości + referencje). Wiadomości z `<think>…</think>` w historii rozdzielane tym samym parserem co stream (§9.3).

### 7.8 Search — `/searches` i `/search/:id` (E4)
- Lista: `ListPage`, „Utwórz” = Nazwa → `/search/:id`.
- Aplikacja: prawy `Drawer` „Ustawienia wyszukiwania” (auto-otwarty, gdy brak datasetów) z polami §8.3.
  - **Ekran startowy**: logo, „Witaj ponownie, {nickname}”, duże pole zapytania na środku.
  - **Wyniki**: przyklejony pasek wyszukiwania; `Card` **Podsumowanie AI** (stream markdown z cytowaniami, zwijany do 208 px, „rozwiń”) — tylko gdy `summary` włączone; filtr plików (popover z licznikami), wybór rozmiaru strony, „Łącznie: N”; lista trafień (treść z podświetleniem, nazwa dokumentu → szuflada podglądu); paginacja; chipy **Powiązane wyszukiwania** (gdy `related_search`).
  - API: `POST /searches/:id/completions` (SSE), `POST /retrieval` (trafienia), `POST /chat/recommendation` (powiązane).

### 7.9 Agent `/agents` (flaga `FEATURE_AGENT`)
v1: `PageContainer` z `EmptyState` „Agenci pojawią się w kolejnej wersji” + link do dokumentacji. Pozycja w menu obecna dla znajomości (decyzja D1). E6 rozszerza tę sekcję.

**E6 (M12, WP E6-3b; spec 13 §4.6; Architekt, zmiana 26 — szkic do potwierdzenia po złocie E6-0/K18).** Formularz zamiast canvas, `@xyflow/react` nie wchodzi.

Lista `/agents` (wzór: lista czatów §7.6):
```
┌ Agenci ───────────────────────────────────────── [+ Nowy agent ▾] ┐
│ 🔎 Szukaj…                                                          │
│ ┌──────────────────────────────┐ ┌──────────────────────────────┐  │
│ │ AG  Asystent z wyszukiwarką  │ │ AG  Agent importowany …  ⚠   │  │
│ │ Retrieval · Web (SearXNG)    │ │ Nieuruchamialny: komponent   │  │
│ │ zmieniono 2 h temu        ⋮  │ │ „Switch” nieobsługiwany   ⋮  │  │
│ └──────────────────────────────┘ └──────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```
„+ Nowy agent ▾” → „Pusty” albo szablon (`GET /agents/templates`). ⋮ = Otwórz, Zmień nazwę, Usuń (potwierdzenie z nazwą).
Agent z DSL spoza podzbioru (migrowany z RAGFlow) — karta z ⚠ i przyczyną (nazwa komponentu); otwarcie pokazuje formularz tylko do odczytu + alert „Ten agent używa komponentów, których Wawelsky Dragon nie obsługuje: …”.

Edytor `/agent/:id` — dwie kolumny ≥ 1200 px (formularz | panel testowy), poniżej — zakładki „Konfiguracja” / „Test”:
```
┌ ← Agenci   Asystent z wyszukiwarką                         [Zapisz] ┐
│ Konfiguracja                             │ Test rozmowy   [Nowa rozmowa]│
│ Nazwa* [Asystent z wyszukiwarką      ]   │ ┌──────────────────────────┐│
│ Opis   [                              ]  │ │ (dymki jak w czacie,      ││
│ Model* [gpt-5.4-mini            ▾]       │ │  pod odpowiedzią lista    ││
│ Prompt systemowy*                        │ │  kroków: 🔧 Retrieval     ││
│ [ Jesteś asystentem…                ]    │ │  „3 fragmenty”, 🌐 Web    ││
│ Narzędzia                                │ │  „5 wyników” – zwinięte)  ││
│ ☑ Bazy wiedzy  [Raporty GUS ×] [+]       │ └──────────────────────────┘│
│    Top N [8]  Próg [0.2]                 │ [Zadaj pytanie…        ] [➤]│
│ ☑ Wyszukiwanie w internecie  [SearXNG▾]  │                              │
│ Maks. rund narzędzi [5]                  │                              │
│ ⓘ Zmiany działają od następnej rozmowy po zapisaniu                    │
└────────────────────────────────────────────────────────────────────────┘
```
| Pole | Znaczenie (U8) | Działa na |
|---|---|---|
| Model | model czatu z rejestru (`tool_calls` wymagane — modele bez obsługi wyszarzone z podpowiedzią) | nowe rozmowy po zapisie |
| Prompt systemowy | instrukcja agenta; bez `{knowledge}` (wiedza przychodzi z narzędzia) | jw. |
| Bazy wiedzy | narzędzie Retrieval: agent sam decyduje, kiedy przeszukać wybrane bazy; Top N / Próg jak w czacie | jw. |
| Wyszukiwanie w internecie | narzędzie web search; lista dostawców z Ustawień (admin); brak skonfigurowanego → pole wyłączone z linkiem do Ustawień | jw. |
| Maks. rund narzędzi | ile razy agent może wywołać narzędzia przed odpowiedzią (1–10, upstream `max_rounds`) | jw. |

Stany: ładowanie — szkielet kart/formularza; pusto — „Nie masz jeszcze agentów” + „Utwórz z szablonu”; błąd zapisu — komunikat K3 przy polu („component X is not supported…” → tłumaczenie PL); niezapisane zmiany przy wyjściu — dialog „Odrzucić zmiany?”; test w trakcie — przycisk ➤ zablokowany + Stop; długa nazwa — wielokropek + `title`; 390 px — jedna kolumna, zakładki Konfiguracja/Test, pole pytania przy dolnej krawędzi (jak czat, R-UI-05). Scenariusze: S6-16 + `work/wp/E6-3b/SCENARIOS.md` (Architekt przed briefem).

### 7.10 Pliki `/files?folder=` (E4)
`PageContainer` z breadcrumbs folderów, „+ Dodaj” (Prześlij plik, Nowy folder), szukaj. `DataGrid`: ☐, Nazwa (ikona; folder → wejście), Data, Rozmiar, **Datasets** (chipy powiązanych), Akcje: Połącz z datasetem (dialog multi-select → `POST /files/link-to-datasets {file_ids, kb_ids}`), Przenieś (dialog drzewa folderów), Zmień nazwę, Pobierz, Podgląd (`/document/:id`), Usuń. Akcje zbiorcze: Połącz, Przenieś, Usuń.

### 7.11 Ustawienia `/user-setting/*` (layout z sub-menu)
Sub-menu: **Dostawcy modeli · Profil · Klucze API** (Team/MCP/Data sources/Chat channels — brak).
- **Dostawcy modeli `/user-setting/model`**:
  - `Card` „Modele domyślne”: LLM*, Embedding*, Rerank, VLM (ADV — „potrzebny do parsowania PDF przez VLM”) → `PATCH /users/me/models`.
  - Lista dostawców (lewa kolumna) — w v1 **jeden generyczny typ „OpenAI-compatible / LiteLLM”** + możliwość dodania kolejnych instancji (nazwa, base URL, klucz API, **Weryfikuj**).
  - Modele instancji (prawa kolumna): `DataGrid` (nazwa, typ chat/embedding/rerank/image2text, max tokens, wymiar dla embedding, włączony) + „Dodaj model” (dialog) + „Pobierz z `/v1/models`” (import listy z bramki).
  - API: kontrakt z M4/M7 (trimmed `/providers*`, `/models`, `/models/default`) — frontend używa wyłącznie ścieżek z OpenAPI.
- **Profil**: wiersze z przyciskami Edytuj → małe dialogi: Nazwa, E-mail (tylko odczyt), Strefa czasowa (ADV), Hasło (obecne/nowe/powtórz; ukryte dla kont Keycloak). Język — w Header/OptionsMenu, zapisywany przez `PATCH /users/me {language}`.
- **Klucze API**: `Card` „API serwera” z bazowym URL (`window.location.origin + /api/v1`) i kopiowaniem; `DataGrid` kluczy (token zamaskowany `ragflow-abcd…wxyz`, utworzono, ostatnio użyto, akcje Kopiuj/Usuń); „Utwórz klucz” → dialog z pełnym tokenem i ostrzeżeniem. Link do dokumentacji API (OpenAPI UI backendu `/api/docs`).
  - **E6-2 (K17)** — pod „API serwera” druga `Card` **„Serwer MCP”** (ten sam układ co `ServerApiCard`):
    ```
    ┌ Serwer MCP ───────────────────────────────────────────────────────────┐
    │ Pozwala asystentom AI (np. Claude Desktop, Cursor) przeszukiwać Twoje │
    │ bazy wiedzy. Uwierzytelnienie: Twój klucz API (poniżej).               │
    │ Streamable HTTP  https://wd.example/mcp                       [⧉]      │
    │ SSE              https://wd.example/sse                       [⧉]      │
    │ Przykład konfiguracji klienta                                 [⧉]      │
    │ { "mcpServers": { "wawelsky-dragon": { "url": "…/mcp",               │
    │   "headers": { "Authorization": "Bearer <TWÓJ_KLUCZ_API>" } } } }      │
    │ ⓘ Serwer musi włączyć administrator (profil compose „mcp”, runbook §13).│
    └────────────────────────────────────────────────────────────────────────┘
    ```
    Adresy = `window.location.origin` + ścieżka; przykład nigdy nie wstawia prawdziwego klucza (placeholder). Stany: brak stanu ładowania/błędu (treść statyczna);
    długi adres — wielokropek + `title`, przycisk kopiowania zawsze widoczny; 390 px — bloki pod sobą, przykład JSON przewijany poziomo **wewnątrz** ramki (U3); ciemny motyw — blok kodu z kontrastem U9.

### 7.12 Admin `/admin/*` (superuser)
Sub-menu: **Użytkownicy · Dostęp do asystentów · Status systemu**.
- **Użytkownicy**: `DataGrid` (E-mail, Nazwa, Rola, Źródło: local/keycloak, Aktywny `Switch`, Utworzono), akcje: Szczegóły, Zmień hasło (lokalne), Nadaj/odbierz admina, Klucze API (dialog jak w hub-compat `ApiKeysDialog`), Usuń; „Nowy użytkownik”. API: `/api/wd/v1/users*` i `/api/wd/v1/users/{id}/api-keys` (nadzbiór user-api; 02-api §12).
- **Dostęp do asystentów**: wybór e-maila → lista czatów z checkboxami + znacznik „nadany automatycznie” (`created_by` = marker auto-provisioningu klienta). API: `/api/wd/v1/access/assistants*` (kanoniczna lista tras admina: 02-api §12).
- **Status systemu**: karty (DB, storage, worker heartbeat — liczba aktywnych workerów, kolejka: queued/running/dead, wersja) z `/api/wd/v1/stats` + `/api/v1/system/healthz`; odświeżanie co 10 s.
- **Integracje** (E4, M9): lista integracji SharePoint, test połączenia, sync, przebiegi i zdarzenia — UI wzorowany na hub-compat `knowledge-base/integrations.tsx`; umieszczone w Admin.

### 7.13 `/document/:id`
Pełnoekranowy podgląd pliku z menedżera plików (ten sam komponent `DocumentPreview` co szuflada i strona chunków).

### 7.14 Metadane dokumentów (E6, M10, WP E6-1b; spec 13 §2.5; Architekt, zmiana 26 — szkic do potwierdzenia po złocie E6-0)
Model danych jak upstream v0.27.2: `documents.meta_fields` = słownik `klucz → wartość | lista wartości`; konfiguracja pól datasetu = lista `{key, description, enum?}` (`common/metadata_utils.py` `_is_metadata_list`); operatory filtra: `=`, `≠`, `>`, `<`, `≥`, `≤`, `contains`, `not contains`, `start with`, `end with`, `in`, `not in`, `empty`, `not empty`; daty `RRRR-MM-DD` porównywane jako daty.

**(a) Konfiguracja datasetu — sekcja „Metadane”** (pod „Metoda chunkowania”, przed ADV):
```
Metadane
  Auto-metadane  [○──]   ⓘ Model indeksujący odczyta z każdego pliku wartości pól poniżej.
                            Działa przy następnym parsowaniu — istniejące pliki: „Parsuj ponownie”.
  ┌ Pola ──────────────────────────────────────────────────────────── [+ Pole] ┐
  │ Klucz*        Opis (dla modelu)                    Dozwolone wartości      │
  │ [rok      ]   [Rok, którego dotyczą dane       ]   [                ]  🗑  │
  │ [region   ]   [Województwo                      ]   [mazowieckie ×][+] 🗑  │
  └─────────────────────────────────────────────────────────────────────────────┘
```
| Pole | Znaczenie (U8) | Działa na |
|---|---|---|
| Auto-metadane (`parser_config.enable_metadata`) | po chunkowaniu model indeksujący (`parser_config.llm_id`) wypełnia pola z listy; błąd modelu nie przerywa parsowania (wpis w logu zadania) | **tylko nowe parsowania**; po zapisie z istniejącymi plikami — to samo pytanie „Zastosować do istniejących plików?” co w R-CFG-01 (ponowne parsowanie) |
| Klucz | nazwa pola w `meta_fields` (unikalna, bez spacji na końcach) | filtr i edycja ręczna |
| Opis | podpowiedź dla modelu, co wpisać | auto-metadane |
| Dozwolone wartości (`enum`) | gdy niepuste — model wybiera tylko z listy; filtr manualny pokazuje select | jw. |
Przełącznik wyłączony, gdy lista pól pusta (podpowiedź „Dodaj co najmniej jedno pole”). Zmiana listy pól **nie** usuwa istniejących wartości w dokumentach.

**(b) Lista dokumentów** — kolumna „Metadane” (≥ **1536 px**: do 2 chipów `klucz: wartość` + „+N”, karta „Pliki” `Container maxWidth=xl`; < 1536 px ukryta, dostępna z ⋮ → „Metadane” — poprawka zmiana 30 po E6-1b: przy 1200–1535 px kolumna zjadała „Nazwę”). ⋮ → „Metadane” otwiera **szufladę** (U4) z tabelą klucz/wartość: edycja inline, „+ Pole”, 🗑, Zapisz (`PATCH …/documents/{id}` `meta_fields`), znacznik źródła wartości nie jest pokazywany (upstream go nie ma). Pasek nad tabelą: „Filtr metadanych” → ten sam kreator warunków co (c), zawęża listę (`metadata_condition` na `GET …/documents`), aktywny filtr widoczny jako chip „Metadane: 2 warunki ×”.

**(c) Kreator warunków (komponent wspólny)** — w szufladzie Ustawień czatu (zakładka Asystent, sekcja ADV „Filtr metadanych”), w ustawieniach Search i w teście retrievalu:
```
Filtr metadanych   ( Wyłączony | Ręczny | Automatyczny | Półautomatyczny )
  Ręczny:  Spełnione [wszystkie ▾] warunki
           [rok ▾] [≥ ▾] [2020        ]  🗑
           [region ▾] [in ▾] [mazowieckie ×][+]  🗑
           [+ Warunek]
  Automatyczny:    ⓘ Model sam ułoży filtr z pytania na podstawie metadanych wybranych baz.
  Półautomatyczny: Klucze, po których model może filtrować: [rok ×] [region ×] [+]
```
| Tryb | Znaczenie (U8) | Uwaga |
|---|---|---|
| Wyłączony | brak `meta_data_filter` | domyślnie |
| Ręczny (`manual`) | stałe warunki, dokument przechodzi, gdy spełnia wszystkie / którykolwiek | klucze podpowiadane z `GET …/metadata/summary` wybranych baz; operatory `empty`/`not empty` bez pola wartości |
| Automatyczny (`auto`) | przy każdym pytaniu model generuje warunki | dodatkowe wywołanie modelu na pytanie (koszt/czas — w podpowiedzi) |
| Półautomatyczny (`semi_auto`) | jak auto, ale tylko po wskazanych kluczach | — |
Zmiana działa od następnego pytania (czat/Search), nie wymaga parsowania.

**Stany (U5)**: brak zdefiniowanych pól i brak metadanych w dokumentach → kreator pokazuje „Bazy nie mają metadanych — zdefiniuj pola w Konfiguracji datasetu” + link; filtr zawęził do 0 dokumentów → czat odpowiada `empty_response`, w teście retrievalu komunikat „Filtr metadanych wykluczył wszystkie dokumenty”; błąd zapisu metadanych → komunikat przy polu, wartości nie znikają; długie klucze/wartości → wielokropek + `title` (U2), w szufladzie zawijanie; 390 px → kreator w jednej kolumnie (klucz / operator / wartość pod sobą), szuflada na pełną szerokość; ciemny motyw — chipy i pola z kontrastem U9.
Scenariusze: S6-15 + `work/wp/E6-1b/SCENARIOS.md` (Architekt przed briefem: auto-metadane na realnym korpusie PL — np. roczniki GUS z polem `rok`, filtr ręczny w czacie, filtr na liście dokumentów, wariant 390 px/ciemny).

### 7.15 Eksport i import bazy wiedzy (E7, WP E7-2; spec 14, kontrakt K19 §3; Architekt, zmiana 28)
Wejścia: lista baz wiedzy `/datasets` — ⋮ przy karcie/wierszu datasetu → „Eksportuj” (widoczne tylko dla właściciela i superusera — `tenant_id == me` albo `is_superuser`);
przycisk „Importuj” obok „Utwórz bazę wiedzy” (każdy zalogowany). Zadania w toku pokazuje **pasek zadań** (ten sam komponent dla eksportu i importu) pod nagłówkiem listy.

**(a) Dialog „Eksportuj bazę wiedzy”** (Dialog MUI, szer. 560 px; < 600 px pełny ekran):
```
Eksportuj „Rocznik GUS 2024”                                          ✕
  Do paczki trafią:  3 pliki · 7 251 chunków · ok. 74 MB
  [■──] Dołącz wektory   ⓘ Import na instalacji z tym samym modelem embeddingów
                           (text-embedding-3-small, 1536) nie przelicza wektorów.
                           Bez wektorów paczka jest mniejsza (ok. 31 MB), ale import
                           przeliczy embeddingi (koszt i czas).
  Paczka nie zawiera kluczy, użytkowników, czatów ani ustawień modeli.
                                                   [Anuluj] [Eksportuj]
```
Po „Eksportuj” dialog się zamyka, w pasku zadań pojawia się wiersz (b). Szacunek > `max_bytes` → przycisk nieaktywny + „Paczka przekroczy limit 2 GB (WD_EXPORT_MAX_BYTES)”.
409 `export_in_progress` → zamiast dialogu przewinięcie do istniejącego wiersza w pasku.

**(b) Pasek zadań** (wiersz na zadanie, odpytywanie `GET /api/wd/v1/tasks/{id}` co 2 s, zadania pamiętane w `localStorage` do końca + 24 h):
```
⤓ Eksport „Rocznik GUS 2024”   Chunki 3 000/7 251  [████████░░░░] 41%   [Stop]
⤒ Import „Rocznik GUS 2024”    Gotowe — 3 pliki, 7 251 chunków           [Otwórz] [✕]
⤓ Eksport „Umowy”              Gotowe · 12 MB · link ważny do 13.10 23:10 [Pobierz] [Kopiuj link] [✕]
⤒ Import „Raporty”             Błąd: Paczka uszkodzona (suma kontrolna)  [Szczegóły] [✕]
```
**(c) Dialog „Importuj bazę wiedzy”** — krok 1 wybór pliku (przycisk „Wybierz plik” + strefa upuszczania; akceptuje `.wdkb.zip`; plik 0 B / nieczytelny → R-ING-03),
pasek wysyłania „Wysłano 24/74 MB” z „Anuluj” (DELETE sesji); po przerwaniu połączenia automatyczne wznowienie (3 próby, potem „Wznów”); krok 2 podsumowanie:
```
Importuj bazę wiedzy                                                   ✕
  Paczka: Rocznik GUS 2024 · 3 pliki · 7 251 chunków · z wektorami
          utworzona 12.10.2026 w Wawelsky Dragon 1.3.0
  Nazwa*  [Rocznik GUS 2024 (import 2026-10-13)]   ⚠ Nazwa „Rocznik GUS 2024” jest zajęta
  Model embeddingów  [text-embedding-3-small (1536) ▾]
     ✔ Zgodny z paczką — wektory zostaną wczytane bez przeliczania.
     (wariant niezgodny) ⚠ Paczka używa „bge-m3 (1024)”. Wszystkie chunki zostaną
       przeliczone wybranym modelem: 7 251 chunków, ok. 1,9 mln tokenów.
                                                    [Anuluj] [Importuj]
```
Walidacja nieudana (`state=invalid`) → krok 2 zastąpiony listą błędów (komunikaty z API) + „Wybierz inny plik”. Po „Importuj” dialog się zamyka → wiersz w pasku;
po `done` „Otwórz” prowadzi do datasetu. `name_conflict` → błąd pod polem Nazwa z `suggested_name` do jednego kliknięcia.

| Pole / akcja | Znaczenie (U8) | Działa na |
|---|---|---|
| Dołącz wektory (`include_vectors`, domyślnie wł.) | wektory z paczki pozwalają pominąć embedding przy imporcie na zgodnym modelu | tylko ta paczka |
| Nazwa (import) | nazwa nowej bazy; domyślnie z paczki, przy kolizji z sufiksem „(import RRRR-MM-DD)” | nowa baza; istniejące bez zmian (scalanie poza v1) |
| Model embeddingów (import) | model wektorów nowej bazy; zgodny = ta sama nazwa i wymiar co paczka → bez przeliczania | nowa baza |
| Stop | przerywa zadanie; import — częściowa baza jest usuwana, eksport — paczka nie powstaje | zadanie |
| Pobierz / Kopiuj link | link działa 24 h bez logowania (można przekazać — traktuj jak hasło) | paczka |

**Stany (U5)**: ładowanie podsumowania (szkielet), pusty pasek (niewidoczny), błąd sieci w uploadzie (wznowienie), długie nazwy (ellipsis + tooltip),
390 px (dialogi pełnoekranowe, pasek zadań: nazwa w 1. linii, postęp i akcje w 2.), ciemny motyw. Scenariusze: `docs/scenarios/eksport-import.md` + `work/wp/E7-2/SCENARIOS.md`.

---

## 8. Inwentarz pól formularzy (KEEP / ADV / DROP)

**To jest źródło prawdy, jakie pola istnieją w UI.** KEEP = widoczne; ADV = w akordeonie „Zaawansowane”; DROP = brak w UI (API nadal przyjmuje i zwraca wartość — nie kasujemy danych). Nazwy kluczy = nazwy API v0.27.

### 8.1 Konfiguracja datasetu (`PUT /datasets/:id`)

| Klucz | Etykieta (pl / en) | Kontrolka | Domyślnie | Werdykt |
|---|---|---|---|---|
| `name` | Nazwa* / Name | text | — | KEEP |
| `description` | Opis / Description | textarea (512) | '' | KEEP |
| `avatar` | Awatar | upload | null | DROP (inicjały) |
| `language` | Język / Language | select | `Polish`/`English` wg locale | ADV |
| `permission` | Uprawnienia / Permissions | radio Tylko ja / Zespół | `me` | ADV |
| `embedding_model` | Model embeddingu* | select modeli typu embedding | domyślny użytkownika | KEEP (zablokowany gdy `chunk_count>0`) |
| `pagerank`, `parser_config.tag_kb_ids`, `topn_tags` | — | — | — | DROP |
| `parse_type`, `pipeline_id` | — | — | — | DROP |
| `chunk_method` | Metoda chunkowania* | select: General, Q&A, Manual, Table, Paper, Book, Laws, Presentation, One | `naive` | KEEP |
| `parser_config.layout_recognize` | Parser PDF | select: Auto (tekst→OCR/VLM wg jakości), Tylko tekst, VLM | Auto | KEEP (VLM wymaga modelu VLM) — wartości mapowane na strategie M5 |
| `parser_config.chunk_token_num` | Rekomendowany rozmiar chunku (tokeny) | slider 64–2048 | 512 | KEEP (General, presety) |
| `parser_config.delimiter` | Separator tekstu | text z podglądem „Dzieli na:” | `\n` | KEEP (General) |
| `parser_config.overlapped_percent` | Nakładanie (%) | slider 0–30 | 0 | ADV |
| `parser_config.enable_children` / `children_delimiter` | Chunki potomne do wyszukiwania | switch + text | false / `\n` | ADV (tylko gdy M5 wspiera parent-child; inaczej ukryte) |
| `parser_config.html4excel` | Excel jako HTML | switch | false | ADV |
| `parser_config.auto_keywords` | Liczba słów kluczowych | slider 0–30 | 0 | ADV |
| `parser_config.auto_questions` | Liczba automatycznych pytań | slider 0–10 | 0 | ADV |
| `parser_config.llm_id` | Model indeksujący | select chat | domyślny | ADV |
| `parser_config.table_column_mode/roles` | Tryb kolumn / role kolumn | radio + select per kolumna | auto / both | ADV (tylko Table) |
| `enable_metadata` + lista pól | Auto-metadane / Metadane | switch + edytor pól | false / [] | KEEP od E6 (§7.14 a) |
| `image_table_context_window`, `entity_types`, `raptor.*`, `graphrag.*`, `connectors`, parsery MinerU/Paddle | — | — | — | DROP |

**Dialog „Metoda chunkowania” per dokument** (`PATCH …/documents/:doc {chunk_method, parser_config}`): metoda, parser PDF, rozmiar chunku, separator; ADV: zakres stron (`pages`, PDF), rozmiar zadania (`task_page_size`, 1–128, 12).

**Test retrievalu**: próg 0.2 (KEEP), waga wektorowa 0.3 (KEEP), Top N 10 (KEEP), rerank (ADV), kandydaci rerank (DROP — stałe 64), międzyjęzykowe (ADV), filtr metadanych (DROP w v1; od E6 — ADV, tylko tryb ręczny, §7.14 c).

### 8.1a Znaczenie pól, które myliły użytkownika (U8 — wymagania dla WP poprawek Q34)
| Pole | Co naprawdę robi | Na co działa | Co UI musi powiedzieć |
|---|---|---|---|
| Konfiguracja datasetu: metoda chunkowania, Parser PDF, zakres stron | wartości kopiowane do dokumentu przy uploadzie (`parser_config` dokumentu) | **tylko nowe pliki**; istniejące — dopiero po zmianie w dialogu „Metoda chunkowania” dokumentu (albo akcji „zastosuj do istniejących i parsuj ponownie”) | `helperText` „Dotyczy nowych plików” + po zapisie przy istniejących dokumentach: pytanie „Zastosować do N istniejących plików i sparsować ponownie?” |
| Parser PDF = model wizji/OCR | nazwa modelu `image2text` z rejestru (nie literał „VLM”) | parsowanie PDF/obrazów | lista modeli `image2text`; brak modelu → link do Ustawień |
| Zakres stron (`pages`) | strony PDF brane do parsowania | dokument (i nowe pliki, gdy ustawione w datasecie) | format `1-10, 20-30`, walidacja |
| Model: „Max tokens” w dialogu modelu | **okno kontekstu** (budżet promptu czatu ×0,95), nie limit odpowiedzi | każdy czat używający modelu | etykieta „Okno kontekstu (tokeny)” + edycja istniejącego modelu (nie tylko usuń) |
| Instancja dostawcy: równoległe zapytania | liczba jednoczesnych wywołań wizji/OCR/embeddingów do tego endpointu | kolejne zadania bez restartu | pole „Równoległe zapytania” (1–32) z podpowiedzią o limitach dostawcy/VRAM |

#### Makiety poprawek Q34 (E5-H8c/E5-H8d, Architekt 2026-10-10)
**Dialog „Edytuj model”** (nowy; ✎ w wierszu modelu w `InstanceModelsGrid`, obok 🗑). „Dodaj model” ma te same dwa pola liczbowe.
```
┌ Edytuj model: gpt-5.4-mini ─────────────────────────── ✕ ┐
│ Typ: Czat (nie można zmienić)                              │
│ Okno kontekstu (tokeny)   [ 128000      ]                  │
│   Ile tokenów (pytanie + historia + fragmenty bazy) model  │
│   przyjmuje naraz. Więcej = więcej fragmentów w odpowiedzi.│
│   Sprawdź w dokumentacji dostawcy. Dotyczy wszystkich      │
│   czatów z tym modelem od następnego pytania.              │
│ Równoległe zapytania      [ 24 ]  (puste = domyślnie 3)    │   ← tylko typ wizja i embedding
│   Ile stron/partii worker wysyła do modelu jednocześnie.   │
│   Więcej = szybciej, ale wymaga limitów dostawcy (RPM) lub │
│   VRAM serwera OCR. Od następnego zadania, bez restartu.   │
│                                   [Anuluj]  [Zapisz]       │
└────────────────────────────────────────────────────────────┘
```
Stany: zapis w toku → „Zapisz” z wskaźnikiem i nieaktywny (U7); błąd API → `Alert` w dialogu z `message`, pola zostają;
walidacja: okno kontekstu liczba ≥ 1024, równoległe 1–32 (błąd przy polu). Kolumna siatki „Max tokens” → „Okno kontekstu”.
Zapis: `PATCH …/models/{model} {max_tokens, extra}` (K13 poprawka 2026-10-10 — pełne `extra`).

**Konfiguracja datasetu przy istniejących dokumentach** (R-CFG-01): pod polami „Metoda chunkowania”, „Parser PDF”, „Zakres stron”
`helperText` „Dotyczy nowych plików. Istniejące: »Zastosuj do istniejących« przy zapisie albo ⋮ → Metoda chunkowania przy pliku.”
Po „Zapisz”, gdy zmieniono któreś z tych pól i dataset ma N ≥ 1 dokumentów:
```
┌ Zastosować zmiany do istniejących plików? ─────────────── ┐
│ Zmieniono: Parser PDF, Zakres stron.                        │
│ Dataset ma 3 pliki sparsowane starą konfiguracją.           │
│ „Zastosuj i parsuj ponownie” nadpisze ustawienia tych       │
│ plików i usunie ich obecne chunki (także edytowane ręcznie).│
│        [Tylko nowe pliki]   [Zastosuj i parsuj ponownie (3)]│
└─────────────────────────────────────────────────────────────┘
```
„Zastosuj…” = dla każdego dokumentu `PATCH …/documents/{id} {chunk_method, parser_config}` (zmienione klucze scalone z konfiguracją
dokumentu) + jedno `POST …/datasets/{id}/chunks {document_ids}`; postęp „Zastosowano 2/3”, błąd per plik w powiadomieniu.
Dialog „Metoda chunkowania” pliku pokazuje **faktyczną** konfigurację dokumentu (parser PDF, zakres stron), nie datasetu.

**Upuszczony plik nieczytelny** (R-ING-03, U10): plik 0 B z upuszczenia nie trafia do kolejki; w strefie upuszczania `Alert` ostrzeżenie:
„Nie można odczytać pliku »raport.pdf« (0 B). Przeglądarka nie ma dostępu do tego katalogu — użyj »Wybierz pliki« albo nadaj
przeglądarce dostęp do katalogu (np. Flatpak: uprawnienie do plików).” Pozostałe upuszczone pliki trafiają do kolejki normalnie.

### 8.2 Asystent czatu (`PATCH /chats/:id`) — trzy zakładki

**Asystent**

| Klucz | Etykieta | Kontrolka | Domyślnie | Werdykt |
|---|---|---|---|---|
| `icon` | Awatar | upload | '' | ADV |
| `name` | Nazwa asystenta* | text | — | KEEP |
| `description` | Opis | textarea | '' | KEEP |
| `dataset_ids` | Bazy wiedzy | multi-select (tylko datasety z tym samym modelem embeddingu i `chunk_count>0`; pozostałe wyszarzone z tooltipem) | [] | KEEP |
| `prompt_config.prologue` | Powitanie | textarea | „Cześć! Jestem Twoim asystentem. W czym mogę pomóc?” | KEEP |
| `prompt_config.empty_response` | Odpowiedź przy braku wyników | textarea | '' | KEEP |
| `prompt_config.quote` | Pokazuj cytowania | switch | true | KEEP |
| `prompt_config.keyword` | Analiza słów kluczowych | switch | false | ADV |
| `prompt_config.web_search_provider` + klucz | Wyszukiwanie w internecie | select (1 dostawca) + hasło | brak | ADV (za flagą, E6) |
| `meta_data_filter` | Filtr metadanych | kreator §7.14 c | wyłączony | ADV od E6 |
| `prompt_config.tts`, `reference_metadata` | — | — | — | DROP |

**Silnik promptu**

| Klucz | Etykieta | Kontrolka | Domyślnie | Werdykt |
|---|---|---|---|---|
| `prompt_config.system` | Prompt systemowy* (musi zawierać `{knowledge}`, gdy wybrano bazy) | textarea 8 wierszy + walidacja | domyślny z backendu | KEEP |
| `similarity_threshold` | Próg podobieństwa | slider 0–1 | 0.2 | ADV |
| `vector_similarity_weight` | Waga podobieństwa wektorowego | slider 0–1 | 0.3 | ADV |
| `top_n` | Top N | slider 1–30 | 8 | ADV |
| `rerank_id` | Model rerank | select, czyszczalny | '' | ADV |
| `prompt_config.cross_languages` | Wyszukiwanie międzyjęzykowe | multi-select | [] | ADV |
| `prompt_config.refine_multiturn` | Optymalizacja wieloturowa | switch | false | ADV |
| `rerank_candidates_count`, `parameters`, `reasoning`, `use_kg`, `toc_enhance`, `top_k` | — | — | — | DROP |

**Model**

| Klucz | Etykieta | Kontrolka | Domyślnie | Werdykt |
|---|---|---|---|---|
| `llm_id` | Model | select chat | domyślny | KEEP |
| `llm_setting.parameter` | Kreatywność | select Improwizacja / Precyzja / Balans / Własne | Precyzja | KEEP |
| `temperature`, `top_p`, `presence_penalty`, `frequency_penalty`, `max_tokens` (+ `*_enabled`) | … | switch + slider | wg presetu | ADV (odblokowane przy „Własne”) |
| `llm_setting.thinking` | — | — | — | DROP |

Presety (jak RAGFlow): Improwizacja t 0.8 / p 0.9 / freq 0.1 / pres 0.1; Precyzja t 0.2 / 0.75 / 0.5 / 0.5; Balans t 0.5 / 0.85 / 0.3 / 0.2; max tokens 4096.

### 8.3 Aplikacja wyszukiwania (`PUT /searches/:id`)

| Klucz | Etykieta | Kontrolka | Domyślnie | Werdykt |
|---|---|---|---|---|
| `name`, `description` | Nazwa*, Opis | text | — | KEEP |
| `search_config.kb_ids` | Bazy wiedzy* (≥1) | multi-select | [] | KEEP |
| `similarity_threshold`, `vector_similarity_weight` | … | slider | 0.2 / 0.3 | ADV |
| `use_rerank` + `rerank_id` | Model rerank | switch + select | off | ADV |
| `summary` | Podsumowanie AI | switch | false | KEEP |
| `llm_setting.llm_id` | Model (wymagany przy podsumowaniu) | select | '' | KEEP |
| `llm_setting.parameter` | Kreatywność | select presetu | Precyzja | ADV |
| `related_search` | Powiązane wyszukiwania | switch | false | KEEP |
| `query_mindmap`, `meta_data_filter`, `web_search`, `use_kg`, `highlight`, `keyword`, `cross_languages`, `top_k`, `rerank_candidates_count` | — | — | — | DROP |

### 8.4 Pozostałe
- **Modele domyślne**: `llm_id` KEEP, `embd_id` KEEP, `rerank_id` KEEP (opcjonalny), `img2txt_id` ADV, `asr_id`/`tts_id` DROP. Instancja dostawcy: nazwa, base URL, klucz API, Weryfikuj — KEEP; pola specyficzne dla Bedrock/Azure/AIMLAPI — DROP.
- **Profil**: nazwa KEEP, hasło KEEP (konta lokalne), strefa czasowa ADV, awatar DROP, język KEEP (w menu).
- **Upload**: „Parsuj po przesłaniu” KEEP; tryb kolumn Table ADV.

---

## 9. Klient API, SSE i stan serwera

### 9.1 Klient REST (`src/api/client.ts`)
- `createClient<paths>({ baseUrl: env.API_BASE ?? '' })` z openapi-fetch; middleware:
  1. `onRequest`: `Authorization: Bearer <access>`; `Accept-Language` z i18n.
  2. `onResponse` 401 → jednorazowe `refresh()` (współdzielony Promise) → powtórzenie żądania; drugi 401 → `logout`.
- **Koperta RAGFlow** (`envelope.ts`): odpowiedź `{code, message, data}` → jeśli `code !== 0` rzuć `ApiError(code, message, httpStatus)`, inaczej zwróć `data`. Frontend **zawsze sprawdza `code`**, bo backend zachowuje semantykę RAGFlow „HTTP 200 + code≠0” na `/api/v1`. Endpointy `/api/wd/v1` zwracają tę samą kopertę (kontrakt z M7).
- Listy: helper `unwrapList(endpoint, data)` zna kształt per endpoint (`data[] + total_datasets`, `{docs,total}`, `{chats,total}`, `{chunks,doc,total}`…) — tabela kształtów generowana z tej samej specyfikacji co prezentery M7 (patrz 02-api.md). Zwraca `{ items, total }`.
- Upload plików: `XMLHttpRequest` (postęp `upload.onprogress`) z tym samym tokenem i obsługą 401.

### 9.2 TanStack Query
- `staleTime` domyślnie 30 s, `retry` 1 dla query (0 dla 4xx), mutacje bez retry.
- Klucze: `['datasets', 'list', params]`, `['datasets', id]`, `['documents', datasetId, params]`, `['chunks', datasetId, docId, params]`, `['chats', …]`, `['sessions', chatId]`, `['session', chatId, sid]`, `['models', …]`, `['me']`.
- Mutacje inwalidują minimalny zakres (`queryClient.invalidateQueries({ queryKey: ['documents', datasetId] })`); przełączniki (Enable) z aktualizacją optymistyczną i rollbackiem.
- Loader tras: `ensureQueryData` dla danych potrzebnych do pierwszego renderu (szczegóły datasetu, czatu) — reszta w komponentach z `useQuery` (spinner/`Skeleton`).

### 9.3 Streaming czatu (`src/lib/sse.ts`, `features/chat-stream`)
Kontrakt SSE (M6/M7, bajtowo jak RAGFlow): linie `data:{json}` (bez spacji), ramki `{"code":0,"message":"","data":{answer, reference, final, id, session_id, start_to_think?, end_to_think?}}`, terminator `data:{"code":0,"data":true}`, błąd `{"code":500,"message":…,"data":{"answer":"**ERROR**: …"}}`.

```ts
// src/lib/sse.ts — czysta funkcja, 100% testów jednostkowych
export async function* readSse(res: Response, signal: AbortSignal): AsyncGenerator<SseFrame> { … }
// eventsource-parser; toleruje "data:" z i bez spacji, CRLF, ramki podzielone między chunkami,
// ostatnią linię bez \n; ignoruje "event:"/"id:"/komentarze.

// features/chat-stream/useChatStream.ts
reduce(state, frame):
  data === true                → done
  code !== 0                   → error(message)
  data.start_to_think          → mode = 'think'
  data.end_to_think            → mode = 'answer'
  typeof data.answer === 'string' → (mode==='think' ? thinking : answer) += data.answer   // DELTY
  data.reference?.chunks niepuste → reference = normalize(data.reference)                  // ostatnia niepusta wygrywa
  data.session_id              → sessionId (nowa sesja)
```
- Wysyłka: `POST /api/v1/chats/{chat_id}/completions {question, session_id, stream:true}` przez `fetch` z `AbortController` (Stop). Przy `legacy`/skumulowanym tekście — nieużywane przez nasz UI.
- Fallback: jeśli model nie emituje markerów, a tekst zawiera `<think>…</think>` inline — `splitThink(text)` (regex jak w hub-compat: `^\s*<think>([\s\S]*?)<\/think>\s*([\s\S]*)$`), także dla historii sesji.
- **Cytowania** (`src/lib/citations.ts`): tokenizacja odpowiedzi na segmenty tekst | `[ID:n]` (0-based, indeks w `reference.chunks` po `Object.values()` gdy obiekt), bez psucia bloków kodu i tabel GFM; nieprawidłowy indeks → znacznik pomijany (nie crash). Renderowane jako komponent w `react-markdown` (`components` + plugin rehype zamieniający tekstowe znaczniki na element).
- Po `done`: `invalidateQueries(['sessions', chatId])` (nazwa/`update_time`), wiadomość dopisana do cache sesji bez refetchu.

### 9.4 Pobieranie i podgląd plików (`src/lib/download.ts`)
Wzorzec z bety: `window.open('', '_blank')` **synchronicznie** w handlerze kliknięcia (blokada popupów), potem `fetch` z Bearer → `Blob` → dla `text/*` wymuszenie `charset=utf-8` w typie bloba (inaczej polskie znaki jako Latin-1) → `URL.createObjectURL` → ustawienie `location` otwartego okna; `revokeObjectURL` po 60 s. Pobieranie jako plik: `Content-Disposition` → nazwa (`filename*=UTF-8''…`).

---

## 10. i18n, dostępność, wydajność

### 10.1 i18n
- i18next + react-i18next, zasoby `src/locales/{pl,en}.json` ładowane przez `import.meta.glob` (lazy per język); domyślny język z `users/me.language` → `navigator.language` → `pl`.
- Klucze płaskie z przestrzeniami (`datasets.create.title`); **zakaz literałów w JSX** (reguła ESLint `i18next/no-literal-string` lub własna w trybie `jsx-text-only`).
- **Test kompletności** (`src/i18n/locales.test.ts`): zbiory kluczy `pl` i `en` identyczne, brak pustych wartości, placeholdery `{{x}}` zgodne między językami.
- Daty i liczby: `Intl` przez `format.ts` (strefa z profilu użytkownika).

### 10.2 Dostępność (WCAG 2.1 AA jako cel)
- Kontrast palety sprawdzony w obu trybach (test jednostkowy na tokenach motywu: kontrast ≥ 4.5:1 dla tekstu).
- Każdy `IconButton` z `aria-label` (i18n); popovery cytowań otwierane też z klawiatury (focus) i zamykane Esc; `LinearProgress` z `aria-valuenow`; strefa uploadu dostępna przyciskiem.
- Nawigacja SideMenu jako `nav` z `aria-current="page"`; skip-link „Przejdź do treści”.
- Testy: `@axe-core/playwright` w scenariuszach e2e (0 naruszeń krytycznych).

### 10.3 Wydajność
- `tanstackRouter({ target:'react', autoCodeSplitting: true })` — **w buildzie i w dev** (Vite 8); gdyby HMR znów był niestabilny (pułapka z bety), wyłączyć tylko w dev.
- Budżet: początkowy JS ≤ 350 kB gzip (MUI + router + query); ciężkie zależności (react-markdown, DataGrid, @xyflow) tylko w chunkach tras, które ich używają.
- Listy > 200 elementów wirtualizowane (DataGrid ma wbudowaną; lista chunków — `@tanstack/react-virtual` jeśli potrzebne).
- Obrazy chunków lazy (`loading="lazy"`), miniatury z `/thumbnails`.

---

## 11. Testy i scenariusze S6

### 11.1 Unit / komponentowe (Vitest 5 + RTL + MSW)
- Środowisko `jsdom`; `msw` z handlerami generowanymi z przykładów OpenAPI (`src/test/handlers.ts`); `renderWithProviders()` (theme, i18n, QueryClient bez retry, router testowy z `createMemoryHistory`).
- **Obowiązkowe testy** (logika czysta, 100% gałęzi): `lib/sse.ts` (ramki podzielone, bez spacji/ze spacją, CRLF, błąd, terminator), `lib/citations.ts` (0-based, obiekt vs tablica, brak indeksu, w bloku kodu), reducer strumienia (think/answer/reference), `api/envelope.ts`, `unwrapList`, `download.ts` (charset), formatery, guardy tras, `featureFlags`.
- Komponenty: `ParsingStatusCell` (wszystkie stany), `UploadDialog` (postęp, parse-on-upload), `ChatComposer` (Enter/Shift+Enter/Stop), `CitationChip` (popover na hover i focus), `ChunkDialog` (walidacja), formularze konfiguracji (pola ADV ukryte do rozwinięcia, embedding zablokowany przy chunkach).
- **Progi pokrycia** (vitest `coverage.thresholds`): `src/lib/**`, `src/api/**`, `src/features/**` — lines/functions/statements ≥ 80%, branches ≥ 75%; `src/routes/**` i `src/theme/**` wyłączone z progu (pokrywane e2e). Konfiguracja w [10-testy-jakosc.md](10-testy-jakosc.md).

### 11.2 E2E (Playwright, `docker-compose.test.yml` + `fake-llm`)
Scenariusze **S6** („użytkownik RAGFlow odnajduje się”) — każdy to osobny plik `e2e/sNN-*.spec.ts`, uruchamiany na świeżej bazie z seedem (admin + modele wskazujące na fake-llm):

| ID | Scenariusz | Kroki i asercje |
|---|---|---|
| S6-01 | Logowanie i nawigacja | login lokalny → Home; SideMenu ma pozycje w kolejności Home, Datasets, Chat, Search, (Agent), Files, Settings; każda pozycja otwiera stronę bez błędów konsoli; wylogowanie → `/login`; F5 na chronionej trasie po zalogowaniu odtwarza sesję (refresh cookie) |
| S6-02 | Utworzenie datasetu | Datasets → pusty stan → „Utwórz” → nazwa + embedding + General → ląduje na `/dataset/files/:id`; karta widoczna na liście i na Home |
| S6-03 | Upload i parsowanie | upload 3 plików (PDF, DOCX, XLSX z `tools/test-data/e2e`) z „Parsuj po przesłaniu” → status przechodzi W kolejce → Parsowanie (pasek %) → Sukces; kolumna Chunki > 0; stop parsowania na dużym pliku → Anulowano |
| S6-04 | Chunki | klik w dokument → strona chunków; filtr Włączone/Wyłączone; wyłączenie chunku (switch) i edycja (dodanie słowa kluczowego) utrwalone po przeładowaniu |
| S6-05 | Test retrievalu | pytanie o znany fragment → wynik zawiera dokument i procent podobieństwa; zmiana progu na 0.99 → pusty stan „Nie znaleziono…” |
| S6-06 | Konfiguracja datasetu | zmiana metody na Q&A → ostrzeżenie o ponownym parsowaniu; pola ADV ukryte do rozwinięcia „Zaawansowane”; model embeddingu zablokowany przy istniejących chunkach |
| S6-07 | Czat z cytowaniami | Chat → „Utwórz” → podpięcie datasetu w ustawieniach (zakładka Asystent) → pytanie → odpowiedź streamowana (widać przyrost tekstu), sekcja „Myślenie…” dla modelu z `<think>`, znacznik cytowania z popoverem, klik w dokument → szuflada podglądu; Stop przerywa stream |
| S6-08 | Sesje | nowa sesja nazwana od pierwszego pytania; zmiana nazwy; przeładowanie `?conversationId=` odtwarza historię z cytowaniami; usunięcie sesji |
| S6-09 | Ustawienia i klucze API | Settings → modele domyślne zapisane; utworzenie klucza API → pełny token widoczny raz → klucz działa w `curl`-owym żądaniu `GET /api/v1/datasets` (request API z Playwright) → usunięcie klucza → 401 |
| S6-10 | Admin i uprawnienia | admin tworzy użytkownika, nadaje dostęp do jednego czatu; zalogowany użytkownik widzi tylko ten czat; brak pozycji Admin w menu; tryb ciemny i język EN przełączane i zapamiętane |
| S6-11 | Admin → Integracje (E4-3c, pełny E4-3d na stubie Graph `fake-graph`) | zły sekret → test połączenia pokazuje błąd z API; pełny cykl: test połączenia OK, wybór/wykluczenie dysku, zapis, synchronizacja `success` → dokumenty w datasecie docelowym, edycja utrwalona po przeładowaniu, usunięcie z potwierdzeniem; sekret znika z DOM po zamknięciu dialogu |
| S6-12 | Wyszukiwarka (E4-4b) | utworzenie z listy `/searches` (nazwa → `/search/:id`), szuflada ustawień otwiera się sama; wybór bazy ze sparsowanym dokumentem, podsumowanie AI (`fake-chat`) i pytania pokrewne, zapis; pytanie → podsumowanie z chipem cytowania, ≥ 1 trafienie, nazwa dokumentu → szuflada podglądu; rekomendacje z `search_id` (chip pokrewny — E4-H1); zmiana nazwy utrwalona po F5, usunięcie z listy |
| S6-13 | Pliki `/files` (E4-5c) | wejście z menu „Pliki”; nowy folder; wejście do folderu (breadcrumbs); upload pliku tekstowego do podfolderu; wyszukiwanie po nazwie (trafienie i brak); zmiana nazwy utrwalona po F5; przeniesienie do roota; połączenie z datasetem (chip w kolumnie „Datasety” i dokument w zakładce Pliki datasetu); pobranie (zdarzenie `download`, nazwa pliku); usunięcie zbiorcze z potwierdzeniem |
| S6-14 | Mobile 390×844 (E3-7) | menu mobilne → Pliki; akcja wiersza w menu ⋮ w pierwszej kolumnie (wzorzec < md); axe bez naruszeń critical/serious |

Każdy scenariusz: `page.on('console')` — błąd konsoli = porażka; `axe` na kluczowych ekranach; zrzuty ekranu przy porażce (artefakty dla Reviewera);
**`expectNoLayoutDefects` na końcu każdego testu** (fixture `page`, `WD_E2E_LAYOUT_GUARD=strict` domyślnie) i jawnie po otwarciu dialogu/szuflady/popovera.

**Od 2026-10-09** nowe scenariusze powstają w formacie `SCENARIOS.md` (skill `user-scenarios`: kroki użytkownika z oczekiwanym
wynikiem po każdym kroku, warianty, budżety czasu) i mają w tytule testu identyfikator `SC-<WP>-NN`; usterki właściciela
trafiają do biblioteki regresji `docs/scenarios/`. **`e2e/visual.spec.ts`**: 14 ekranów × (jasny 1280, ciemny 1280, jasny 390)
z danymi „długimi” — `expectNoLayoutDefects` + `toHaveScreenshot` (zrzuty wzorcowe w `e2e/visual.spec.ts-snapshots/`).

### 11.3 Testy eksploracyjne agentów (`playwright-cli`)
Poza CI: Programista frontu (samosprawdzenie, `.task/shots/`), QA-UI (scenariusze `SCENARIOS.md`, ocena wizualna każdego
zrzutu wg §4.4) i — przy zamknięciu etapu — QA-UI w trybie „pierwszy użytkownik” na czystej instalacji. Zrzut, którego nikt
nie otworzył (Read), nie jest dowodem. Nie zastępuje e2e.

---

## 12. Pułapki znane z bety

1. **`routeTree.gen.ts` przed `tsc`** — plik generowany i gitignorowany; `tsc` w świeżym worktree padnie. Rozwiązanie: `typecheck` = `tsr generate && tsc --noEmit` (§2). Nie commitujemy wygenerowanego drzewa.
2. **Wspólny prefiks tras bez rodzica** — `x.index.tsx` + `x.$id.tsx` bez `x.tsx`/`x/route.tsx` → generator odwołuje się do wirtualnego rodzica i obie trasy są „Not Found”, a build i `tsc` przechodzą (plik ma `@ts-nocheck`). Zasada: **tylko trasy katalogowe + `route.tsx` dla każdego katalogu z więcej niż jedną trasą**; test jednostkowy `routes.test.ts` przechodzi po `router.routesByPath` i sprawdza, że każda oczekiwana ścieżka z §6.2 istnieje; e2e S6-01 odwiedza każdą pozycję menu.
3. **Nieświeże moduły Vite po przełączeniu gałęzi** — dev server w kontenerze potrafi serwować starą wersję mimo nowego pliku. Procedura: `curl localhost:5173/src/<plik>` porównać z dyskiem → `docker compose restart web-dev`. Zapisane w runbooku (M12).
4. **Otwieranie zabezpieczonego pliku** — `window.open` musi być synchroniczny w handlerze; blob tekstowy wymaga `charset=utf-8` (§9.4).
5. **Przestarzały eksport pluginu** `TanStackRouterVite` → używać `tanstackRouter`.
6. **Brak TanStack Query w becie** skutkował ręcznym `useEffect`-fetchingiem i brakiem inwalidacji — w WD zakazane regułą ESLint (`no-restricted-syntax` na `fetch(` poza `src/api` i `src/lib/sse.ts`).
7. **Ręczne typy API rozjeżdżały się z backendem** — tylko `schema.gen.ts`; test kontraktu backendu pilnuje aktualności `openapi.json`.

---

## 13. Uwagi do Big Picture

1. ✅ rozstrzygnięte w ARCHITECTURE.md (ADR-13) — Keycloak w przepływie prowadzonym przez backend (§5.2).
2. ✅ rozstrzygnięte — trasy admina `/api/wd/v1/users*`, `/access/*`, `/audit`, `/stats` wg 02-api §12 (bez prefiksu `/admin` w API; `/admin/*` to tylko ścieżki SPA).
3. ✅ rozstrzygnięte — M5 zapisuje `derived/normalized.html` (05 §2.1); `GET /api/v1/documents/{id}/preview` zwraca PDF/obraz albo ten HTML (02-api §5).
4. ✅ rozstrzygnięte — `positions` w formacie RAGFlow z opcjonalnym bbox + `page_from/page_to` (04 §4.8, 05 §14); v1 UI: przewinięcie do strony, ramki gdy bbox obecny.
5. **Port publiczny**: ARCHITECTURE.md §3 podaje `web` na :8080; dev server Vite działa na :5173 z proxy na `api:8000` — spójne z M12.
