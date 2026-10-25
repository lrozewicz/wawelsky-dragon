/**
 * Dialog usuwania bazy wiedzy z listą powiązań (K20 §4, SC-V12-04): przed potwierdzeniem pokazuje,
 * które czaty i wyszukiwarki stracą źródło („Usuń mimo to”). Wzór: `components/ConfirmDialog.tsx`
 * (nie modyfikujemy components/**), sekcja powiązań z `GET /api/wd/v1/datasets/{id}/usage`
 * (`useDatasetUsage`). Nazwy to zwykły tekst (decyzja Architekta: dialog nie nawiguje), długie
 * nazwy zawijane (`overflowWrap: 'anywhere'`), lista w kontenerze przewijanym do 40 % okna.
 * Stany sekcji: ładowanie (szkielet, potwierdzenie nieaktywne), błąd trasy (komunikat,
 * potwierdzenie aktywne — dialog działa jak dziś), dane (lista; bez powiązań sekcji brak —
 * dialog jak przed V12-3).
 */

import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogContentText from '@mui/material/DialogContentText'
import DialogTitle from '@mui/material/DialogTitle'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import { useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { DatasetListed } from './queries'
import { useDatasetUsage } from './usageQueries'

export type DeleteDatasetDialogProps = {
  dataset: DatasetListed
  /** Trwa mutacja usuwania — potwierdzenie pokazuje wskaźnik (jak w `ConfirmDialog`). */
  loading: boolean
  onConfirm: () => void
  onCancel: () => void
}

/**
 * Kontener listy powiązań: punktory (odróżnialne pozycje), przewijany, maks. 40 % wysokości
 * okna, w ramce — lista wygląda jak osobne pole (T8, review T6: sygnał przewijania nie może
 * zależeć od koloru tła; maski gradientowe w kolorze `background.paper` dawały ciemny pas w
 * ciemnym motywie). O przepełnieniu informuje podpowiedź tekstowa pod listą (`UsageList`).
 * `paddingLeft` utrzymuje punktory wewnątrz kontenera (bez przycięcia przez `overflowY`).
 */
const listSx = {
  margin: 0,
  paddingY: 0.5,
  paddingLeft: 2.5,
  paddingRight: 1,
  listStyle: 'disc',
  maxHeight: '40vh',
  overflowY: 'auto',
  border: '1px solid',
  borderColor: 'divider',
  borderRadius: 1,
} as const

/** Nagłówek sekcji („Czaty (N)”): pogrubiony, by było jasne, do której grupy należą pozycje. */
const SECTION_LABEL_SX = { fontWeight: 600 } as const

/** Pozycja listy: odstęp + cienki separator oddzielający zawinięte nazwy (QA V12-3-1). */
const ITEM_SX = {
  overflowWrap: 'anywhere',
  paddingY: 0.5,
  borderBottom: '1px solid',
  borderColor: 'divider',
} as const

/** Nazwy jako zwykły tekst w liście (wrap długich pozycji, bez linków — decyzja Architekta). */
function UsageList(props: {
  label: string
  testId: string
  items: ReadonlyArray<{ id: string; name: string }>
}) {
  const { t } = useTranslation()
  const listRef = useRef<HTMLUListElement | null>(null)
  // T8: podpowiedź przewijania tylko gdy lista się nie mieści (inaczej promptuje przewijanie
  // tam, gdzie nic nie ma do przewinięcia). Pomiar po layoutcie i przy każdej zmianie rozmiaru
  // (dołączenie pozycji, zwinięcie okna) — niezależny od koloru tła, więc motywo-bezpieczny.
  const [scrollable, setScrollable] = useState(false)

  useLayoutEffect(() => {
    const element = listRef.current
    if (element === null) {
      return undefined
    }
    const update = () => setScrollable(element.scrollHeight > element.clientHeight)
    update()
    const observer = new ResizeObserver(update)
    observer.observe(element)
    return () => observer.disconnect()
  }, [props.items])

  return (
    <>
      <Typography variant="body2" sx={SECTION_LABEL_SX}>
        {props.label}
      </Typography>
      <Box
        component="ul"
        ref={listRef}
        data-testid={props.testId}
        aria-label={props.label}
        tabIndex={0}
        sx={listSx}
      >
        {props.items.map((item) => (
          <Typography key={item.id} component="li" variant="body2" sx={ITEM_SX}>
            {item.name}
          </Typography>
        ))}
      </Box>
      {scrollable ? (
        <Typography
          variant="caption"
          color="text.secondary"
          data-testid="delete-dataset-usage-scrollhint"
        >
          {t('datasets.delete.usage.scrollHint')}
        </Typography>
      ) : null}
    </>
  )
}

export function DeleteDatasetDialog(props: DeleteDatasetDialogProps) {
  const { t } = useTranslation()
  const usage = useDatasetUsage(props.dataset.id)
  // „Usuń mimo to” i sekcja przy jakimkolwiek powiązaniu (CONTRACT WP V12-3 §Decyzje UI).
  const hasBindings =
    usage.data !== undefined &&
    (usage.data.chats.length > 0 ||
      usage.data.searches.length > 0 ||
      usage.data.hidden_chats > 0 ||
      usage.data.hidden_searches > 0)
  const usageLoading = usage.isPending && usage.isFetching

  return (
    <Dialog
      open
      onClose={props.onCancel}
      maxWidth="xs"
      fullWidth
      data-testid="delete-dataset-dialog"
    >
      <DialogTitle>{t('datasets.list.deleteTitle')}</DialogTitle>
      <DialogContent>
        <DialogContentText>
          {t('datasets.list.deleteMessage', { name: props.dataset.name })}
        </DialogContentText>

        {usageLoading ? (
          <Stack spacing={1} sx={{ marginTop: 2 }} data-testid="delete-dataset-usage-loading">
            <Skeleton />
            <Skeleton width="60%" />
          </Stack>
        ) : null}

        {usage.isError ? (
          <Alert severity="error" sx={{ marginTop: 2 }} data-testid="delete-dataset-usage-error">
            {t('datasets.delete.usage.loadError')}
          </Alert>
        ) : null}

        {usage.data !== undefined && hasBindings ? (
          <Stack spacing={1} sx={{ marginTop: 2 }} data-testid="delete-dataset-usage">
            <Typography variant="body2">{t('datasets.delete.usage.title')}</Typography>
            {usage.data.chats.length > 0 ? (
              <UsageList
                label={t('datasets.delete.usage.chats', { count: usage.data.chats.length })}
                testId="delete-dataset-usage-chats"
                items={usage.data.chats}
              />
            ) : null}
            {usage.data.searches.length > 0 ? (
              <UsageList
                label={t('datasets.delete.usage.searches', { count: usage.data.searches.length })}
                testId="delete-dataset-usage-searches"
                items={usage.data.searches}
              />
            ) : null}
            {usage.data.hidden_chats > 0 || usage.data.hidden_searches > 0 ? (
              <Stack spacing={0.5} data-testid="delete-dataset-usage-hidden">
                {usage.data.hidden_chats > 0 ? (
                  <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>
                    {t('datasets.delete.usage.hiddenChats', { count: usage.data.hidden_chats })}
                  </Typography>
                ) : null}
                {usage.data.hidden_searches > 0 ? (
                  <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>
                    {t('datasets.delete.usage.hiddenSearches', {
                      count: usage.data.hidden_searches,
                    })}
                  </Typography>
                ) : null}
              </Stack>
            ) : null}
            {usage.data.truncated ? (
              <Typography variant="body2">{t('datasets.delete.usage.truncated')}</Typography>
            ) : null}
            <Typography variant="body2">{t('datasets.delete.usage.impact')}</Typography>
          </Stack>
        ) : null}
      </DialogContent>
      <DialogActions>
        <Button onClick={props.onCancel}>{t('common.cancel')}</Button>
        <Button
          variant="contained"
          color="error"
          data-testid="delete-dataset-confirm"
          loading={props.loading || usageLoading}
          onClick={props.onConfirm}
          sx={(theme) => ({
            // Ciemny motyw: hover MUI ciemnieje tło do `error.dark` (red[700]) przy prawie
            // czarnym contrastText — etykieta ginie (~1.4:1). Hover zostaje na `error.main`
            // (jasne tło, kontrast bez zmian); sygnałem hoveru jest cień domyślnego contained.
            ...theme.applyStyles('dark', {
              '&:hover': { backgroundColor: 'error.main' },
            }),
          })}
        >
          {hasBindings ? t('datasets.delete.usage.confirmAnyway') : t('datasets.list.delete')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
