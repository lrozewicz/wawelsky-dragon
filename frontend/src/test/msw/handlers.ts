import { HttpResponse, http, type HttpHandler } from 'msw'

import { adminHandlers } from './handlers/admin'
import { authHandlers } from './handlers/auth'
import { apiUrl } from './handlers/common'
import { chatsHandlers } from './handlers/chats'
import { chunksHandlers } from './handlers/chunks'
import { datasetHandlers, metadataHandlers } from './handlers/datasets'
import { datasetUsageHandlers } from './handlers/datasetUsage'
import { documentsHandlers } from './handlers/documents'
import { filesHandlers } from './handlers/files'
import { integrationsHandlers } from './handlers/integrations'
import { kbTransferHandlers } from './handlers/kbTransfer'
import { modelsDefaultHandlers } from './handlers/models'
import { searchesHandlers } from './handlers/searches'
import { settingsHandlers } from './handlers/settings'

export { makeDeployment, makeRunpodState, runpodHandlers } from './handlers/runpod'
export * from './handlers/admin'
export * from './handlers/auth'
export * from './handlers/chats'
export * from './handlers/chunks'
export * from './handlers/common'
export * from './handlers/datasetLogs'
export * from './handlers/datasets'
export * from './handlers/datasetUsage'
export * from './handlers/documents'
export * from './handlers/files'
export * from './handlers/home'
export * from './handlers/integrations'
export * from './handlers/kbTransfer'
export * from './handlers/models'
export * from './handlers/retrieval'
export * from './handlers/searches'
export * from './handlers/settings'

// Kolejność tras jak dotąd: auth i użytkownik, modele, datasety, czaty, dokumenty.
export const handlers: HttpHandler[] = [
  ...authHandlers,

  // Domyślne modele użytkownika i pusty rejestr WD (08 §8.2).
  ...modelsDefaultHandlers,

  // Datasety (08 §7.3, §7.4) — domyślnie pusty magazyn, żeby ekran nie wymagał danych;
  // testy podmieniają stan przez `server.use(...datasetHandlers([...]))`.
  ...datasetHandlers(),

  // Konfiguracja metadanych datasetów (kontrakt WP E6-1b §1) — domyślnie puste listy; zakładka
  // „Konfiguracja” czyta ją na wejściu, więc bez handlera jej testy padałyby na MSW „unhandled”.
  ...metadataHandlers(),

  // Powiązania datasetu (K20 §4, trasa dialogu usuwania) — domyślnie puste powiązania; testy
  // podmieniają stan przez `...datasetUsageHandlers(usage)` albo własny handler tej trasy.
  ...datasetUsageHandlers(),

  // Czaty (08 §7.6) — stan początkowy pusty, jak w pozostałych listach.
  ...chatsHandlers(),

  // Dokumenty datasetu (08 §7.4, kontrakt WP E3-3b §T1a) — domyślnie pusty magazyn; testy
  // podmieniają stan przez `server.use(...documentsHandlers([...]))`.
  ...documentsHandlers(),

  // Chunki (08 §7.5, kontrakt WP E3-4a §Fakty API) — domyślnie pusty magazyn; testy podmieniają
  // stan przez `server.use(...chunksHandlers([...]))`.
  ...chunksHandlers(),

  // Admin (kontrakt WP E3-6c2 §6) — seed domyślny (admin@wd.test + jan@wd.test); testy
  // podmieniają stan przez `server.use(...adminHandlers({...}))`.
  ...adminHandlers(),

  // Ustawienia (kontrakt WP E3-6c1 §6) — seed domyślny (instancja `default` z `fake-llm`
  // i `fake-embd`, brak tokenów); testy podmieniają stan przez `server.use(...settingsHandlers({...}))`.
  ...settingsHandlers(),

  // Integracje SharePoint (kontrakt WP E4-3c §3) — domyślnie pusty magazyn; testy podmieniają
  // stan przez `server.use(...integrationsHandlers({...}))`.
  ...integrationsHandlers(),

  // Wyszukiwarki (kontrakt WP E4-4b §6) — ziarno `searchFixtureApp`; testy wracają do niego
  // przez `resetSearchesFixtures()` i podmieniają trasy `server.use(...)`.
  ...searchesHandlers(),
  ...filesHandlers(),

  // Eksport/import bazy wiedzy (kontrakt WP E7-2 §1, trasy 1–10 z K19 §3) — ziarno: dataset
  // `d1` z podglądem; testy konfigurują scenariusze przez `setExportPreview`, `failNextUpload`,
  // `setImportPackage`, `failTask` i wracają do ziarna przez `resetKbTransfer()`.
  ...kbTransferHandlers(),

  // Konfiguracja pól metadanych datasetu (kontrakt WP E6-1b §1) — domyślnie brak pól; kreator
  // warunków czyta ją obok `metadata/summary` (`useMetaKeys` scala wartości enum). Testy
  // podmieniają ją własnym handlerem `GET …/metadata/config`.
  http.get(apiUrl('/api/v1/datasets/:datasetId/metadata/config'), () =>
    HttpResponse.json({
      code: 0,
      message: 'success',
      data: { metadata: [], built_in_metadata: [] },
    }),
  ),
]
