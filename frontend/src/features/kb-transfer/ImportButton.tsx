/**
 * Przycisk „Importuj" listy baz wiedzy (08 §7.15: obok „Utwórz bazę wiedzy", każdy zalogowany).
 * Otwiera dialog importu przez kontekst hosta (`openImport`); osobny plik, bo działa w nagłówku
 * strony (wewnątrz `<KbTransferHost>`), a `DatasetsPage.tsx` stoi na limicie `max-lines`.
 */

import FileUploadOutlinedIcon from '@mui/icons-material/FileUploadOutlined'
import Button from '@mui/material/Button'
import { useTranslation } from 'react-i18next'

import { useKbTransfer } from './KbTransferHost'

export function ImportButton() {
  const { t } = useTranslation()
  const { openImport } = useKbTransfer()
  return (
    <Button variant="outlined" startIcon={<FileUploadOutlinedIcon />} onClick={openImport}>
      {t('kbTransfer.import.button')}
    </Button>
  )
}
