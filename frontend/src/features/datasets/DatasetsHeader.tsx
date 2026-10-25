/**
 * Nagłówek strony „Bazy wiedzy” (SC-E67-05): tytuł w jednej linii i przyciski „Importuj” /
 * „Utwórz dataset” bez łamania tekstu. Przy ciasnym ekranie (320 px, 390 px z zoomem 125 %)
 * przyciski zawijają się POD tytuł (`flexWrap`), a strona nie dostaje poziomego przewijania.
 */

import type { ReactNode } from 'react'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { ImportButton } from '../kb-transfer/ImportButton'

export function DatasetsHeader(props: { createButton: ReactNode }) {
  const { t } = useTranslation()

  return (
    <Box
      sx={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 2,
        mb: 2,
        // Kompensuje spacing={2} PageContainer (tytuł tuż pod breadcrumbs jak na innych stronach).
        mt: -2,
      }}
    >
      <Typography
        variant="h4"
        sx={{ whiteSpace: 'nowrap', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}
      >
        {t('datasets.list.title')}
      </Typography>
      <Box
        sx={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 1,
          // Po zawinięciu pod tytuł akcje zostają po prawej, jak obok tytułu.
          marginLeft: 'auto',
          '& .MuiButton-root': { whiteSpace: 'nowrap' },
        }}
      >
        <ImportButton />
        {props.createButton}
      </Box>
    </Box>
  )
}
