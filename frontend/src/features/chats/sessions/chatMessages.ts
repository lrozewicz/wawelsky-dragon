/**
 * Mapowanie wiadomości czatu na model UI (kontrakt WP E3-5b §T1): historia sesji z backendu
 * (`historyToMessages`) oraz bieżąca para pytanie/odpowiedź ze streamu (`liveToMessages`).
 * Czyste funkcje — cytowania normalizuje reduktor E3-5a (`normalizeChunks`).
 */

import { normalizeChunks, type Citation, type StreamState } from '../../chat-stream/reducer'
import { splitThink } from '../../chat-stream/splitThink'

import type { StreamPhase } from '../stream/useChatStream'
import type { Session } from './sessionQueries'

export type DocAgg = { docId: string; docName: string; count: number }

export type ChatMessage = {
  key: string // stabilny klucz Reacta ('greeting' | id | `${role}-${id}` | `msg-n` | `live-…`)
  id: string | null
  role: 'user' | 'assistant'
  content: string // treść BEZ <think> (po splitThink) dla assistant; surowa dla user
  thinking: string // '' gdy brak
  citations: Citation[] // z reduktora
  docAggs: DocAgg[]
  thumbup: boolean | null
  status: 'done' | 'streaming' | 'aborted' | 'error'
  error: string | null
}

function toDocAggs(raw: Session['reference'][number]['doc_aggs']): DocAgg[] {
  if (!Array.isArray(raw)) return []
  return raw.map((agg) => ({ docId: agg.doc_id, docName: agg.doc_name, count: agg.count }))
}

/**
 * Identyfikatory powtórzone w historii. API sesji eksponuje JEDNO `id` dla pary user+assistant
 * (K4 §3.3), więc sam `id` nie jest unikalnym kluczem Reacta — dla powtórzonych dokładamy rolę.
 */
function duplicatedIds(session: Session): Set<string> {
  const seen = new Set<string>()
  const duplicated = new Set<string>()
  for (const message of session.messages) {
    const id = message.id
    if (id === undefined || id === null) continue
    if (seen.has(id)) duplicated.add(id)
    seen.add(id)
  }
  return duplicated
}

/**
 * Historia sesji → wiadomości UI. Prologue (pierwsza assistant bez `id`) dostaje klucz 'greeting'
 * i puste cytowania; k-ta pozostała assistant bierze cytowania i agregaty z `reference[k]`
 * (brak wpisu → puste).
 */
export function historyToMessages(session: Session): ChatMessage[] {
  const messages: ChatMessage[] = []
  const duplicated = duplicatedIds(session)
  let prologueSeen = false
  let assistantIndex = 0

  for (const message of session.messages) {
    const id = message.id ?? null
    const isAssistant = message.role === 'assistant'
    const isPrologue = isAssistant && id === null && !prologueSeen
    if (isPrologue) prologueSeen = true

    const reference = isAssistant && !isPrologue ? session.reference[assistantIndex] : undefined
    if (isAssistant && !isPrologue) assistantIndex += 1

    const { thinking, answer } = isAssistant
      ? splitThink(message.content)
      : { thinking: '', answer: message.content }

    const role = isAssistant ? 'assistant' : 'user'
    // Para user/assistant dzieli `id`, więc dla powtórzonych ról klucz dostaje prefiks roli.
    let key = id ?? `msg-${messages.length}`
    if (isPrologue) key = 'greeting'
    else if (id !== null && duplicated.has(id)) key = `${role}-${id}`

    messages.push({
      key,
      id,
      role,
      content: answer,
      thinking,
      citations: reference === undefined ? [] : normalizeChunks(reference.chunks),
      docAggs: reference === undefined ? [] : toDocAggs(reference.doc_aggs),
      thumbup: message.thumbup ?? null,
      status: 'done',
      error: null,
    })
  }

  return messages
}

/** Bieżąca wymiana podczas streamu: para user/assistant zasilana stanem reduktora. */
export function liveToMessages(
  question: string,
  state: StreamState,
  status: 'streaming' | 'done' | 'aborted' | 'error',
): ChatMessage[] {
  // Klucze pary live są równe kluczom, jakie ta para dostanie w historii (`historyToMessages`):
  // user i assistant sesji dzielą jedno `id` (K4 §3.3), a powtórzone id dostaje prefiks roli.
  // Własne klucze `live-*` skończyłyby się remontem komponentów wiadomości przy refetchu sesji po
  // `done` (useChatStream) — otwarty modal cytowania zamykałby się zaraz po kliknięciu tuż po
  // końcu odpowiedzi (SC-V13-z-01). Zanim pierwsza ramka przyniesie `id`, klucze zostają `live-*`:
  // remont na samym starcie streamu niczego nie psuje (nic nie jest wtedy otwarte).
  const pairId = state.messageId
  return [
    {
      key: pairId === null ? 'live-user' : `user-${pairId}`,
      id: null,
      role: 'user',
      content: question,
      thinking: '',
      citations: [],
      docAggs: [],
      thumbup: null,
      status: 'done',
      error: null,
    },
    {
      key: pairId === null ? 'live-assistant' : `assistant-${pairId}`,
      id: state.messageId,
      role: 'assistant',
      content: state.answer,
      thinking: state.thinking,
      citations: state.citations,
      docAggs: state.docAggs,
      thumbup: null,
      status,
      error: status === 'error' ? state.error : null,
    },
  ]
}

/**
 * Status wiadomości live. Live renderuje się wyłącznie z niepustym `question`, więc faza `idle`
 * nie występuje — zostaje mapowaniem domykającym typ.
 */
export function liveStatus(phase: StreamPhase): 'streaming' | 'done' | 'aborted' | 'error' {
  return phase === 'idle' ? 'streaming' : phase
}
