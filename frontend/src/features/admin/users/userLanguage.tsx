import type { JSX } from 'react'
import MenuItem from '@mui/material/MenuItem'
import TextField from '@mui/material/TextField'
import { useTranslation } from 'react-i18next'

import { resolveLanguage } from '../../../i18n'

/** Język konta w formularzach: pusty oznacza, że użytkownik nic nie wybrał. */
export type AccountLanguage = '' | 'pl' | 'en'

/** Wartość z bazy (także starsze 'Polish', 'English') → opcja formularza. */
export function accountLanguage(value: string): AccountLanguage {
  return value === '' ? '' : resolveLanguage(value)
}

export function UserLanguageField(props: {
  value: AccountLanguage
  onChange: (value: AccountLanguage) => void
}): JSX.Element {
  const { t } = useTranslation()

  return (
    <TextField
      select
      label={t('admin.users.details.language')}
      value={props.value}
      onChange={(event) => props.onChange(event.target.value as AccountLanguage)}
      slotProps={{
        inputLabel: { shrink: true },
        select: { displayEmpty: true },
      }}
    >
      <MenuItem value="">{t('admin.users.language.unset')}</MenuItem>
      <MenuItem value="pl">{t('language.pl')}</MenuItem>
      <MenuItem value="en">{t('language.en')}</MenuItem>
    </TextField>
  )
}
