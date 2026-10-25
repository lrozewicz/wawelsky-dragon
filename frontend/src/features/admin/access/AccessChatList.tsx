/**
 * Czysta lista czatów z checkboxami grantów (brief T5 p. 3 i 5): bez zapytań i mutacji —
 * stan wyboru i zapis należą do `AccessPage`. Grant automatyczny jest zaznaczony na stałe
 * (checkbox `disabled`) i opisany chipem, a pod listą pojawia się podpowiedź, dlaczego.
 */

import type { InputHTMLAttributes, JSX } from 'react'
import Checkbox from '@mui/material/Checkbox'
import Chip from '@mui/material/Chip'
import FormControlLabel from '@mui/material/FormControlLabel'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import type { ChatListItem } from '../../chats/queries'

export function AccessChatList(props: {
  chats: ChatListItem[]
  selected: ReadonlySet<string>
  autoIds: ReadonlySet<string>
  onToggle: (chatId: string) => void
}): JSX.Element {
  const { t } = useTranslation()
  const hasAuto = props.autoIds.size > 0

  return (
    <Stack spacing={1}>
      {props.chats.map((chat) => {
        const auto = props.autoIds.has(chat.id)
        // Slot `input` typuje wyłącznie znane atrybuty `input` (bez `data-*`),
        // więc `data-testid` niesiemy jawnie typowanym obiektem.
        const inputProps: InputHTMLAttributes<HTMLInputElement> & Record<string, unknown> = {
          'data-testid': `admin-access-chat-${chat.id}`,
        }
        return (
          <Stack key={chat.id} direction="row" spacing={1} sx={{ alignItems: 'center' }}>
            <FormControlLabel
              control={
                <Checkbox
                  checked={auto || props.selected.has(chat.id)}
                  disabled={auto}
                  onChange={() => props.onToggle(chat.id)}
                  slotProps={{ input: inputProps }}
                />
              }
              label={chat.name}
            />
            {auto ? <Chip size="small" label={t('admin.access.auto')} /> : null}
          </Stack>
        )
      })}
      {hasAuto ? (
        <Typography variant="caption" color="text.secondary">
          {t('admin.access.autoHint')}
        </Typography>
      ) : null}
    </Stack>
  )
}
