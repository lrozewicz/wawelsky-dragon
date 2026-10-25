/**
 * Obszar roboczy czatu `/chat/:id?conversationId=` (08 §7.7, kontrakt WP E3-5b §T6b):
 * trzy kolumny — panel rozmów (T4), kolumna konwersacji (nagłówek z nazwą rozmowy i zębatką,
 * lista wiadomości T5b, pole pytania T6a) oraz szuflady — ustawień czatu i podglądu dokumentu.
 *
 * Źródłem prawdy o otwartej rozmowie jest adres (`conversationId` z search trasy, wchodzi propsem),
 * a bieżącą wymianę dokłada `useChatStream` (T2): historia z `GET …/sessions/{sid}` plus para live,
 * dopóki historia nie przyniesie już tej samej wiadomości asystenta (deduplikacja po `id`).
 * Sesja tymczasowa (DEC-078) jest czysto kliencka: „+” daje `conversationId = null`, pierwsze
 * pytanie idzie bez `session_id`, a po pierwszej ramce z `session_id` strona zgłasza go do adresu.
 *
 * Markdown (`react-markdown`) jest ciężki, więc `MessageList` trafia do leniwego chunku (§T6b).
 */

import { Suspense, lazy, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { JSX } from 'react'
import { useQuery } from '@tanstack/react-query'
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import CircularProgress from '@mui/material/CircularProgress'
import Drawer from '@mui/material/Drawer'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import useMediaQuery from '@mui/material/useMediaQuery'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../api/envelope'

import { ChatSettingsDrawer } from './components/ChatSettingsDrawer'
import { ChatInput } from './input/ChatInput'
import { filterLabels } from './input/filterLabels'
import { DocumentPreviewDrawer } from './preview/DocumentPreviewDrawer'
import { chatQueryOptions } from './queries'
import { historyToMessages, liveStatus, liveToMessages } from './sessions/chatMessages'
import type { ChatMessage } from './sessions/chatMessages'
import { SESSIONS_PANEL_WIDTH, SessionsPanel } from './sessions/SessionsPanel'
import { sessionQueryOptions, useMessageFeedback } from './sessions/sessionQueries'
import { useChatStream } from './stream/useChatStream'

const MessageList = lazy(() =>
  import('./messages/MessageList').then((module) => ({ default: module.MessageList })),
)

export type ChatWorkspacePageProps = {
  chatId: string
  /** Sesja z adresu (`?conversationId=`); brak = rozmowa tymczasowa (DEC-078). */
  conversationId?: string
  /** Zapis wybranej rozmowy do adresu (`null` = rozmowa tymczasowa). */
  onConversationChange: (sessionId: string | null) => void
}

export function ChatWorkspacePage(props: ChatWorkspacePageProps): JSX.Element {
  const { chatId, conversationId, onConversationChange } = props
  const { t } = useTranslation()

  // Wysokość obszaru roboczego liczona z faktycznego układu aplikacji (R-UI-05): nad stroną
  // jest margines nawigacji mobilnej i nagłówek o wysokości zależnej od treści, więc stałe
  // `100vh` ignorowałoby AppBar i oderwało pole pytania od dolnej krawędzi. Mierzymy górną
  // krawędź kontenera (raz, przy zmianie rozmiaru okna) i dopełniamy do pełnego viewportu.
  const rootRef = useRef<HTMLDivElement | null>(null)
  const [height, setHeight] = useState<string | undefined>(undefined)
  useLayoutEffect(() => {
    const measure = (): void => {
      const root = rootRef.current
      if (root !== null) setHeight(`calc(100dvh - ${root.getBoundingClientRect().top}px)`)
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])

  const activeSessionId = conversationId ?? null
  const chat = useQuery(chatQueryOptions(chatId))
  const session = useQuery({
    ...sessionQueryOptions(chatId, activeSessionId ?? ''),
    enabled: activeSessionId !== null,
  })

  // Poniżej `md` panel rozmów startuje zwinięty, powyżej — rozwinięty (stan lokalny, §T6b).
  // `noSsr` sprawia, że dopasowanie media query jest znane już przy montowaniu (bez tego pierwszy
  // render bierze wartość domyślną `false` i wąskie okno startuje z rozwiniętym panelem).
  const belowMd = useMediaQuery((theme) => theme.breakpoints.down('md'), { noSsr: true })
  // Ręczny wybór użytkownika obowiązuje dla progu `md`, przy którym go podjęto; zmiana szerokości
  // (obrót telefonu, przeciągnięcie okna) wraca do układu domyślnego, a panel nadal da się zwinąć
  // i rozwinąć ręcznie. Rozstrzygnięcie trzymamy razem z progiem, żeby obyło się bez efektu.
  const [manual, setManual] = useState<{ belowMd: boolean; collapsed: boolean } | null>(null)
  const collapsed = manual !== null && manual.belowMd === belowMd ? manual.collapsed : belowMd
  // Poniżej `md` rozwinięty panel rozmów jest nakładką (szufladą), żeby nie ściskał kolumny
  // czatu do ~100 px (QA E5-H8z-4); powyżej `md` — kolumną obok czatu, jak dotąd.
  const panelInDrawer = belowMd && !collapsed
  // Ustawienia otwarte od chipa filtra (`'filter'`) mają sekcję filtra w widoku (SC-E67-06 k5).
  const [settings, setSettings] = useState<'default' | 'filter' | null>(null)
  const [preview, setPreview] = useState<{ docId: string; docName: string } | null>(null)

  // Rozmowa, do której należy bieżąca wymiana: `null` = sesja tymczasowa, napis = sesja nadana
  // przez backend (raportowana przy pierwszej ramce), `undefined` = brak wymiany w tej instancji.
  // Dzięki temu przejście „tymczasowa → nadana" (DEC-078) nie uchodzi za zmianę rozmowy.
  const liveSessionRef = useRef<string | null | undefined>(undefined)

  const handleSessionId = useCallback(
    (sessionId: string) => {
      liveSessionRef.current = sessionId
      // Adres dostaje sesję tylko po rozmowie tymczasowej — wybrana rozmowa już w nim jest.
      if (activeSessionId === null) onConversationChange(sessionId)
    },
    [activeSessionId, onConversationChange],
  )

  const stream = useChatStream(chatId, { onSessionId: handleSessionId })
  const { phase, question, reset, send, stop } = stream

  // Zmiana rozmowy porzuca bieżącą wymianę (także trwający stream).
  useEffect(() => {
    const liveSession = liveSessionRef.current
    if (liveSession === undefined || liveSession === activeSessionId) return
    liveSessionRef.current = undefined
    reset()
  }, [activeSessionId, reset])

  const history = session.data === undefined ? [] : historyToMessages(session.data)
  // Po odświeżeniu historii (invalidate po `done`) ta sama wiadomość asystenta jest już w historii —
  // para live znika, żeby nie dublować treści. Prologue nie ma `id`, więc porównujemy tylko niepuste.
  // API sesji eksponuje JEDNO `id` dla pary user+assistant (to id asystenta — K4 §3.3,
  // `services/sessions.py`), więc szukamy po roli `assistant`, a nie po samym `id`.
  // Wyjątek (K4 §3.4): backend nie utrwala tekstu empty_response — historia wraca PUSTA, a para live
  // niesie jedyny tekst dymka; wtedy NIE deduplikujemy, żeby odpowiedź nie zniknęła.
  const liveAnswered = stream.state.messageId
  const liveAnsweredText = stream.state.answer.trim()
  const liveInHistory =
    liveAnswered !== null &&
    history.some(
      (message) =>
        message.role === 'assistant' &&
        message.id === liveAnswered &&
        !(message.content.trim() === '' && liveAnsweredText !== ''),
    )
  const live =
    question === null || liveInHistory
      ? []
      : liveToMessages(question, stream.state, liveStatus(phase))
  const messages = [...history, ...live]

  const feedback = useMessageFeedback(chatId, activeSessionId ?? '')

  const handleSend = useCallback(
    (text: string) => {
      liveSessionRef.current = activeSessionId
      void send(text, activeSessionId)
    },
    [activeSessionId, send],
  )

  /** Wybór rozmowy (także „+"); na wąskim ekranie zwija panel, żeby rozmowa była widoczna (§T6b). */
  function handleSelectSession(sessionId: string | null): void {
    onConversationChange(sessionId)
    if (belowMd) setManual({ belowMd, collapsed: true })
  }

  /** Ręczne zwinięcie/rozwinięcie panelu rozmów — obowiązuje do zmiany progu `md`. */
  function handleToggleCollapsed(): void {
    setManual({ belowMd, collapsed: !collapsed })
  }

  /** Powtórzenie ostatniego pytania w tej samej rozmowie (DEC-079: dopisuje nową parę). */
  function handleRegenerate(): void {
    const lastQuestion = messages.filter((message) => message.role === 'user').at(-1)
    if (lastQuestion === undefined) return
    liveSessionRef.current = activeSessionId
    void send(lastQuestion.content, activeSessionId)
  }

  function handleFeedback(message: ChatMessage, thumbup: boolean, text: string | null): void {
    // Opinia dotyczy wiadomości zapisanej na backendzie — prologue i wiadomości live nie mają `id`.
    if (message.id === null || activeSessionId === null) return
    feedback.mutate({ messageId: message.id, thumbup, feedback: text })
  }

  // Brak czatu w bazie wraca kopertą `code 102` (RetCode.DATA_ERROR), a cudzy czat odmową 109 —
  // własny komunikat ma tylko ten pierwszy, każdy inny błąd dostaje tekst ogólny.
  const notFound = chat.error instanceof ApiError && chat.error.code === 102
  const errorMessage = notFound ? t('chat.notFound') : t('chat.loadError')

  return (
    <Box ref={rootRef} sx={{ flex: 1, display: 'flex', minHeight: 0, height }}>
      {/* Poniżej `md` miejsce rozwiniętego panelu zajmuje szuflada (niżej) — inline zostaje
          pasek zwinięty albo pełna kolumna powyżej `md`. */}
      {panelInDrawer ? null : (
        <SessionsPanel
          chatId={chatId}
          chatName={chat.data?.name}
          activeSessionId={activeSessionId}
          onSelect={handleSelectSession}
          collapsed={collapsed}
          onToggleCollapsed={handleToggleCollapsed}
        />
      )}

      <Box
        data-testid="chat-column"
        sx={{ flexGrow: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}
      >
        <Stack
          direction="row"
          spacing={1}
          sx={{
            alignItems: 'center',
            p: 2,
            borderBottom: '1px solid',
            borderColor: 'divider',
          }}
        >
          <Typography
            variant="h6"
            noWrap
            title={session.data?.name ?? t('chat.workspace.newSession')}
            sx={{ flexGrow: 1, minWidth: 0 }}
          >
            {session.data?.name ?? t('chat.workspace.newSession')}
          </Typography>
          <IconButton aria-label={t('chat.settings.open')} onClick={() => setSettings('default')}>
            <SettingsOutlinedIcon />
          </IconButton>
        </Stack>

        {chat.isError ? (
          <Alert severity="error" sx={{ m: 2 }}>
            {errorMessage}
          </Alert>
        ) : null}

        <Box sx={{ flexGrow: 1, minHeight: 0 }}>
          <Suspense
            fallback={
              <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
                <CircularProgress aria-label={t('chat.workspace.loading')} />
              </Box>
            }
          >
            <MessageList
              messages={messages}
              streaming={phase === 'streaming'}
              onOpenDocument={(docId, docName) => setPreview({ docId, docName })}
              onFeedback={handleFeedback}
              onRegenerate={handleRegenerate}
            />
          </Suspense>
        </Box>

        <ChatInput
          streaming={phase === 'streaming'}
          onSend={handleSend}
          onStop={stop}
          filterLabels={filterLabels(chat.data?.meta_data_filter)}
          onEditFilter={() => setSettings('filter')}
        />
      </Box>

      {/* Rozwinięty panel rozmów poniżej `md`: tymczasowa szuflada (wzór: ustawienia czatu),
          nakrywająca obszar czatu zamiast ściskania kolumny (QA E5-H8z-4). Poniżej `sm` zajmuje
          całą szerokość (R-UI-01, jak szuflada ustawień) — czat jest wtedy zakryty w całości.
          Wybór rozmowy (i „+”), „Zwiń panel rozmów”, Esc i klik w zasłonę zwijają panel
          (`onClose`). */}
      <Drawer
        anchor="left"
        open={panelInDrawer}
        onClose={handleToggleCollapsed}
        slotProps={{
          paper: { sx: { width: { xs: 'min(100%, 100vw)', sm: SESSIONS_PANEL_WIDTH } } },
        }}
      >
        {/* Szuflada jest kolumną flex o pełnej wysokości — wiersz rozciąga panel na jej wysokość. */}
        <Box sx={{ flex: 1, minHeight: 0, display: 'flex' }}>
          <SessionsPanel
            chatId={chatId}
            chatName={chat.data?.name}
            activeSessionId={activeSessionId}
            onSelect={handleSelectSession}
            collapsed={false}
            onToggleCollapsed={handleToggleCollapsed}
          />
        </Box>
      </Drawer>

      <ChatSettingsDrawer
        chatId={chatId}
        open={settings !== null}
        focusFilter={settings === 'filter'}
        onClose={() => setSettings(null)}
      />

      <DocumentPreviewDrawer
        documentId={preview?.docId ?? null}
        documentName={preview?.docName}
        onClose={() => setPreview(null)}
      />
    </Box>
  )
}
