/**
 * Formularz ustawień czatu — zawartość `ChatSettingsDrawer` (08 §7.7 p. 3, §8.2): trzy zakładki
 * i stopka Anuluj / Zapisz. Zapis idzie jednym PATCH-em z wyłącznie zmienionymi polami
 * (`buildPatch`), sukces zamyka szufladę (`onClose`) i pokazuje powiadomienie, a błąd API ląduje
 * w `Alert` na górze. „Anuluj” idzie przez `onCancel` — strażnik szuflady przy zmianach pyta
 * „Odrzucić zmiany?” (SC-V12-07), więc formularz podnosi do niej fakt „brudny”.
 *
 * Wydzielony z `ChatSettingsDrawer.tsx` (limit 300 linii eslint); remontowany per otwarcie
 * (`key={chatId}` w szufladzie) — stan startuje na nowo przy każdym otwarciu, bez efektów
 * inicjalizacyjnych i bez gubienia niezapisanych zmian przy refetchu.
 */

import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import Tab from '@mui/material/Tab'
import Tabs from '@mui/material/Tabs'
import { useTranslation } from 'react-i18next'

import useNotifications from '../../../hooks/useNotifications/useNotifications'
import { DisabledReason, describedBy } from '../../../components/DisabledReason'
import { modelsQueryOptions } from '../../models/queries'
import { datasetsListQueryOptions } from '../datasetsQuery'
import { buildModelOptions, modelsListQueryOptions } from '../modelsQuery'
import { useUpdateChat } from '../queries'
import type { Chat } from '../queries'
import { AssistantTab } from '../settings/AssistantTab'
import { DEFAULT_SYSTEM_PROMPT } from '../settings/defaultPrompt'
import { ModelTab } from '../settings/ModelTab'
import { PromptTab } from '../settings/PromptTab'
import { buildPatch, chatSettingsSchema, chatToFormValues } from '../settings/schema'
import { TAB_VALUES, mutationError, tabOfIssue } from '../settings/tabs'
import type { TabValue } from '../settings/tabs'
import type { ChatSettingsUpdate, ChatSettingsValues } from '../settings/schema'

export type ChatSettingsFormProps = {
  chatId: string
  chat: Chat
  /** Bezpośrednie zamknięcie po udanym zapisie — bez pytania o odrzucenie (SC-V12-07). */
  onClose: () => void
  /** „Anuluj” — przez strażnika: przy zmianach pyta „Odrzucić zmiany?”. */
  onCancel: () => void
  /** Podniesienie faktu „brudny” do szuflady (strażnik pilnuje Esc/tła/✕ w nagłówku). */
  onDirtyChange: (dirty: boolean) => void
  focusFilter: boolean
}

