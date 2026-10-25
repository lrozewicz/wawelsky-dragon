# Moduł: frontend — Ustawienia (`/user-setting/*`)

Stan po WP E3-6c1 (2026-10-01). Spec: `docs/architecture/08-frontend.md` §7.11, scenariusz S6-09 (§11.2). Kontrakty: `docs/contracts/K13-dostawcy-modeli.md`, `work/wp/E3-6c1/CONTRACT.md`.
Dostęp: każdy zalogowany (guard `_app`); zapis modeli/instancji tylko superuser (UI chowa akcje zapisu, `useIsSuperuser()`).

## Trasy (`routes/_app/user-setting/`)
`/user-setting` → redirect `/user-setting/model`; `model`, `profile`, `api`. Strony ładowane leniwie (`lazy` + `Suspense`), bo ciągną `@mui/x-data-grid`. Pozycja „Ustawienia” w SideMenu istniała wcześniej.
Layout `SettingsLayout({ active: 'model'|'profile'|'api', children })` — nagłówek „Ustawienia” + zakładki-linki (`data-testid="settings-tab-<key>"`), `scrollable` poniżej `md`.

## Warstwa danych (`features/settings/`)
- `constants.ts`: `PROVIDER = 'litellm'`, `MODEL_TYPES`, `MASKED_API_KEY`, `DEFAULT_INSTANCE_NAME`.
- `queries.ts`: `settingsKeys`, `maskToken` (`ragflow-abcd…wxyz`), `meQueryOptions`, `tokensQueryOptions`, `registryQueryOptions` (`GET /api/v1/models`), `useUpdateMe`, `useUpdateDefaultModels`, `useCreateToken` (token tylko w `mutation.data`), `useDeleteToken`.
- `providerQueries.ts`: instancje i modele dostawcy (`instancesQueryOptions`, `instanceDetailQueryOptions`, `instanceModelsQueryOptions`, `supportedModelsQueryOptions`) oraz mutacje K13 (`useCreateInstance`, `useUpdateInstance`, `useDeleteInstances`, `useVerifyConnection`, `useAddInstanceModel`, `useUpdateInstanceModel`, `useDeleteInstanceModels`).
- `useIsSuperuser.ts` czyta kontekst trasy `/_app`; w testach `renderWithProviders(ui, { route: '/_app', routes: ['/_app'], auth })`.
- Błędy 101/102 koperty RAGFlow (`ApiError`) pokazywane w `Alert` z nagłówkiem `settings.error.title` i komunikatem API.

## Strony
- **Profil** (`profile/`): wiersze Nazwa / E-mail (tylko odczyt) / Strefa czasowa (w akordeonie „Zaawansowane”) / Hasło; dialogi `NameDialog`, `TimezoneDialog`, `PasswordDialog` (obecne/nowe/powtórz, wysyła tylko `password` i `new_password`). Wiersz Hasło ukryty, gdy `login_channel !== 'password'`.
- **Klucze API** (`api/`): `ServerApiCard` (URL `origin + /api/v1`, kopiuj, link `/api/docs`), `KeysGrid` (leniwy `DataGrid`; token zamaskowany, utworzono, Kopiuj/Usuń z potwierdzeniem; `getRowId` oparty o maskę — pełny token nie trafia do atrybutów DOM, DEC-126), `CreateKeyDialog` (pełny token w `data-testid="settings-new-token"`, ostrzeżenie „widoczny raz”, `reset()` mutacji przy zamknięciu). Brak kolumn „ostatnio użyto” i „Wygasa”: schemat `ApiToken` ich nie ma.
- **Dostawcy modeli** (`model/`): `ModelsPage` = `DefaultModelsCard` (LLM*, Embedding*, Rerank, VLM w ADV; patch tylko ze zmienionych niepustych pól; zwykły użytkownik: selecty `disabled` + `Alert` info) nad dwiema kolumnami: `InstancesPanel` (lista, `InstanceDialog` dodaj/edytuj/Weryfikuj, usuwanie z komunikatem 102; `buildInstanceCreate/Update` w `instanceForm.ts` — pusty klucz = pole `api_key` nieobecne w ciele, maska nigdy nie wysyłana; instancja `default` bez Edytuj/Usuń) i `InstanceModelsPanel` (`InstanceModelsGrid` z `Switch` włączony → PATCH `status`, `AddModelDialog`, `ImportModelsDialog` = `?supported=true` + wiele POST-ów, usuwanie z komunikatem blokady 102).

