// Strażnik wad układu (analiza 2026-10-09): QA-UI i testy oceniały ekran po drzewie DOM, w którym nie widać
// nakładania, ucięć ani okien wychodzących poza ekran — te wady znajdował dopiero właściciel. Helper mierzy
// prostokąty w przeglądarce i zgłasza wady widoczne dla użytkownika:
//   - overflow-page:   poziomy pasek przewijania całej strony,
//   - clipped:         tekst ucięty bez wielokropka (overflow hidden/clip, scrollWidth > clientWidth),
//   - overlap:         dwa teksty (liście DOM) nachodzą na siebie; para mieszana „liść w stałej nakładce
//                      (position: fixed/sticky) ↔ liść spoza niej” jest pomijana — nakładka z natury leży
//                      nad przewiniętą treścią (fałszywy „Wawelsky Dragon”, E5-H8c),
//   - label-over-value: etykieta MUI nie „uniesiona” nad polem, które ma wartość,
//   - off-screen:      dialog/popover/menu/podpowiedź nie mieści się w całości w oknie,
//   - covered:         środek widocznego przycisku/linku/pola zasłania inny element,
//   - cut-off:         element interaktywny przycięty krawędzią kontenera (część widoczna 10–90% pola,
//                      jedna krawędź, ≤ 60% wymiaru), gdy kontener w tej osi jest nieprzewinięty —
//                      użytkownik widzi „ucięty” przycisk bez ruchu (R-UI-04); treść całkowicie
//                      przewinięta poza kontener i treść odsłaniana dopiero po przewinięciu użytkownika
//                      (lista wiadomości czatu pod stałym paskiem, T4 z E5-H8d) nie są wadą.
// Wołany automatycznie na końcu każdego testu (fixtures.ts, WD_E2E_LAYOUT_GUARD) i jawnie po otwarciu
// dialogu/szuflady/popovera: `await expectNoLayoutDefects(page, 'dialog uploadu')`.
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { KNOWN_LAYOUT_DEFECTS } from '../layout-known-defects'

export type LayoutDefect = { kind: string; detail: string }

export type LayoutOptions = {
  /** Selektory CSS elementów pomijanych (z poddrzewem) — każde użycie z komentarzem „dlaczego”. */
  ignore?: string[]
}

