/**
 * Powód nieaktywnego „Zapisz” (SC-V12-08, 08-frontend §4.4 k1): widoczny tekst pod przyciskiem,
 * powiązany atrybutem `aria-describedby`. Jeden element na formularz/dialog — id jest stałe,
 * a atrybut przycisku nadaje funkcja `describedBy` (tylko gdy powód istnieje). Tekst pomocniczy
 * akcji (np. podpowiedź „Prześlij ponownie nieudane (N)”) używa tego samego komponentu.
 */

import type { JSX } from 'react'
import FormHelperText from '@mui/material/FormHelperText'

export type DisabledReasonProps = {
  /** Stałe id elementu z tekstem — tę samą wartość przyjmuje `describedBy`. */
  id: string
  /** Powód/podpowiedź; `null` = element się nie renderuje (i atrybut przycisku znika). */
  reason: string | null
}

/** Wartość `aria-describedby` dla przycisku: id powodu albo `undefined` (atrybut zdjęty). */
export function describedBy(id: string, reason: string | null): string | undefined {
  return reason === null ? undefined : id
}

/** Pełna szerokość — w `DialogActions`/`SaveFooter` tekst zajmuje własny wiersz nad przyciskami. */
export function DisabledReason(props: DisabledReasonProps): JSX.Element | null {
  const { id, reason } = props
  if (reason === null) return null
  return (
    <FormHelperText id={id} sx={{ flexBasis: '100%', textAlign: 'right', my: 0 }}>
      {reason}
    </FormHelperText>
  )
}
