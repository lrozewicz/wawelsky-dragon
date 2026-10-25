/**
 * Dostęp do asystentów (brief T5, kontrakt WP E3-6c2 §4): wybór e-maila użytkownika
 * (`Autocomplete` freeSolo z podpowiedziami z listy kont), lista czatów z checkboxami
 * grantów i zapis całego zbioru przez `useReplaceGrants` (PUT zastępuje zbiór).
 * Granty nadane automatycznie są zaznaczone i zablokowane, ale wysyłamy je jawnie —
 * serwer i tak ich nie usuwa.
 */

import type { JSX } from 'react'
import { useMemo, useState } from 'react'
import Alert from '@mui/material/Alert'
import Autocomplete from '@mui/material/Autocomplete'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { chatsListQueryOptions } from '../../chats/queries'
import { isAutoProvisioned } from '../constants'
import { grantsQueryOptions, useReplaceGrants, usersListQueryOptions } from '../queries'
import { wdErrorKey } from '../wdClient'

import { AccessChatList } from './AccessChatList'

/** Ile e-maili pobieramy do podpowiedzi `Autocomplete` (brief T5 p. 1). */
const EMAIL_OPTIONS_PAGE_SIZE = 20

export function AccessPage(): JSX.Element {
  const { t } = useTranslation()

  const [email, setEmail] = useState('')
  const [inputValue, setInputValue] = useState('')
  // Lokalny wybór trzymamy razem ze źródłem, z którego powstał: nowy e-mail albo nowy
  // zestaw grantów (inna tożsamość tablicy) unieważnia wybór bez efektu z `setState`.
  const [selection, setSelection] = useState<{ source: unknown; ids: ReadonlySet<string> }>({
    source: undefined,
    ids: new Set(),
  })

  const users = useQuery(
    usersListQueryOptions({ page: 1, pageSize: EMAIL_OPTIONS_PAGE_SIZE, q: inputValue }),
  )
  const chats = useQuery(chatsListQueryOptions())
  const grants = useQuery(grantsQueryOptions(email))
  const replaceGrants = useReplaceGrants()

  const grantList = grants.data
  // Zbiór z serwera: start dla lokalnego wyboru i punkt odniesienia dla „czy są zmiany”.
  const serverIds = useMemo(
    () => new Set((grantList ?? []).map((grant) => grant.chat_id)),
    [grantList],
  )
  const autoIds = useMemo(
    () =>
      new Set(
        (grantList ?? [])
          .filter((grant) => isAutoProvisioned(grant.created_by))
          .map((grant) => grant.chat_id),
      ),
    [grantList],
  )

  // Wybór użytkownika liczy się tylko dla bieżącego zestawu grantów; po zmianie danych wracamy do serwera.
  const selected = selection.source === grantList ? selection.ids : serverIds

  const changed =
    selected.size !== serverIds.size || [...selected].some((chatId) => !serverIds.has(chatId))

  function toggle(chatId: string): void {
    const next = new Set(selected)
    if (next.has(chatId)) next.delete(chatId)
    else next.add(chatId)
    setSelection({ source: grantList, ids: next })
  }

  return (
    <Stack spacing={3} data-testid="admin-access">
      <Autocomplete
        freeSolo
        // Blur zatwierdza wpisany tekst (brief T5 p. 1); Enter i klik opcji działają domyślnie.
        autoSelect
        options={(users.data?.items ?? []).map((user) => user.email)}
        value={email === '' ? null : email}
        inputValue={inputValue}
        onInputChange={(_event, next) => setInputValue(next)}
        onChange={(_event, next) => {
          setEmail(next ?? '')
          // Komunikat poprzedniego zapisu nie może zostać na ekranie innego użytkownika.
          replaceGrants.reset()
        }}
        renderInput={(params) => (
          <TextField
            {...params}
            label={t('admin.access.email')}
            slotProps={{
              ...params.slotProps,
              htmlInput: {
                ...params.slotProps.htmlInput,
                'data-testid': 'admin-access-email',
              },
            }}
          />
        )}
      />

      {email === '' ? (
        <Typography color="text.secondary">{t('admin.access.pickUser')}</Typography>
      ) : chats.data !== undefined && chats.data.length === 0 ? (
        <Typography color="text.secondary">{t('admin.access.noChats')}</Typography>
      ) : (
        <Stack spacing={1}>
          <Typography variant="h6">{t('admin.access.chats')}</Typography>
          <AccessChatList
            chats={chats.data ?? []}
            selected={selected}
            autoIds={autoIds}
            onToggle={toggle}
          />
        </Stack>
      )}

      {replaceGrants.isSuccess ? <Alert severity="success">{t('admin.access.saved')}</Alert> : null}
      {replaceGrants.isError ? (
        <Alert severity="error">{t(wdErrorKey(replaceGrants.error))}</Alert>
      ) : null}

      <Button
        variant="contained"
        data-testid="admin-access-save"
        disabled={email === '' || !changed || replaceGrants.isPending}
        onClick={() => replaceGrants.mutate({ email, chatIds: [...selected] })}
      >
        {t('admin.access.save')}
      </Button>
    </Stack>
  )
}