/** Zbiera wady układu bieżącego widoku (bez asercji). */
export async function collectLayoutDefects(
  page: Page,
  options: LayoutOptions = {},
): Promise<LayoutDefect[]> {
  return page.evaluate((ignore: string[]) => {
    const defects: { kind: string; detail: string }[] = []
    const vw = window.innerWidth
    const vh = window.innerHeight
    const TOL = 1

    // Toasty (Snackbar) znikają same po kilku sekundach — nie są wadą układu ekranu.
    const transient = ['.MuiSnackbar-root']
    const ignored = (el: Element): boolean =>
      [...transient, ...ignore].some((selector) => el.closest(selector) !== null)
    const hiddenTree = (el: Element): boolean =>
      el.closest('[aria-hidden="true"], [inert], [hidden]') !== null
    const isVisible = (el: Element): boolean => {
      const rect = el.getBoundingClientRect()
      if (rect.width < 1 || rect.height < 1) return false
      const style = getComputedStyle(el)
      if (
        style.visibility === 'hidden' ||
        style.display === 'none' ||
        Number(style.opacity) === 0
      ) {
        return false
      }
      return !hiddenTree(el) && !ignored(el)
    }
    const describe = (el: Element): string => {
      const id = el.getAttribute('data-testid') ?? el.getAttribute('aria-label') ?? el.id
      const text = (el.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 40)
      const tag = el.tagName.toLowerCase()
      return `${tag}${id ? `[${id}]` : ''}${text ? ` „${text}”` : ''}`
    }
    const inViewport = (rect: Pick<DOMRect, 'top' | 'right' | 'bottom' | 'left'>): boolean =>
      rect.bottom > 0 && rect.right > 0 && rect.top < vh && rect.left < vw

    // Część elementu widoczna dla użytkownika: prostokąt przycięty do przodków z
    // `overflow` innym niż `visible` (kontener przewijalny, klip). Treść przewinięta
    // poza własny kontener ma `getBoundingClientRect` daleko poza klipem (np. lista
    // wiadomości czatu pod stałym paskiem nawigacji) — nie jest widoczna, więc nie
    // może tworzyć wad `overlap`. Zwraca `null`, gdy nic nie zostaje w klipie. Obok
    // prostokąta zwraca KRAWĘDZIE KLIPÓW (który przodek przyciął którą krawędzią) —
    // z nich kategoria `cut-off` rozpoznaje przycięty element interaktywny (R-UI-04).
    type Box = { left: number; right: number; top: number; bottom: number }
    type ClipEdge = {
      node: HTMLElement
      axis: 'x' | 'y'
      edge: 'left' | 'right' | 'top' | 'bottom'
    }
    const visibleBox = (el: Element): { box: Box; edges: ClipEdge[] } | null => {
      const raw = el.getBoundingClientRect()
      let box: Box = { left: raw.left, right: raw.right, top: raw.top, bottom: raw.bottom }
      const edges: ClipEdge[] = []
      for (let node = el.parentElement; node !== null; node = node.parentElement) {
        const style = getComputedStyle(node)
        // Element w poddrzewie position: fixed/sticky ucieka spod klipów DALSZYCH przodków:
        // jego kontenerem blokowym jest ten element (dla fixed — viewport), więc np. BODY z
        // `overflow: hidden` i wysokością po treści nie przycina dialogu (fixed) ani paska
        // sticky (okno dialogu „Utwórz czat” niższego niż treść strony dawało fałszywy
        // cut-off). Sprawdzane PRZEZ skrót „brak overflow → dalej”, bo kontener fixed/sticky
        // zwykle sam nie ma overflow i musi przerwać wędrówkę.
        if (style.position === 'fixed' || style.position === 'sticky') break
        const clipX = ['auto', 'scroll', 'hidden', 'clip'].includes(style.overflowX)
        const clipY = ['auto', 'scroll', 'hidden', 'clip'].includes(style.overflowY)
        if (!clipX && !clipY) continue
        const clip = node.getBoundingClientRect()
        const clipNode = node as HTMLElement
        if (clipX) {
          const left = Math.max(box.left, clip.left)
          const right = Math.min(box.right, clip.right)
          if (left > box.left + TOL) edges.push({ node: clipNode, axis: 'x', edge: 'left' })
          if (box.right - right > TOL) edges.push({ node: clipNode, axis: 'x', edge: 'right' })
          box = { ...box, left, right }
        }
        if (clipY) {
          const top = Math.max(box.top, clip.top)
          const bottom = Math.min(box.bottom, clip.bottom)
          if (top > box.top + TOL) edges.push({ node: clipNode, axis: 'y', edge: 'top' })
          if (box.bottom - bottom > TOL) edges.push({ node: clipNode, axis: 'y', edge: 'bottom' })
          box = { ...box, top, bottom }
        }
        if (box.right <= box.left || box.bottom <= box.top) return null
      }
      return { box, edges }
    }

    // 1. Poziomy overflow strony.
    const pageWidth = document.documentElement.scrollWidth
    if (pageWidth > vw + TOL) {
      defects.push({ kind: 'overflow-page', detail: `scrollWidth ${pageWidth} > okno ${vw}` })
    }

    // Liście tekstowe: elementy z własnym niepustym węzłem tekstowym — z częścią widoczną
    // w klipach przodków (bez niej `overlap` porównywałby też treść przewiniętą poza
    // kontener, której użytkownik nie widzi).
    const textLeaves: { el: Element; box: Box }[] = []
    for (const el of Array.from(document.body.querySelectorAll('*'))) {
      if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'svg', 'path'].includes(el.tagName)) continue
      const ownText = Array.from(el.childNodes).some(
        (node) => node.nodeType === Node.TEXT_NODE && (node.textContent ?? '').trim() !== '',
      )
      if (!ownText || !isVisible(el)) continue
      const clipped = visibleBox(el)
      if (clipped !== null && inViewport(clipped.box)) textLeaves.push({ el, box: clipped.box })
    }

    // 2. Tekst ucięty bez wielokropka.
    for (const { el } of textLeaves) {
      const style = getComputedStyle(el)
      const clips =
        ['hidden', 'clip'].includes(style.overflowX) || ['hidden', 'clip'].includes(style.overflow)
      if (clips && el.scrollWidth > el.clientWidth + TOL && style.textOverflow !== 'ellipsis') {
        defects.push({
          kind: 'clipped',
          detail: `${describe(el)} (scrollWidth ${el.scrollWidth} > ${el.clientWidth})`,
        })
      }
    }

    // Warstwa stała: najbliższy przodek (lub element) z position fixed/sticky. Nakładka stała
    // (rail nawigacji, nagłówek strony) z natury leży nad przewiniętą treścią, więc porównanie
    // z elementem spoza niej daje fałszywe wady (nagłówek „Wawelsky Dragon” nad przewiniętą
    // stroną, E5-H8c). Dwa elementy TEJ SAMEJ warstwy — albo oba poza warstwami — porównuje
    // normalnie (nakładka wewnątrz siebie nadal musi mieścić treść). Współdzielone przez
    // krok 3 (overlap) i krok 6 (covered).
    const fixedLayer = (el: Element): Element | null => {
      for (let node: Element | null = el; node !== null; node = node.parentElement) {
        const position = getComputedStyle(node).position
        if (position === 'fixed' || position === 'sticky') return node
      }
      return null
    }

    // 3. Nakładające się teksty (powierzchnia przecięcia > 25% mniejszego prostokąta) —
    // liczone na częściach widocznych (patrz `visibleBox` przy liściach). Para mieszana
    // „liść w stałej nakładce ↔ liść spoza niej” jest pomijana: nakładka `fixed`/`sticky`
    // z natury przykrywa przewiniętą treść (nagłówek „Wawelsky Dragon” nad przewiniętą
    // stroną, E5-H8c). Dwa liście tej samej warstwy (albo oba poza warstwami) nadal tworzą
    // overlap — nakładki wewnątrz siebie muszą się mieścić. Warstwę wyznacza `fixedLayer`
    // (współdzielona z krokiem 6).
    const rects = textLeaves.map(({ el, box }) => ({
      el,
      box,
      area: (box.right - box.left) * (box.bottom - box.top),
    }))
    for (const [i, a] of rects.entries()) {
      for (const b of rects.slice(i + 1)) {
        if (a.el.contains(b.el) || b.el.contains(a.el)) continue
        const layerA = fixedLayer(a.el)
        const layerB = fixedLayer(b.el)
        if (layerA !== layerB && (layerA !== null || layerB !== null)) continue
        const w = Math.min(a.box.right, b.box.right) - Math.max(a.box.left, b.box.left)
        const h = Math.min(a.box.bottom, b.box.bottom) - Math.max(a.box.top, b.box.top)
        if (w <= 0 || h <= 0) continue
        const smaller = Math.min(a.area, b.area)
        if ((w * h) / smaller > 0.25) {
          defects.push({ kind: 'overlap', detail: `${describe(a.el)} ↔ ${describe(b.el)}` })
        }
      }
    }

    // 4. Etykieta MUI leży na polu z wartością (np. „Pytanie” na wpisanym tekście, E3-7/E3-H4).
    for (const label of Array.from(document.querySelectorAll('label[data-shrink="false"]'))) {
      if (!isVisible(label)) continue
      const control = label.parentElement?.querySelector('input, textarea') as
        HTMLInputElement | HTMLTextAreaElement | null
      if (control && control.value !== '') {
        defects.push({ kind: 'label-over-value', detail: `${describe(label)} nad wartością pola` })
      }
    }

    // 5. Okna nakładkowe w całości w oknie przeglądarki (popover cytowania #7).
    const overlays = document.querySelectorAll(
      '[role="dialog"], [role="tooltip"], [role="menu"], [role="listbox"], .MuiPopover-paper, .MuiPopper-root',
    )
    for (const el of Array.from(overlays)) {
      if (!isVisible(el)) continue
      const rect = el.getBoundingClientRect()
      if (rect.left < -TOL || rect.top < -TOL || rect.right > vw + TOL || rect.bottom > vh + TOL) {
        const box = `${Math.round(rect.left)},${Math.round(rect.top)} ${Math.round(rect.width)}×${Math.round(rect.height)}`
        defects.push({
          kind: 'off-screen',
          detail: `${describe(el)} [${box}] poza oknem ${vw}×${vh}`,
        })
      }
    }

    // 6. Zasłonięte elementy interaktywne (środek przycisku przykryty innym elementem).
    const interactive = document.querySelectorAll(
      'button, a[href], input:not([type="hidden"]), select, textarea, [role="button"], [role="tab"], [role="menuitem"], [role="checkbox"], [role="switch"]',
    )
    for (const el of Array.from(interactive)) {
      if (!isVisible(el)) continue
      const rect = el.getBoundingClientRect()
      const x = rect.left + rect.width / 2
      const y = rect.top + rect.height / 2
      if (x < 0 || y < 0 || x >= vw || y >= vh) continue
      // Środek przycięty przez klip przodka (element wychodzi poza własny kontener przewijalny):
      // punkt trafia w geometrię sąsiada spod klipa, więc „zasłonięcie” nie opisuje żadnej wady
      // widocznej dla użytkownika (np. akcje ostatniej wiadomości czatu tuż nad polem pytania).
      const clipped = visibleBox(el)
      if (
        clipped === null ||
        x < clipped.box.left ||
        x > clipped.box.right ||
        y < clipped.box.top ||
        y > clipped.box.bottom
      )
        continue
      const top = document.elementFromPoint(x, y)
      if (top === null || top === el || el.contains(top) || top.contains(el) || ignored(top))
        continue
      // Własna etykieta/obramowanie pola MUI (np. ukryty input checkboxa pod ikoną) — ten sam komponent.
      const owner = el.closest(
        '.MuiFormControl-root, .MuiButtonBase-root, .MuiInputBase-root, label',
      )
      if (owner !== null && owner.contains(top)) continue
      // Przycisk w stałej nakładce (rail nawigacji — Paper fixed, z 1200) vs treść poza nią:
      // hit-test trafia w przezroczysty box kontenera treści, ale nakładka maluje się NAD treścią
      // i klik dociera do przycisku (sprawdzone na żywo) — ta sama klasa fałszywych alarmów co
      // overlap wyżej. Para w obrębie jednej warstwy nadal jest zgłaszana.
      // Treść przewinięta POD nakładką (odwrotna orientacja; K5: przyklejona pierwsza kolumna
      // tabeli nad zrolowanymi kolumnami) też nie jest wadą — element wraca na wierzch po
      // przewinięciu z powrotem, użytkownik nigdy nie widzi go „zasłoniętego na stałe”.
      const layer = fixedLayer(el)
      const topLayer = fixedLayer(top)
      if (layer !== null ? layer !== topLayer : topLayer !== null) continue
      defects.push({ kind: 'covered', detail: `${describe(el)} zasłonięty przez ${describe(top)}` })
    }

    // 7. Element interaktywny przycięty krawędzią kontenera (R-UI-04): widoczna część po klipach
    //    to 10–90% pola elementu, przycięcie jedną krawędzią o ≤ 60% wymiaru, a kontener w tej
    //    osi jest nieprzewinięty — użytkownik widzi „ucięty” przycisk bez żadnego ruchu. Treść
    //    całkowicie poza klipem (visibleBox → null) i treść odsłaniana dopiero po przewinięciu
    //    przez użytkownika (krawędź górna/lewa w kontenerze przewijalnym = ktoś przewinął;
    //    lista wiadomości czatu pod stałym paskiem, T4 z E5-H8d) nie są wadą.
    const EDGE_NAMES = { left: 'lewą', right: 'prawą', top: 'górną', bottom: 'dolną' } as const
    for (const el of Array.from(interactive)) {
      if (!isVisible(el)) continue
      const rect = el.getBoundingClientRect()
      const clipped = visibleBox(el)
      if (clipped === null) continue
      const { box: vis, edges } = clipped
      const areaAll = rect.width * rect.height
      const areaVis = (vis.right - vis.left) * (vis.bottom - vis.top)
      const fraction = areaVis / areaAll
      if (fraction < 0.1 || fraction >= 0.9) continue
      const clip = edges.length === 1 ? edges[0] : undefined
      if (clip === undefined) continue
      const { node, axis, edge } = clip
      const style = getComputedStyle(node)
      const scrollable =
        axis === 'x'
          ? ['auto', 'scroll'].includes(style.overflowX)
          : ['auto', 'scroll'].includes(style.overflowY)
      if (scrollable) {
        if (edge === 'left' || edge === 'top') continue
        const offset = axis === 'x' ? node.scrollLeft : node.scrollTop
        if (offset > TOL) continue
      }
      // Geometria PRZEJŚCIOWA: klip w trakcie animacji wysokości (MUI Collapse przy rozwijaniu
      // akordeonu — SC-E6-1b-05 krok 7: strażnik mierzy tuż po rozwinięciu „Filtr metadanych”
      // w szufladzie czatu i widział ściśnięty klip, ustalony stan jest poprawny) przycina
      // treść tylko chwilowo. Animacje CSS klipu i jego poddrzewa (transition height Collapse,
      // ripple po kliknięciu) wykrywa `getAnimations({ subtree: true })` — proxy zamiast
      // gałęzi po klasach MUI; animacja nieskończona (spinner) w realnie przyciętym klipie
      // wyciszy wadę do jej końca (świadomy kompromis, pomiar 2026-10-13).
      const animated =
        typeof node.getAnimations === 'function' &&
        node.getAnimations({ subtree: true }).some((a) => a.playState === 'running')
      if (animated) continue
      const cut =
        edge === 'right'
          ? rect.right - vis.right
          : edge === 'left'
            ? vis.left - rect.left
            : edge === 'bottom'
              ? rect.bottom - vis.bottom
              : vis.top - rect.top
      const dimension = axis === 'x' ? rect.width : rect.height
      if (cut > 0.6 * dimension) continue
      defects.push({
        kind: 'cut-off',
        detail: `${describe(el)} przycięty ${EDGE_NAMES[edge]} krawędzią kontenera (widoczne ${Math.round(fraction * 100)}%)`,
      })
    }

    return defects
  }, options.ignore ?? [])
}

