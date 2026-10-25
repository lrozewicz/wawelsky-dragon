# Moduł: frontend — Admin (`/admin/*`)

Stan po WP E3-6c2 (2026-09-30). Spec: `docs/architecture/08-frontend.md` §7.12, scenariusz S6-10 (§11.2). Kontrakt WP: `work/wp/E3-6c2/CONTRACT.md`.
Dostęp: guard `requireSuperuser` w `routes/_app/admin/route.tsx`; pozycja „Administracja” w `SideMenu` tylko dla superusera (istniała wcześniej).

## Trasy (`routes/_app/admin/`)
`/admin` → redirect na `/admin/users`; `users`, `access`, `status`, `integrations`. `UsersPage` ładowany leniwie (`lazy` + `Suspense`), bo ciągnie `@mui/x-data-grid`. `routeTree.gen.ts` jest gitignored (generuje go `bun run typecheck`/`gen:routes`).

## Warstwa danych (`features/admin/`)
- **`wdClient.ts`** (DEC-129): koperta wd to `{data}` (bez `code`), błędy to HTTP 4xx `{error:{code:<slug>,message}}`. `wdCall<T>(promise)` rozpakowuje (204 → `undefined`), `WdApiError(code, message, httpStatus)`, `wdErrorKey(err)` → `admin.error.<slug>` (nieznany → `admin.error.unknown`), `WD_ERROR_SLUGS` (10 slugów). `src/api/envelope.ts` bez zmian.
- **`queries.ts`**: `adminKeys` (prefiks `['admin']`), `usersListQueryOptions({page,pageSize,q})`, `apiKeysQueryOptions(userId)`, `grantsQueryOptions(email)` (`enabled` tylko dla niepustego e-maila), `statsQueryOptions()`/`healthzQueryOptions()` z `refetchInterval` 10 s; mutacje `useCreateUser`, `useUpdateUser`, `useSetUserActive`, `useSetPassword`, `useDeleteUser({id, mode})`, `useCreateApiKey(userId)` (token tylko w `mutation.data`, bez zapisu w cache Query), `useDeleteApiKey`, `useReplaceGrants`.
- **`constants.ts`**: `AUTO_PROVISIONED_BY` = wartość markera auto-provisioningu klienta (`created_by`), `USERS_PAGE_SIZE = 25`, `STATUS_REFETCH_MS = 10000`.

## Layout — interfejs dla E4-3c (Integracje)
```ts
AdminLayout({ active: 'users'|'access'|'status'|'integrations'; children: ReactNode; showIntegrations?: boolean })
```
Nagłówek `h1` „Administracja” + zakładki-linki (`data-testid="admin-tab-<key>"`). Zakładka Integracje jest ukryta, dopóki `showIntegrations` nie jest `true`; od E4-3c wszystkie cztery trasy admina przekazują `showIntegrations`, a `integrations.tsx` renderuje `IntegrationsPage` (sekcja „Integracje (E4-3c)”).

## Użytkownicy (`users/`)
`UsersPage` (szukaj z debounce 300 ms, paginacja serwerowa po 25) → `UsersGrid` (leniwy `DataGrid`, kolumny w `userColumns.tsx`: e-mail, nazwa, rola, źródło, `Switch` Aktywny, utworzono, akcje). `CreateUserDialog`, `UserActionsMenu` (Szczegóły, Zmień hasło tylko dla `local`, Nadaj/Odbierz admina, Klucze API, Usuń; własne konto zablokowane dla dezaktywacji/zmiany roli/usunięcia). Dialogi: `PasswordDialog`, `UserDetailsDialog`, `DeleteUserDialog` (wybór `transfer`/`cascade`), `ApiKeysDialog` (token pełny raz w `admin-key-token`, `mutation.reset()` przy zamknięciu; opcjonalne pole `datetime-local` `admin-key-expires` → `expires_at` ISO 8601 UTC (`toISOString()`, K14 §3; pusty = pole pominięte; przeszłość blokowana po stronie klienta, 400 z API w `Alert`); błąd listy kluczy w `Alert` `admin-keys-load-error`; kolumna „Wygasa”: pusty = Bezterminowy, `expires_at <= now` = Wygasł; slot `inputLabel.shrink` zamiast `InputLabelProps`, DEC-167). `UsersPage` montuje tylko dialog pasujący do wybranej akcji (brak zbędnego `GET …/api-keys`); `usersListQueryOptions` ma `placeholderData: keepPreviousData` (paginacja nie wraca na stronę 1). Błędy 4xx (np. `conflict` dla ostatniego admina / zajętego e-maila) jako `Alert` z `admin.error.<slug>`.

