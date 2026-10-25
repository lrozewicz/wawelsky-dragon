/**
 * Pole formularza modelu z etykietą STATYCZNĄ nad polem (QA T8, D3): motyw rysuje obramowanie
 * na korzeniu `OutlinedInput` i wyłącza notched outline (`src/theme/customizations/inputs.tsx`),
 * więc pływająca etykieta MUI (`TextField label` + `shrink`) leżałaby NA obramowaniu i
 * pierścieniu fokusa. `FormLabel` + `htmlFor`/`id` trzyma etykietę nad polem, a `getByLabel`
 * (e2e) i `getByLabelText` (Vitest) działają jak wcześniej — asocjacja `for`/`id`.
 */

import type { JSX } from 'react'
import FormLabel from '@mui/material/FormLabel'
import TextField from '@mui/material/TextField'
import type { TextFieldProps } from '@mui/material/TextField'

export type ModelTextFieldProps = Omit<TextFieldProps, 'label'> & {
  /** Id pola — łączy etykietę z inputem (`htmlFor`/`id`, `getByLabel`). */
  id: string
  /** Tekst etykiety nad polem (bez asteriska MUI — `required` dokleja gwiazdkę sam). */
  label: string
}

export function ModelTextField({
  id,
  label,
  required,
  ...props
}: ModelTextFieldProps): JSX.Element {
  return (
    <>
      <FormLabel htmlFor={id} required={required}>
        {label}
      </FormLabel>
      <TextField id={id} fullWidth size="small" required={required} {...props} />
    </>
  )
}
