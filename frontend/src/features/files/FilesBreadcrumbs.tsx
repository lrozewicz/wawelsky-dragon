/**
 * Ścieżka nawigacji po folderach (kontrakt WP E4-5c §3, §7): „Pliki” → przodkowie → bieżący
 * folder. API zwraca łańcuch w kolejności [bieżący, …, root], a `ancestorsQueryOptions` odwraca
 * go na [root, …, bieżący]; pierwszy element to systemowy root, więc pomijamy go i zastępujemy
 * etykietą `files.root`. Ostatni element nie jest linkiem (`aria-current="page"`).
 * Dla root-u (`folderId === undefined`) pokazujemy sam tekst `files.root`.
 */

import type { JSX } from 'react'
import NavigateNextRoundedIcon from '@mui/icons-material/NavigateNextRounded'
import Breadcrumbs from '@mui/material/Breadcrumbs'
import Link from '@mui/material/Link'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ancestorsQueryOptions } from './queries'

export type FilesBreadcrumbsProps = {
  folderId: string | undefined
  onNavigate: (folderId: string | undefined) => void
}

export function FilesBreadcrumbs(props: FilesBreadcrumbsProps): JSX.Element {
  const { folderId, onNavigate } = props
  const { t } = useTranslation()
  const ancestors = useQuery(ancestorsQueryOptions(folderId))
  // Pomijamy systemowy root z API — jego rolę pełni etykieta `files.root`.
  const trail = ancestors.data?.slice(1) ?? []

  return (
    <Breadcrumbs
      data-testid="files-breadcrumbs"
      aria-label={t('nav.breadcrumb')}
      separator={<NavigateNextRoundedIcon fontSize="small" />}
    >
      {folderId === undefined ? (
        <Typography sx={{ color: 'text.primary', fontWeight: 600 }}>{t('files.root')}</Typography>
      ) : (
        [
          <Link
            key="root"
            component="button"
            type="button"
            underline="hover"
            color="inherit"
            onClick={() => onNavigate(undefined)}
          >
            {t('files.root')}
          </Link>,
          ...trail.map((folder, index) =>
            index === trail.length - 1 ? (
              <Typography
                key={folder.id}
                aria-current="page"
                sx={{ color: 'text.primary', fontWeight: 600 }}
              >
                {folder.name}
              </Typography>
            ) : (
              <Link
                key={folder.id}
                component="button"
                type="button"
                underline="hover"
                color="inherit"
                onClick={() => onNavigate(folder.id)}
              >
                {folder.name}
              </Link>
            ),
          ),
        ]
      )}
    </Breadcrumbs>
  )
}
