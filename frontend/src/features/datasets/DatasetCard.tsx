/** Karta bazy wiedzy na liście `/datasets` (nazwa, „N plików”, menu akcji) — wydzielona z `DatasetsPage`. */

import { useNavigate } from '@tanstack/react-router'
import MoreVertIcon from '@mui/icons-material/MoreVert'
import Avatar from '@mui/material/Avatar'
import Card from '@mui/material/Card'
import CardActionArea from '@mui/material/CardActionArea'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { isPlainLeftClick } from '../../lib/linkClick'
import { datasetInitials } from './detail/DatasetHeader'
import type { DatasetListed } from './queries'

/**
 * Adres karty dla zwykłego `<a>` (`CardActionArea component="a"`) — jak `ChatsPage` dla `/chat/:id`.
 * Nawigacja po utworzeniu datasetu idzie już typowanym `navigate` (kontrakt WP E3-3b §T4).
 */
function datasetHref(id: string): string {
  return `/dataset/files/${id}`
}

export function DatasetCard(props: {
  dataset: DatasetListed
  onMenuOpen: (anchor: HTMLElement) => void
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { dataset } = props
  const href = datasetHref(dataset.id)

  return (
    <Card data-testid="dataset-card" sx={{ position: 'relative', height: '100%' }}>
      <CardActionArea
        component="a"
        href={href}
        // Zwykły klik nawiguje routerem (bez przeładowania); modyfikatory i inne przyciski
        // zostawiamy przeglądarce — `<a href>` zachowuje zatem semantykę linku (kontrakt §C2).
        onClick={(event) => {
          if (!isPlainLeftClick(event)) return
          event.preventDefault()
          void navigate({ href })
        }}
        sx={{ height: '100%' }}
      >
        <Stack spacing={1} sx={{ p: 2, pr: 6, height: '100%', alignItems: 'flex-start' }}>
          <Avatar>{datasetInitials(dataset.name)}</Avatar>
          <Typography variant="subtitle1" noWrap sx={{ width: '100%' }}>
            {dataset.name}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t('datasets.list.files', { count: dataset.document_count })}
          </Typography>
        </Stack>
      </CardActionArea>
      <IconButton
        aria-label={t('datasets.list.menuLabel', { name: dataset.name })}
        onClick={(event) => props.onMenuOpen(event.currentTarget)}
        sx={{ position: 'absolute', top: 8, right: 8 }}
      >
        <MoreVertIcon />
      </IconButton>
    </Card>
  )
}
