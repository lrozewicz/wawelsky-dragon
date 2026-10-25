// SC-E5-H8z (brief T1, G1–G4): czułość strażnika helpers/layout.ts. G1 — nowa kategoria
// `cut-off`: przycisk interaktywny przycięty krawędzią kontenera z `overflow` (R-UI-04, kosz
// w menedżerze plików), gdy użytkownik widzi „ucięty” przycisk bez przewijania. G2/G3 —
// treść w całości przewinięta poza kontener i w całości w kontenerze NIE są wadą (T4 z E5-H8d:
// lista wiadomości czatu). G4 — nakładki `position: fixed`/`sticky` (np. nagłówek „Wawelsky
// Dragon” na przewiniętej stronie, E5-H8c) nie tworzą fałszywego `overlap` z treścią pod sobą,
// ale dwa teksty w TEJ SAMEJ nakładce i dwa nakładające się teksty na zwykłej stronie nadal
// są zgłaszane.
//
// Spec czysty DOM (`page.setContent`) — bez stosu aplikacji i bez logowania; wady liczy
// `collectLayoutDefects` z helpers/layout. Każdy test kończy się czystą stroną, żeby fabryczny
// strażnik z fixtures.ts (biegnący po teście na ostatnim stanie strony) nie widział wady, którą
// test CELNIE zostawił na ekranie (G1/G4b/G4c).
import { expect, test } from './fixtures'

import { collectLayoutDefects } from './helpers/layout'

test.describe('strażnik układu — cut-off (R-UI-04)', () => {
  test('G1: przycisk przycięty prawą krawędzią kontenera overflow:auto → cut-off', async ({
    page,
  }) => {
    // Kontener 200 px, wewnętrzny rząd 230 px, przycisk 90 px przy prawej krawędzi rzędu —
    // poza kontenerem wystaje ~1/3 przycisku (30 px), scrollLeft = 0 (użytkownik nic nie
    // przewinął). Na kodzie bazowym strażnik nic nie zgłasza — test jest CZERWONY.
    await page.setContent(`
      <div style="width: 200px; overflow: auto;">
        <div style="position: relative; width: 230px; height: 52px;">
          <button id="kosz" style="position: absolute; right: 0; top: 8px; width: 90px; height: 36px;">Usuń</button>
        </div>
      </div>
    `)
    const defects = await collectLayoutDefects(page)
    expect(
      defects.filter((defect) => defect.kind === 'cut-off').map((defect) => defect.detail),
      'strażnik zgłasza przycięty przycisk krawędzią kontenera',
    ).not.toEqual([])
    // Ekran bez wad na koniec testu (strażnik fixtures.ts).
    await page.setContent('<main>czysty stan</main>')
  })

  test('G2: przycisk w całości przewinięty poza kontener → brak wady', async ({ page }) => {
    await page.setContent(`
      <div id="box" style="width: 220px; height: 120px; overflow: auto;">
        <div style="position: relative; height: 400px;">
          <button id="gora" style="position: absolute; top: 20px; left: 8px; width: 90px; height: 36px;">Nad</button>
        </div>
      </div>
    `)
    await page.evaluate(() => {
      ;(document.getElementById('box') as HTMLElement).scrollTop = 400
    })
    const defects = await collectLayoutDefects(page)
    expect(defects, 'treść przewinięta poza własny kontener nie jest wadą').toEqual([])
  })

  test('G3: przycisk w całości w kontenerze → brak wady', async ({ page }) => {
    await page.setContent(`
      <div style="width: 200px; overflow: auto;">
        <button id="srodek" style="margin: 8px; width: 90px; height: 36px;">W środku</button>
      </div>
    `)
    const defects = await collectLayoutDefects(page)
    expect(defects, 'przycisk w całości w kontenerze nie jest wadą').toEqual([])
  })

  test('G1b: przycięcie dekoracyjnym klipem (overflow: clip) → cut-off — cięcie TRWAŁE (T8)', async ({
    page,
  }) => {
    // Dekoracyjny klip (`overflow: clip`, jak `MuiPaper` akordeonu) przycina element, który
    // wystaje ponad jego krawędź, także gdy klip siedzi w przewijanym kontenerze: klip przesuwa
    // się z treścią, więc przewinięcie NIE odsłania ukrytej części (pomiar Reviewera T8:
    // elementFromPoint trafia w box przy scrollTop=102, gdy krawędź klipu jest wewnątrz
    // scrollportu) — to realna wada R-UI-04, zgłaszana.
    await page.setContent(`
      <div style="width: 240px; height: 120px; overflow: auto;">
        <div style="padding-top: 30px;">
          <div style="overflow: clip; height: 36px;">
            <button id="dol" style="position: relative; top: -14px; width: 90px; height: 36px;">Przycięty</button>
          </div>
        </div>
      </div>
    `)
    const defects = await collectLayoutDefects(page)
    expect(
      defects.filter((defect) => defect.kind === 'cut-off').map((defect) => defect.detail),
      'trwałe przycięcie dekoracyjnym klipem jest zgłaszane (przewinięcie nie odsłania treści)',
    ).not.toEqual([])
    await page.setContent('<main>czysty stan</main>')
  })

  test('G1d: klip w trakcie animacji wysokości → brak wady (T8)', async ({ page }) => {
    // Fałszywy alarm z szuflady czatu (SC-E6-1b-05 krok 7, wariant EN): strażnik mierzy tuż po
    // rozwinięciu akordeonu, gdy klip jest ściśnięty w trakcie animacji wysokości MUI Collapse
    // — stan ustalony klipu jest poprawny i cięcia nie ma. Animacja CSS (tu: keyframes) na
    // klipie wycisza cut-off na czas biegu (`getAnimations({ subtree: true })` w guardzie).
    await page.setContent(`
      <style>
        @keyframes sq { from { height: 36px } to { height: 60px } }
      </style>
      <div style="width: 240px; height: 120px; overflow: auto;">
        <div style="padding-top: 30px;">
          <div style="overflow: clip; height: 36px; animation: sq 10s linear;">
            <button id="dol" style="position: relative; top: -14px; width: 90px; height: 36px;">Animowany</button>
          </div>
        </div>
      </div>
    `)
    const defects = await collectLayoutDefects(page)
    expect(
      defects.filter((defect) => defect.kind === 'cut-off').map((defect) => defect.detail),
      'klip w trakcie animacji wysokości nie tworzy cut-off (geometria przejściowa)',
    ).toEqual([])
    await page.setContent('<main>czysty stan</main>')
  })

  test('G1c: przycięty kontenerem overflow:hidden bez przewijalnego przodka → cut-off (T8)', async ({
    page,
  }) => {
    // Realne przycięcie musi przetrwać poprawkę z G1b: kontener brzegowy (hidden) bez żadnego
    // przewijalnego przodka — użytkownik NIE odsłoni treści przewinięciem (R-UI-04).
    await page.setContent(`
      <div style="width: 200px; overflow: hidden;">
        <div style="position: relative; width: 230px; height: 52px;">
          <button id="kosz" style="position: absolute; right: 0; top: 8px; width: 90px; height: 36px;">Usuń</button>
        </div>
      </div>
    `)
    const defects = await collectLayoutDefects(page)
    expect(
      defects.filter((defect) => defect.kind === 'cut-off').map((defect) => defect.detail),
      'realne przycięcie kontenerem hidden nadal zgłaszane',
    ).not.toEqual([])
    await page.setContent('<main>czysty stan</main>')
  })
})

