/**
 * Strona Klucze API (brief E3-6c1 T4): karta „API serwera”, przycisk tworzenia klucza i lista
 * kluczy użytkownika. Siatkę ładujemy przez `lazy`, żeby ciężki `@mui/x-data-grid` nie trafiał
 * do chunku strony (wzór: `features/admin/users/UsersPage.tsx`).
 */

import { Suspense, lazy, useState } from 'react'
import type { JSX } from 'react'
import AddRoundedIcon from '@mui/icons-material/AddRounded'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../../api/envelope'
import { QueryError } from '../../../components/QueryError'
import { tokensQueryOptions } from '../queries'

import { CreateKeyDialog } from './CreateKeyDialog'
import { GridSkeleton } from './GridSkeleton'
import { McpServerCard } from './McpServerCard'
import { ServerApiCard } from './ServerApiCard'

const KeysGrid = lazy(async () => {
  const module = await import('./KeysGrid')
  return { default: module.KeysGrid }
})

/** Tekst błędu: nagłówek z i18n plus komunikat z API (kontrakt §0). */
function errorText(error: unknown, title: string, fallback: string): string {
  const message = error instanceof ApiError && error.message !== '' ? error.message : fallback
  return `${title}: ${message}`
}

export function ApiKeysPage(): JSX.Element {
  const { t } = useTranslation()
  const [createOpen, setCreateOpen] = useState(false)
  const tokens = useQuery(tokensQueryOptions())

  return (
    <Stack spacing={2}>
      <ServerApiCard />
      <McpServerCard />
      <Stack direction="row" sx={{ justifyContent: 'flex-end' }}>
        <Button
          variant="contained"
          startIcon={<AddRoundedIcon />}
          onClick={() => setCreateOpen(true)}
        >
          {t('settings.keys.create')}
        </Button>
      </Stack>
      {tokens.isError ? (
        // Kontrakt WP E3-7 §C6: błąd zapytania to `QueryError` z ponowieniem, nie ad-hoc `Alert`.
        <QueryError
          message={errorText(tokens.error, t('settings.error.title'), t('settings.keys.error'))}
          onRetry={() => void tokens.refetch()}
        />
      ) : (
        <Suspense fallback={<GridSkeleton />}>
          <KeysGrid rows={tokens.data ?? []} loading={tokens.isPending} />
        </Suspense>
      )}
      <CreateKeyDialog open={createOpen} onClose={() => setCreateOpen(false)} />
    </Stack>
  )
}
