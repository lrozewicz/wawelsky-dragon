/**
 * Strona użytkowników (kontrakt WP E3-6c2 §4, §T3 i §T4): szukaj z debounce 300 ms, przycisk
 * „Nowy użytkownik”, lista z serwerową paginacją i `Alert` błędu nad siatką. Siatkę ładujemy
 * przez `lazy`, żeby ciężki `@mui/x-data-grid` nie trafił do chunku strony. Szybkie akcje —
 * przełącznik „Aktywny” i nadanie/odebranie administratora — obsługujemy tutaj; pozostałe
 * pozycje menu odkładają wybór w stanie `{ kind, user }` i otwierają jeden z czterech dialogów.
 */

import { Suspense, lazy, useEffect, useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import type { GridPaginationModel } from '@mui/x-data-grid'
import { useRouteContext } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { QueryError } from '../../../components/QueryError'
import { USERS_PAGE_SIZE } from '../constants'
import { useSetUserActive, useUpdateUser, usersListQueryOptions } from '../queries'
import type { WdUser } from '../queries'
import { wdErrorKey } from '../wdClient'

import { ApiKeysDialog } from './ApiKeysDialog'
import { CreateUserDialog } from './CreateUserDialog'
import { DeleteUserDialog } from './DeleteUserDialog'
import { PasswordDialog } from './PasswordDialog'
import { UserDetailsDialog } from './UserDetailsDialog'
import type { UserActionKind } from './UserActionsMenu'

/** Opóźnienie szukania (kontrakt §T3 pkt 4). */
export const SEARCH_DEBOUNCE_MS = 300

/** Wybrana pozycja menu akcji wiersza — czyta ją slot dialogów T4. */
export type UserAction = { kind: UserActionKind; user: WdUser }

const UsersGrid = lazy(async () => {
  const module = await import('./UsersGrid')
  return { default: module.UsersGrid }
})

export function UsersPage(): JSX.Element {
  const { t } = useTranslation()
  // Kontekst trasy jest częściowy — bierzemy z niego wyłącznie identyfikator zalogowanego konta.
  const selfId = useRouteContext({
    strict: false,
    select: (context) => context.auth?.user?.id ?? null,
  })
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [pagination, setPagination] = useState<GridPaginationModel>({
    page: 0,
    pageSize: USERS_PAGE_SIZE,
  })
  const [createOpen, setCreateOpen] = useState(false)
  const [action, setAction] = useState<UserAction | null>(null)
  const [mutationError, setMutationError] = useState<unknown>(null)

  const setActive = useSetUserActive()
  const updateUser = useUpdateUser()

  // `q` idzie do zapytania 300 ms po ostatnim znaku, a nowa fraza wraca na pierwszą stronę.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQ(search)
      setPagination((current) => (current.page === 0 ? current : { ...current, page: 0 }))
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [search])

  const users = useQuery(
    usersListQueryOptions({ page: pagination.page + 1, pageSize: pagination.pageSize, q }),
  )

  function toggleActive(user: WdUser, active: boolean): void {
    setMutationError(null)
    setActive.mutate({ id: user.id, active }, { onError: (error) => setMutationError(error) })
  }

  function runAction(user: WdUser, kind: UserActionKind): void {
    // Rola nie ma dialogu — od razu PATCH z odwróconą wartością (kontrakt §T3 pkt 5).
    if (kind === 'role') {
      setMutationError(null)
      updateUser.mutate(
        { id: user.id, body: { is_superuser: !user.is_superuser } },
        { onError: (error) => setMutationError(error) },
      )
      return
    }
    setAction({ kind, user })
  }

  /** Zamknięcie dialogu akcji zeruje wybór z menu. */
  function clearAction(): void {
    setAction(null)
  }

  let list: JSX.Element
  if (users.isError) {
    // Kontrakt WP E3-7 §C6: błąd zapytania to `QueryError` z ponowieniem, nie ad-hoc `Alert`.
    list = <QueryError message={t('admin.common.loadError')} onRetry={() => void users.refetch()} />
  } else {
    list = (
      <Suspense fallback={<Skeleton variant="rounded" height={420} />}>
        <UsersGrid
          rows={users.data?.items ?? []}
          total={users.data?.total ?? 0}
          loading={users.isPending || users.isFetching}
          pagination={pagination}
          onPaginationModelChange={setPagination}
          selfId={selfId}
          onToggleActive={toggleActive}
          onAction={runAction}
        />
      </Suspense>
    )
  }

  return (
    <Stack spacing={2} data-testid="admin-users">
      {/* `useFlexGap` (wzorzec FilesToolbar E5-H8z): po zawinięciu „Nowy użytkownik” startuje
          przy lewej krawędzi — `margin-left` ze `spacing` wciskało go o 16 px (SC-E5-H9-07 k. 3). */}
      <Stack
        direction="row"
        spacing={2}
        useFlexGap
        sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 2 }}
      >
        <TextField
          size="small"
          label={t('admin.users.search')}
          value={search}
          data-testid="admin-users-search"
          onChange={(event) => setSearch(event.target.value)}
          sx={{ minWidth: 260 }}
        />
        <Button
          variant="contained"
          data-testid="admin-users-new"
          onClick={() => setCreateOpen(true)}
        >
          {t('admin.users.new')}
        </Button>
      </Stack>

      {mutationError !== null ? (
        <Alert severity="error">{t(wdErrorKey(mutationError))}</Alert>
      ) : null}

      {list}

      <CreateUserDialog open={createOpen} onClose={() => setCreateOpen(false)} />

      {/* Kontrakt WP E3-H2b §C2: montujemy wyłącznie dialog wybranej pozycji. Zamknięte okno
          kluczy i tak odpala pobranie listy, więc nie może wisieć w drzewie przy innych akcjach. */}
      {action === null ? null : (
        <>
          {action.kind === 'details' ? (
            <UserDetailsDialog open user={action.user} onClose={clearAction} />
          ) : null}
          {action.kind === 'password' ? (
            <PasswordDialog open user={action.user} onClose={clearAction} />
          ) : null}
          {action.kind === 'delete' ? (
            <DeleteUserDialog open user={action.user} onClose={clearAction} />
          ) : null}
          {action.kind === 'keys' ? (
            <ApiKeysDialog open user={action.user} onClose={clearAction} />
          ) : null}
        </>
      )}
    </Stack>
  )
}