/**
 * Odfiltrowuje wady z listy znanych (`layout-known-defects.ts`) dla bieżącego pliku spec — każda znana wada
 * trafia do raportu jako adnotacja `layout-known-defect`, pozostałe zwraca.
 */
export function withoutKnownDefects(defects: string[]): string[] {
  const file = test.info().file.split('/').pop() ?? ''
  const known = (defect: string): boolean =>
    KNOWN_LAYOUT_DEFECTS.some((k) => k.spec === file && defect.includes(k.contains))
  for (const defect of defects.filter(known)) {
    test.info().annotations.push({ type: 'layout-known-defect', description: defect })
  }
  return defects.filter((defect) => !known(defect))
}

/**
 * Asercja: brak wad układu w bieżącym widoku (poza znanymi); `context` opisuje ekran.
 * `soft: true` — zbiera wszystkie wady testu zamiast przerywać na pierwszym ekranie (visual.spec.ts).
 */
export async function expectNoLayoutDefects(
  page: Page,
  context: string,
  options: LayoutOptions & { soft?: boolean } = {},
): Promise<void> {
  const defects = await collectLayoutDefects(page, options)
  const lines = withoutKnownDefects(defects.map((defect) => `${defect.kind}: ${defect.detail}`))
  const assertion = options.soft === true ? expect.soft : expect
  assertion(lines, `${context} — wady układu`).toEqual([])
}
