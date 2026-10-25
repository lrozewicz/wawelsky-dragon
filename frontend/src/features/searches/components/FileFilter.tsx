/**
 * Filtr plików wyszukiwania (kontrakt WP E4-4b §4): przycisk z liczbą wybranych otwiera popover
 * z listą plików z `aggs` (etykieta `name (count)`) i przyciskiem czyszczenia filtra. Zmiana
 * checkboxa oddaje nową listę `doc_id` przez `onChange`.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { useTranslation } from 'react-i18next'
import Button from '@mui/material/Button'
import Checkbox from '@mui/material/Checkbox'
import FormControlLabel from '@mui/material/FormControlLabel'
import Popover from '@mui/material/Popover'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'

import type { DocAgg } from '../../datasets/retrieval/queries'

export type FileFilterProps = {
  aggs: DocAgg[]
  selected: string[]
  onChange: (docIds: string[]) => void
}

export function FileFilter(props: FileFilterProps): JSX.Element {
  const { aggs, selected, onChange } = props
  const { t } = useTranslation()
  // Kotwica popovera (element przycisku) — `null` = zamknięty.
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)

  /** Nowa lista wybranych dokumentów po zaznaczeniu/odznaczeniu jednego z nich. */
  const toggle = (docId: string, checked: boolean): string[] =>
    checked ? [...selected, docId] : selected.filter((id) => id !== docId)

  const button = t('searches.filter.button')
  const label = selected.length > 0 ? `${button} (${selected.length})` : button

  return (
    <>
      <Button
        size="small"
        data-testid="file-filter"
        onClick={(event) => setAnchor(event.currentTarget)}
      >
        {label}
      </Button>
      <Popover
        open={anchor !== null}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Stack spacing={1} sx={{ p: 2, minWidth: 240 }}>
          <Typography variant="subtitle2">{t('searches.filter.title')}</Typography>
          <Button size="small" onClick={() => onChange([])}>
            {t('searches.filter.clear')}
          </Button>
          {aggs.map((doc) => (
            <FormControlLabel
              key={doc.doc_id}
              control={
                <Checkbox
                  size="small"
                  checked={selected.includes(doc.doc_id)}
                  onChange={(event) => onChange(toggle(doc.doc_id, event.target.checked))}
                />
              }
              label={t('searches.filter.item', { name: doc.doc_name, count: doc.count })}
            />
          ))}
        </Stack>
      </Popover>
    </>
  )
}
