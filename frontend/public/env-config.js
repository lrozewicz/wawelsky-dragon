// Domyślna konfiguracja runtime dla środowiska deweloperskiego (kontrakt E3-1a C4).
// W produkcji ten plik nadpisuje serwer: serve.ts odpowiada na GET /env-config.js z wartości z procesu.
window.__ENV__ = {
  KEYCLOAK_URL: '',
  KEYCLOAK_REALM: 'wawelsky-dragon',
  KEYCLOAK_CLIENT_ID: 'wawelsky-web',
  DOCS_URL: 'https://docs.wawelsky-dragon.local',
  FEATURE_AGENT: 'true',
  FEATURE_MEMORY: 'false',
  FEATURE_SEARCH: 'true',
  FEATURE_FILES: 'true',
}