## Dostęp do asystentów (`access/`)
`AccessPage`: `Autocomplete` e-maila (freeSolo, podpowiedzi z `users?q=`), lista czatów z `chatsListQueryOptions()` jako `AccessChatList`; granty z `created_by === AUTO_PROVISIONED_BY` zaznaczone, zablokowane, z chipem „Nadany automatycznie”. Zapis: `PUT access/assistants` z pełnym zbiorem (w tym automatycznymi).

## Status (`status/`)
`StatusPage` + `StatusCard`: karty DB, storage (Chip OK/Błąd + czas sondy), workery (aktywni, lista z tętnem), kolejka (queued/running/dead), wersja + status z `/api/v1/system/healthz`. Błąd `stats` → `Alert` w kartach zależnych.

## Integracje (E4-3c)
Kod: `features/admin/integrations/`; trasa `/admin/integrations` → `IntegrationsPage` (`data-testid="admin-integrations"`). API: `/api/wd/v1/integrations*` przez `wdCall` (koperta WD), typy z `components['schemas']`.
- `queries.ts`: `integrationKeys`, `integrationsListQueryOptions`, `integrationQueryOptions`, `integrationStatusQueryOptions` (polling `INTEGRATION_POLL_MS` = 3 s tylko gdy przebieg `running`/`queued`, `isActiveRunStatus`), `integrationDrivesQueryOptions`, `integrationRunsQueryOptions`, `runEventsQueryOptions`; mutacje `useCreate/Update/DeleteIntegration`, `useTestConnection`, `useTestSavedConnection`, `useSyncIntegration({full})`, `useCancelIntegration`. Mutacje unieważniają `integrationKeys.all`; sekretu nie zapisują w cache.
- `schema.ts`: `IntegrationFormValues`, `validateForm(values, 'create'|'edit')` (klucze i18n błędów), `toCreateBody/toUpdateBody/toTestBody/toSavedTestBody` (MB→bajty; pusty sekret pomijany w PATCH i teście zapisanej integracji).
- Lista: `IntegrationsGrid` (`DataGrid`: nazwa-link, dataset, harmonogram „co N s/min”, ostatni przebieg `StatusChip`, aktywna, akcje; kolumna dataset ukryta poniżej `md`), pusty stan, `Alert` błędu.
- `IntegrationFormDialog` (+ `IntegrationFormFields`, `ConnectionTestResult`): tworzenie/edycja; sekret `type=password`, `autoComplete=new-password`, czyszczony przy zamknięciu, przy edycji puste = bez zmiany (maska `client_secret_masked` jako podpowiedź). „Testuj połączenie”: create → `integrations_test`, edit → `integrations_test_saved`; wynik trzech etapów (graph_auth, site_resolution, dataset_exists), nazwa witryny i lista dysków. 409 `conflict` → „Ten dataset ma już integrację”.
- `IntegrationDetailsDialog` (+ `RunsList`, `RunEvents`, `IntegrationDrivesList`): stan i liczniki ostatniego przebiegu, sync (opcja „pełna”) i cancel z `ConfirmDialog`, dyski (read-only; wybór dysków = lista wykluczonych bibliotek w formularzu), historia przebiegów (kursor `after_id`, „Pokaż więcej”), zdarzenia przebiegu z filtrem poziomu (`info|warn|error` — enum schematu) i kursorem, usunięcie z potwierdzeniem (dokumenty w datasecie zostają).
- Tłumaczenia: `locales/{pl,en}/integrations.json` (prefiks `integrations.`; błędy API z `admin.error.*`). MSW: `test/msw/handlers/integrations.ts` (`integrationsHandlers(seed)`, `makeIntegration/makeRun/makeEvent`; test połączenia zwraca `graph_auth:'failed'` dla `tenant_id==='bad'`).
- e2e: `e2e/s11-integrations.spec.ts` + `e2e/helpers/integrations.ts` (S6-11, patrz niżej).
- Znane braki: (1) zapis integracji na stosie testowym nie jest możliwy bez Graph (backend woła `resolve` przy POST/PATCH zmieniającym dane dostępowe — 09 §3), więc e2e S6-11 pokrywa test połączenia i odrzucenie zapisu; edycja/usunięcie/sync pokryte vitestem + MSW (DEC-152; pełny cykl e2e wymaga stubu Graph i konfigurowalnego URL logowania Graph); (2) [E3-H2b: usunięte] `ConfirmDialog` ma `children`, checkbox „pełna synchronizacja” jest w dialogu potwierdzenia; alert zapisu pokazuje `error.message` z API przy 400; formularz pełnoekranowy < sm; `deleteAllIntegrations` czyści wszystkie strony; (3) doczytane strony historii/zdarzeń trzymane lokalnie — po unieważnieniu cache kursor pierwszej strony może się rozjechać z doczytanymi (leczy ponowne otwarcie dialogu); (4) `ConnectionTest` nie ma `dataset_exists_error` — w wierszu datasetu pokazujemy `dataset_name`; (5) `documents_source_link` nie jest używany w UI.

