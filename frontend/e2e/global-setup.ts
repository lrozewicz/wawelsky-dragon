// Seed stosu testowego przed każdym biegiem Playwrighta (kontrakt WP E3-2: K9, `POST
// /api/wd/v1/test/reset` z ciałem `{}`). Reset zakłada konto admina z fixture'ów.
const API_URL = process.env.WD_E2E_API_URL ?? ''

export default async function globalSetup(): Promise<void> {
  const response = await fetch(`${API_URL}/api/wd/v1/test/reset`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: '{}',
  })
  if (response.status !== 200) {
    throw new Error(`test/reset ${response.status}: ${await response.text()}`)
  }
}