test.describe('strażnik układu — nakładki position: fixed (E5-H8c)', () => {
  test('G4a: stały nagłówek nad przewiniętą treścią → brak overlap', async ({ page }) => {
    await page.setContent(`
      <header style="position: fixed; top: 0; left: 0; right: 0; height: 48px; background: #fff; z-index: 10;">
        <div style="line-height: 48px;">Wawelsky Dragon</div>
      </header>
      <main style="height: 2400px; padding-top: 515px;">
        <p>Treść przewinięta pod stałym nagłówkiem strony głównej</p>
      </main>
    `)
    await page.evaluate(() => window.scrollTo(0, 500))
    const defects = await collectLayoutDefects(page)
    expect(
      defects.filter((defect) => defect.kind === 'overlap').map((defect) => defect.detail),
      'nakładka fixed nad przewiniętą treścią to nie overlap',
    ).toEqual([])
  })

  test('G4b: dwa teksty nakładające się na zwykłej stronie → overlap', async ({ page }) => {
    await page.setContent(`
      <div style="position: relative; width: 320px; height: 60px;">
        <span style="position: absolute; top: 0; left: 0;">Pierwszy przykładowy tekst</span>
        <span style="position: absolute; top: 12px; left: 16px;">Drugi przykładowy tekst</span>
      </div>
    `)
    const defects = await collectLayoutDefects(page)
    expect(
      defects.filter((defect) => defect.kind === 'overlap').map((defect) => defect.detail),
      'zachowanie nie zepsute: nakładanie tekstów bez nakładki jest zgłaszane',
    ).not.toEqual([])
    await page.setContent('<main>czysty stan</main>')
  })

  test('G4c: dwa teksty w tej samej stałej nakładce → overlap', async ({ page }) => {
    await page.setContent(`
      <header style="position: fixed; top: 0; left: 0; width: 400px; height: 64px; background: #fff;">
        <span style="position: absolute; top: 8px; left: 8px;">Nakładka pierwszy tekst</span>
        <span style="position: absolute; top: 16px; left: 24px;">Nakładka drugi tekst</span>
      </header>
    `)
    const defects = await collectLayoutDefects(page)
    expect(
      defects.filter((defect) => defect.kind === 'overlap').map((defect) => defect.detail),
      'dwa teksty w jednej nakładce fixed nadal tworzą overlap',
    ).not.toEqual([])
    await page.setContent('<main>czysty stan</main>')
  })
})