export function ChatSettingsForm(props: ChatSettingsFormProps) {
  const { chatId, chat, onClose, onCancel, onDirtyChange, focusFilter } = props
  const { t } = useTranslation()
  const { show } = useNotifications()

  const datasets = useQuery(datasetsListQueryOptions())
  const models = useQuery(modelsQueryOptions())
  const modelList = useQuery(modelsListQueryOptions())
  const updateChat = useUpdateChat(chatId)

  const [initial] = useState<ChatSettingsValues>(() => chatToFormValues(chat))
  const [values, setValues] = useState<ChatSettingsValues>(initial)
  const [tab, setTab] = useState<TabValue>('assistant')
  const [error, setError] = useState<string | null>(null)

  const parsed = chatSettingsSchema.safeParse(values)
  const issues = parsed.success ? [] : parsed.error.issues
  const errorAt = (path: string): string | null =>
    issues.find((issue) => issue.path.map(String).join('.') === path)?.message ?? null
  // Warunek ręczny bez klucza (T6 c): pierwszy błąd filtra trafia przy polu „Klucz” wiersza
  // warunku (AssistantTab → kreator), reszta błędów filtra i tak dotyczy pustych kluczy.
  const filterKeyError =
    issues.find((issue) => issue.path[0] === 'metaDataFilter' && issue.path[3] === 'key')
      ?.message ?? null
  // Pusta wartość warunku (SC-E67-06 k4): błąd dopiero po próbie zapisu — świeży wiersz nie krzyczy.
  const [attempted, setAttempted] = useState(false)
  const filterValueError = attempted
    ? (issues.find((issue) => issue.path[0] === 'metaDataFilter' && issue.path[3] === 'value')
        ?.message ?? null)
    : null

  const patch = buildPatch(initial, values)
  // U11: „Zapisz” wyłącza tylko brak zmian; błędy walidacji ujawnia klik (fokus + zakładka).
  const dirty = Object.keys(patch).length > 0
  // Powód nieaktywnego „Zapisz” (SC-V13-11): jedyną przyczyną jest brak zmian — błędy walidacji
  // nie wyłączają przycisku (U11), komunikat o blokadzie pokaże się dopiero po kliku.
  const saveReason = dirty ? null : t('common.noChangesToSave')

  // Strażnik zamknięcia (SC-V12-07) potrzebuje znać stan „brudny” także wtedy, gdy zamyka
  // Esc/tło/✕ w nagłówku szuflady — podnosimy go jednym poziom wyżej.
  useEffect(() => {
    onDirtyChange(dirty)
  }, [dirty, onDirtyChange])

  // Błąd walidacji pola z innej zakładki pokazujemy jako alert z przyciskiem przenoszącym
  // (na samej zakładce z błędnym polem alertu nie ma — tam błąd widać w helper textcie przy polu).
  const blocked = issues[0]
  const blockedTab = blocked === undefined ? null : tabOfIssue(blocked.path)

  // U11: klik „Zapisz” przy błędzie cofa fokus na pierwsze błędne pole — jednorazowo (T9):
  // ręczna zmiana zakładki już nie przeskakuje z powrotem fokusem do pola.
  const nameInputRef = useRef<HTMLInputElement>(null)
  const systemInputRef = useRef<HTMLInputElement>(null)
  const [focusTick, setFocusTick] = useState(0)
  const focusTabRef = useRef<TabValue | null>(null)
  const focusFilterErrorRef = useRef(false)
  useEffect(() => {
    if (focusTick === 0 || focusTabRef.current !== tab) return
    focusTabRef.current = null
    // Błąd filtra: przewiń do pierwszego błędnego pola (bez fokusu — combobox „Wartość” otwierałby
    // listę podpowiedzi nad komunikatem, a fokus na nazwie przewinąłby szufladę z dala od błędu).
    const invalid = focusFilterErrorRef.current
      ? document.querySelector<HTMLElement>('[aria-invalid="true"]')
      : null
    if (invalid !== null) invalid.scrollIntoView?.({ block: 'center' })
    else (tab === 'prompt' ? systemInputRef : nameInputRef).current?.focus()
  }, [focusTick, tab])

  const update: ChatSettingsUpdate = (changed) =>
    setValues((previous) => {
      const next = { ...previous, ...changed }
      // Pierwsza baza wiedzy przy pustym prompcie dostaje domyślny szablon z `{knowledge}` (C2);
      // bez niego walidacja blokowałaby zapis, a czat działałby wbrew domyślnemu promptowi API.
      if (
        previous.dataset_ids.length === 0 &&
        next.dataset_ids.length > 0 &&
        next.prompt_config.system.trim() === ''
      ) {
        return {
          ...next,
          prompt_config: { ...next.prompt_config, system: DEFAULT_SYSTEM_PROMPT },
        }
      }
      return next
    })

  function save(): void {
    // U11: klik przy błędzie nie wysyła PATCH-u — ujawnia pole i wraca do niego fokusem.
    if (issues.length > 0) {
      setAttempted(true)
      focusFilterErrorRef.current = issues[0]!.path[0] === 'metaDataFilter'
      // Fokus po zmianie `tab` dokłada efekt; tick wyzwala go też na zakładce bieżącej.
      const targetTab = tabOfIssue(issues[0]!.path)
      focusTabRef.current = targetTab
      setTab(targetTab)
      setFocusTick((tick) => tick + 1)
      return
    }
    if (!dirty) return
    updateChat.mutate(patch, {
      onSuccess: () => {
        // Toast znika sam (D4) — bez tego Snackbar zostaje do ręcznego zamknięcia.
        show(t('chat.settings.saved'), { severity: 'success', autoHideDuration: 4000 })
        onClose()
      },
      onError: (failure) => setError(mutationError(failure, t('chat.settings.saveError'), t)),
    })
  }

  const modelOptions = buildModelOptions(
    modelList.data ?? [],
    values.llm_id,
    models.data?.llm_id ?? '',
  )
  const rerankOptions = [
    ...new Set([values.rerank_id, models.data?.rerank_id ?? ''].filter((id) => id !== '')),
  ]

  return (
    <>
      {error !== null ? (
        <Alert severity="error" sx={{ mx: 2, mt: 1 }}>
          {error}
        </Alert>
      ) : null}
      {blocked !== undefined && blockedTab !== null && blockedTab !== tab ? (
        <Alert
          severity="warning"
          sx={{ mx: 2, mt: 1 }}
          action={
            <Button color="inherit" size="small" onClick={() => setTab(blockedTab)}>
              {t('chat.settings.blockedGoto')}
            </Button>
          }
        >
          {t('chat.settings.blockedHint', {
            tab: t(`chat.settings.tab.${blockedTab}`),
            message: t(blocked.message),
          })}
        </Alert>
      ) : null}
      <Tabs
        value={tab}
        variant="scrollable"
        onChange={(_event, next: TabValue) => setTab(next)}
        sx={{ px: 2, borderBottom: 1, borderColor: 'divider' }}
      >
        {TAB_VALUES.map((value) => (
          <Tab key={value} value={value} label={t(`chat.settings.tab.${value}`)} />
        ))}
      </Tabs>
      <Box sx={{ p: 2, flex: 1, overflowY: 'auto' }}>
        {tab === 'assistant' ? (
          <AssistantTab
            values={values}
            datasets={datasets.data ?? []}
            nameError={errorAt('name')}
            metaFilterKeyError={filterKeyError}
            metaFilterValueError={filterValueError}
            focusFilter={focusFilter}
            nameInputRef={nameInputRef}
            onUpdate={update}
          />
        ) : null}
        {tab === 'prompt' ? (
          <PromptTab
            values={values}
            rerankOptions={rerankOptions}
            systemError={errorAt('prompt_config.system')}
            systemInputRef={systemInputRef}
            onUpdate={update}
          />
        ) : null}
        {tab === 'model' ? (
          <ModelTab values={values} modelOptions={modelOptions} onUpdate={update} />
        ) : null}
      </Box>
      <Stack
        direction="row"
        spacing={1}
        sx={{
          p: 2,
          justifyContent: 'flex-end',
          flexWrap: 'wrap',
          rowGap: 0.5,
          borderTop: 1,
          borderColor: 'divider',
        }}
      >
        <DisabledReason id="chat-settings-save-reason" reason={saveReason} />
        <Button onClick={onCancel}>{t('common.cancel')}</Button>
        <Button
          variant="contained"
          disabled={!dirty}
          loading={updateChat.isPending}
          onClick={save}
          aria-describedby={describedBy('chat-settings-save-reason', saveReason)}
        >
          {t('chat.settings.save')}
        </Button>
      </Stack>
    </>
  )
}
