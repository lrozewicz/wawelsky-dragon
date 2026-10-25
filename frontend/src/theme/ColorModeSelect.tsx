// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/shared-theme/ColorModeSelect.tsx (MIT). Zmiany: import typu (type SelectProps); etykiety pozycji i aria-label przez i18n (t('theme.*')); eslint-disable dla @ts-ignore z upstream; formatowanie Prettier (DEC-038).
import { useColorScheme } from '@mui/material/styles'
import MenuItem from '@mui/material/MenuItem'
import Select, { type SelectProps } from '@mui/material/Select'
import { useTranslation } from 'react-i18next'

export default function ColorModeSelect(props: SelectProps) {
  const { t } = useTranslation()
  const { mode, setMode } = useColorScheme()
  if (!mode) {
    return null
  }
  return (
    <Select
      value={mode}
      onChange={(event) => setMode(event.target.value as 'system' | 'light' | 'dark')}
      aria-label={t('theme.mode')}
      SelectDisplayProps={{
        // eslint-disable-next-line @typescript-eslint/ban-ts-comment -- wyjątek CONTRACT C0 pkt 2: @ts-ignore z upstream
        // @ts-ignore
        'data-screenshot': 'toggle-mode',
      }}
      {...props}
    >
      <MenuItem value="system">{t('theme.system')}</MenuItem>
      <MenuItem value="light">{t('theme.light')}</MenuItem>
      <MenuItem value="dark">{t('theme.dark')}</MenuItem>
    </Select>
  )
}