## Tłumaczenia i MSW
`locales/{pl,en}/admin.json` (108 kluczy, prefiks `admin.`). `test/msw/handlers/admin.ts` + `adminData.ts`: `adminHandlers(seed?)`, `makeWdUser`, `makeStats`, `makeGrant`, `adminSeed`; stan w domknięciu, 409 `conflict` dla duplikatu e-maila, degradacji jedynego admina i zmiany hasła konta nielokalnego.

## e2e
`e2e/s10-admin-access.spec.ts` + `e2e/helpers/admin.ts`: admin tworzy użytkownika, nadaje dostęp do jednego z dwóch czatów; drugi kontekst przeglądarki — użytkownik widzi tylko ten czat, brak „Administracji” w menu; tryb ciemny i EN przeżywają `reload`.

## Znane braki / wnioski
- Drobne: podwójny JSDoc nad `changeExpires` w `ApiKeysDialog.tsx`; `UsersGrid` bez `localeText` (domyślne angielskie etykiety MUI paginacji).
- `AssistantGrant` z backendu nie ma znacznika auto-provisioningu — UI wylicza go z `created_by`.
- Audyt (`audit_list`) poza zakresem UI v1.

## Utrzymanie E5-H8d (zmiana 25)
`AdminLayout` poniżej `md`: zakładki zawijają się do kolejnych rzędów (`flexWrap`), wskaźnik MUI ukryty, aktywna zakładka z tłem — żadna nie jest przycięta (R-UI-02). `layout-known-defects.ts` jest pusty.

## Historia
| WP | data | zmiana |
|---|---|---|
| E3-6c2 | 2026-09-30 | UI Admin: Użytkownicy, Dostęp do asystentów, Status systemu, slot Integracje; S6-10 |
| E4-3c | 2026-10-01 | UI Integracje SharePoint (lista, formularz z testem połączenia, szczegóły: sync/cancel, dyski, przebiegi, zdarzenia, usunięcie); S6-11 (ograniczony, DEC-152) |
| E3-H2b | 2026-10-01 | data wygaśnięcia klucza (K14), dialogi montowane tylko otwarte, paginacja bez powrotu na stronę 1, wnioski E4-3c (komunikat 400, `ConfirmDialog.children`, pełnoekranowy formularz); S6-10 z kluczem z datą |
| E4-H1 | 2026-10-01 | usunięcie integracji: `useDeleteIntegration` anuluje i usuwa z cache zapytania usuniętego zasobu (detail/status/dyski/przebiegi/zdarzenia), unieważnia tylko listę; dialog szczegółów wyłącza zapytania po usunięciu; S6-11 wymaga 0 błędów konsoli (bez tolerancji 404) |

## Wersja w Statusie systemu (V12-3, SC-V12-03)
Karta „Wersja” (`StatusPage.tsx`) pokazuje `stats.version` z `/api/wd/v1/system/stats` — od V12-1 „1.2.0”, od V13-z „1.3.0”; zmiana kodu UI nie była potrzebna, e2e SC-V12-03 w `s29-v12-3-a.spec.ts`.
