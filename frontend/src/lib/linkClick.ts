/**
 * Rozpoznawacz „zwykłego” kliku lewym przyciskiem (kontrakt WP E5-H6a §C2).
 * Karta z `<a href>` przejmuje klik routerem TYLKO wtedy, gdy to zwykły klik — zdarzenie
 * z modyfikatorem (ctrl/meta/shift/alt), innym przyciskiem myszy albo już obsłużone
 * (`defaultPrevented`) zostaje domyślnemu zachowaniu przeglądarki (nowa karta, pobranie).
 *
 * Typ jest celowo wąskim podzbiorem `MouseEvent` — bez `currentTarget`/`target`, by dał się
 * sprawdzić w tabeli przypadków bez budowania zdarzenia DOM.
 */

/** Minimalny kształt zdarzenia kliku potrzebny do decyzji o przejęciu nawigacji. */
export type ClickEventLike = {
  button: number
  ctrlKey: boolean
  metaKey: boolean
  shiftKey: boolean
  altKey: boolean
  defaultPrevented: boolean
}

/** `true` tylko dla lewego przycisku bez modyfikatorów i nieobsłużonego wcześniej. */
export function isPlainLeftClick(event: ClickEventLike): boolean {
  return (
    event.button === 0 &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.shiftKey &&
    !event.altKey &&
    !event.defaultPrevented
  )
}
