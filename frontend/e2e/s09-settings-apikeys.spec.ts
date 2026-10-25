// Scenariusz S6-09 (08-frontend §11.2, brief WP E3-6c1/T7): admin zmienia domyślny model LLM
// i widzi zmianę po przeładowaniu, a nowy klucz API działa w żądaniu bez ciasteczek dopóki
// nie zostanie usunięty. Błędów konsoli pilnuje fixture `page` (`./fixtures`).
import { expect, test } from './fixtures'
import { expectNoSeriousA11y } from './helpers/axe'
import { apiLogin, loginViaUi } from './helpers'
import { bearerGet, ok } from './helpers/settings'

const API_URL = process.env.WD_E2E_API_URL ?? ''

/** Domyślny LLM seedu K9 §3 p. 4; embeddingu nie ruszamy — seed ma tylko jeden. */
const SEEDED_LLM = 'fake-chat'

/** Maska tokenu na liście kluczy (kontrakt E3-6c1 §2): pierwsze 12 znaków + `…` + ostatnie 4. */
function maskedToken(token: string): string {
  return `${token.slice(0, 12)}…${token.slice(-4)}`
}

test('S6-09: modele domyślne i klucz API', async ({ page, request }) => {
  // Token sesji admina: sprzątanie klucza i przywrócenie modelu także wtedy, gdy test padnie.
  const sessionToken = await apiLogin(request)
  let key: string | null = null
  let switchedLlm = false

  try {
    await loginViaUi(page)

    // ---- Krok A: modele domyślne ------------------------------------------------
    await page.getByRole('navigation').getByRole('link', { name: 'Ustawienia' }).click()
    await expect(page).toHaveURL(/\/user-setting\/model$/)
    await expect(page.getByTestId('settings-tab-model')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Modele domyślne' })).toBeVisible()

    const llm = page.getByRole('combobox', { name: 'Model LLM' })
    const embedding = page.getByRole('combobox', { name: 'Model embeddingu' })
    // Wartości startowe to domyślne modele seedu K9 (nazwy `fake-*`) wypełnione oba pola.
    await expect(llm).toContainText(/fake-/)
    await expect(embedding).toContainText(/fake-/)
    const initialLlm = (await llm.textContent())?.trim() ?? ''

    // Rejestr seedu ma dwa modele czatu, więc zmiana domyślnego nie wymaga dodawania modelu.
    await llm.click()
    const options = page.getByRole('listbox').getByRole('option')
    await expect(options.first()).toBeVisible()
    const names = (await options.allTextContents()).map((name) => name.trim())
    expect(names.length, `rejestr LLM: [${names.join(', ')}]`).toBeGreaterThanOrEqual(2)
    const otherLlm = names.find((name) => name !== initialLlm) ?? ''
    expect(otherLlm, `rejestr LLM musi mieć model inny niż „${initialLlm}”`).not.toBe('')
    await page.getByRole('option', { name: otherLlm, exact: true }).click()
    await expect(llm).toContainText(otherLlm)

    await page.getByRole('button', { name: 'Zapisz' }).click()
    await expect(page.getByText('Zapisano modele domyślne')).toBeVisible()
    switchedLlm = true

    // Zapis przeżywa przeładowanie (dane idą z API, nie ze stanu formularza).
    await page.reload()
    await expect(page.getByRole('combobox', { name: 'Model LLM' })).toContainText(otherLlm)

    // Jasny motyw, główny ekran scenariusza: zakładka „Modele domyślne” po przeładowaniu.
    await expectNoSeriousA11y(page, 'S6-09 ustawienia modeli domyślnych')

    // ---- Krok B: nowy klucz API -------------------------------------------------
    await page.getByTestId('settings-tab-api').click()
    await expect(page).toHaveURL(/\/user-setting\/api$/)

    // U2: tworzenie klucza domykamy własnym przebiegiem (nie pomocnikiem), bo scenariusz bada
    // sam dialog — po „Utwórz” widok tworzenia ma się zamknąć, a nie tylko pokazać sekret.
    // Czekamy na wiersze listy (seed K9 ma klucz admina), żeby licznik był stabilny.
    const removeButtons = page.getByRole('button', { name: /^Usuń klucz / })
    await expect(removeButtons.first()).toBeVisible()
    const keysBefore = await removeButtons.count()

    await page.getByRole('button', { name: 'Utwórz klucz' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    // Dwuklik (nie zwykły klik) — regresja U2: drugie kliknięcie nie może wysłać drugiego POST-a.
    await dialog.getByRole('button', { name: 'Utwórz', exact: true }).dblclick()
    const field = dialog.getByTestId('settings-new-token')
    await expect(field).toBeVisible()
    key = ((await field.textContent()) ?? '').trim()
    expect(key, 'pełny token musi zaczynać się od „ragflow-”').toMatch(/^ragflow-/)
    // Widok tworzenia zamknięty: pole nazwy i przycisk „Utwórz” znikają (U2).
    await expect(dialog.getByRole('button', { name: 'Utwórz', exact: true })).toHaveCount(0)
    await expect(dialog.getByRole('textbox', { name: 'Nazwa (opcjonalna)' })).toHaveCount(0)

    await dialog.getByRole('button', { name: 'Zamknij', exact: true }).click()
    await expect(dialog).toHaveCount(0)

    // Dokładnie jeden nowy klucz na liście (U2: brak duplikatu).
    await expect(removeButtons).toHaveCount(keysBefore + 1)

    // Pełny token pokazał się dokładnie raz: po zamknięciu dialogu nie ma go w DOM, a wiersz
    // listy niesie tylko maskę (ta sama maska jest w nazwie akcji „Usuń klucz …”).
    await expect(page.getByText(maskedToken(key))).toBeVisible()
    expect(await page.content(), 'pełny token nie może zostać w DOM').not.toContain(key)

    // ---- Krok C: klucz działa w żądaniu bez ciasteczek --------------------------
    const allowed = await bearerGet(key, '/api/v1/datasets')
    const datasets = ok<unknown[]>(allowed, 'GET /api/v1/datasets (nowy klucz)')
    expect(Array.isArray(datasets), 'GET /api/v1/datasets: data to lista baz wiedzy').toBe(true)

    // ---- Krok D: usunięcie klucza odbiera dostęp --------------------------------
    await page.getByRole('button', { name: `Usuń klucz ${maskedToken(key)}` }).click()
    const confirm = page.getByRole('dialog')
    await expect(confirm).toBeVisible()
    await confirm.getByRole('button', { name: 'Usuń', exact: true }).click()
    await expect(page.getByRole('button', { name: `Usuń klucz ${maskedToken(key)}` })).toHaveCount(
      0,
    )

    // Zmierzone na stosie testowym zachowanie: to samo żądanie po usunięciu klucza wraca jako
    // HTTP 401 z kopertą `code 401`. Kontrakt dopuszcza też postać 200 + `code != 0`, ale jej
    // ten scenariusz nie wywołuje (shim v0.24 wymaga nagłówka zgodności), więc asercja pilnuje
    // obu pól zmierzonej odpowiedzi — komunikaty niosą zmierzone wartości.
    const denied = await bearerGet(key, '/api/v1/datasets')
    expect(
      denied.status,
      `żądanie usuniętym kluczem musi zostać odrzucone: HTTP ${denied.status}, ` +
        `code ${denied.envelope?.code}`,
    ).toBe(401)
    expect(denied.envelope?.code, 'koperta odmowy: code != 0').not.toBe(0)
    key = null
  } finally {
    // Sprzątanie mimo porażki: usuń klucz testowy i przywróć domyślny model LLM seedu,
    // żeby kolejne scenariusze widziały stan z resetu K9.
    if (key !== null) {
      const response = await request.delete(`${API_URL}/api/v1/system/tokens/${key}`, {
        headers: { authorization: `Bearer ${sessionToken}` },
      })
      expect(response.status(), 'DELETE /api/v1/system/tokens/{token}').toBe(200)
    }
    if (switchedLlm) {
      const response = await request.patch(`${API_URL}/api/v1/users/me/models`, {
        headers: { authorization: `Bearer ${sessionToken}` },
        data: { llm_id: SEEDED_LLM },
      })
      expect(response.status(), 'PATCH /api/v1/users/me/models (przywrócenie)').toBe(200)
    }
  }
})