## Tłumaczenia i MSW
`locales/{pl,en}/settings.json` (prefiks `settings.`: `profile.*`, `keys.*`, `defaults.*`, `instances.*`, `models.*`). `test/msw/handlers/settings.ts` + `settingsData.ts`: `settingsHandlers(seed?)`, `makeToken`, `makeSeedInstance`, `makeInstanceModel`; stan w domknięciu; reguły 101/102 z K13 §4 (nie waliduje nazwy dostawcy ani formatu `base_url`).

## e2e
`e2e/s09-settings-apikeys.spec.ts` + `e2e/helpers/settings.ts`: zmiana LLM domyślnego i zapis (utrzymany po `reload`, przywrócenie na końcu); klucz → pełny token raz (`page.content()` bez pełnego tokenu) → `GET /api/v1/datasets` tym kluczem = 200/`code 0` → usunięcie → HTTP 401. Sprzątanie kluczy w `finally`.

## Znane braki / wnioski
- `ApiToken`/`CreatedApiToken` (`/system/tokens`) nie mają `expires_at` ani „ostatnio użyto” — K14 dotyczy tras wd; wniosek do Architekta o rozszerzenie schematu, jeśli Ustawienia mają pokazywać wygaśnięcie.
- `GET /system/tokens` zwraca tokeny w pełnej postaci, więc cache Query listy je zawiera; wymóg „token poza cache” dotyczy wyniku tworzenia (DEC-126). Token po `reset()` zostaje w `MutationCache` do GC (~5 min) — jak w `admin/users/ApiKeysDialog`.
- „Ostatnio użyto” i nazwa klucza w Ustawieniach — świadomie bez zmian (schemat `ApiToken` upstreamu ich nie ma, K14 §4).
- E3-H2b: po E2-H2 usunięto rzutowania `as components['schemas'][...Request]` (DefaultModelsCard, instanceForm, AddModelDialog, InstanceModelsPanel); zostają `as ModelType` (select) i `as TabProps` (SettingsLayout). Toast Profilu (nazwa, strefa, hasło) ma `autoHideDuration: 4000`; dialogi Profilu resetują mutację przy odmontowaniu.
- `TimezoneDialog` przy wyczyszczeniu pola wysyła `timezone: ''` (nie `null`); `AddModelDialog` przy pustym „Max tokens” wysyła 0; martwy klucz `settings.models.nameRequired`; zduplikowany `errorText` w `InstancesPanel`/`InstanceDialog`.
- Typ VLM: backend `image2text`, API K13 `vision` — `DefaultModelsCard` akceptuje oba.
- `e2e/run.sh` ignoruje argumenty (zawsze pełny zestaw). Wariant e2e „rejestr z jednym modelem na typ” nieprzetestowany (seed K9 ma dwa modele czatu).

## Historia
| WP | data | zmiana |
|---|---|---|
| E3-6c1 | 2026-10-01 | UI Ustawień: Dostawcy modeli, Profil, Klucze API; S6-09; DEC-126 |
| E3-H2b | 2026-10-01 | typy żądań bez rzutowań po E2-H2; toast Profilu z auto-hide, reset błędów dialogów |

## Utrzymanie E5-H6a (zmiana 23) — dialog klucza API (U2, DEC-254)
`CreateKeyDialog`: po sukcesie ten sam `Dialog` pokazuje tylko widok sekretu; strażnik tworzenia to `useRef` (synchroniczny — `isPending` z hooka nie łapał dblclick: 2 POST); zwolnienie w `onSettled` i przy `close()`. e2e `s09` używa `dblclick()` i asertuje +1 klucz.

## Utrzymanie E5-H8c (zmiana 25) — okno kontekstu, „Edytuj model”, „Równoległe zapytania”
- Etykieta „Max tokens” → „Okno kontekstu (tokeny)” (kolumna: „Okno kontekstu”) w PL i EN, z podpowiedzią (`settings.models.maxTokensHelp`: budżet promptu czatu, nie limit odpowiedzi).
- `EditModelDialog.tsx` (✎ w wierszu `InstanceModelsGrid`, w widoku compact pozycja menu ⋮): `PATCH …/models/{model}` z `max_tokens` i PEŁNYM `extra` (K13 poprawka 2026-10-10). Logika czysta w `modelForm.ts` (`validateMaxTokens` ≥ 1024, `validateConcurrency` 1–32/puste, `buildModelPatch` podmienia/usuwa wyłącznie `extra.max_concurrency`, `CONCURRENCY_DEFAULTS` vision/image2text 3, embedding 4). Pole „Równoległe zapytania” tylko dla vision/image2text/embedding; `AddModelDialog` ma te same pola (`extra.max_concurrency` w POST).
- Nagłówki panelu instancji i modeli: kolumna < sm, `whiteSpace: nowrap` na przyciskach; `AppNavbar`: nazwa aplikacji `noWrap` (baner 73 → 57 px, nie zasłania treści na 390 px).
- Czat bierze `max_tokens` modelu z rejestru przy każdym pytaniu: `ChatService._resolve_model` → `ModelRegistry.resolve` (zapytanie do DB w transakcji, bez cache) → `chat_pipeline._build_prompt` (`ctx.model.max_tokens`). Frontend czatu nie przekazuje tej wartości; `llm_setting.max_tokens` czatu (limit odpowiedzi) to osobne pole. Wniosek: brak buforowania w backendzie.
- e2e: `s17-model-edit.spec.ts` (SC-E5-H8c-03/04/05), pomocnik `e2e/helpers/models.ts`.
- Po QA-UI (T7–T8, T10): `EditModelDialog` startuje od `model.max_tokens ?? 8192` (zasiew testowy ma `max_tokens = null`; 8192 = domyślna backendu), bez `autoFocus` (czerwony fokus motywu wyglądał jak błąd). Etykiety pól dialogów modelu są STATYCZNE nad polem (`ModelTextField.tsx`: `FormLabel` + `htmlFor`) — motyw (`theme/customizations/inputs.tsx`) rysuje obramowanie na korzeniu `OutlinedInput`, więc pływająca etykieta MUI była przecinana pierścieniem fokusa; placeholder „domyślnie 3/4” widoczny. Siatka modeli: nazwa flex (min 120), typ 100, okno kontekstu 135, wymiar 100, włączony 90, akcje 100, `ModelsPage` md 4/8, nagłówek panelu instancji w kolumnie; kolumna akcji ≥ 100 px (węższa obcinała kosz do „…”).
- Znane: czerwony kolor fokusa motywu (primary) bywa czytany jako błąd walidacji (globalne, `src/theme`, wniosek do Architekta); strażnik układu nie odejmuje nakładek `fixed` — testy SC-05 przewijają stronę na górę przed pomiarem.

## Nazwa klucza API (V12-3, SC-V12-01)
`features/settings/api/KeysGrid.tsx` ma kolumnę „Nazwa” (z `GET /api/v1/system/tokens`, `name`; „—” dla `null`, wielokropek + `title`); w compact (<md) kolumna „Utworzono” jest zwinięta, by przy 390 px nie było poziomego przewijacza.
`CreateKeyDialog.tsx`: pole nazwy `maxLength 128` + licznik `n/128` (dłuższa nazwa dawałaby 500 z serwera; walidacja serwera → backlog v1.3). e2e: `s29-v12-3-a.spec.ts` (SC-V12-01), `s27-e67z2-e.spec.ts` SC-E67-z2-23 (odblokowany).
