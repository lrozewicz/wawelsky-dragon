/**
 * Hook strumienia czatu (kontrakt WP E3-5b §T2): wysyła pytanie przez klienta API
 * (`POST /chats/{chat_id}/completions`, `parseAs: 'stream'` — DEC-081), składa ramki
 * reduktorem z E3-5a i wystawia fazę, stan oraz Stop (AbortController).
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { api } from '../../../api/client'
import type { components } from '../../../api/schema.gen'
import { readSse } from '../../../lib/sse'
import { initialStreamState, reduce } from '../../chat-stream/reducer'
import type { StreamState } from '../../chat-stream/reducer'
import { sessionKeys } from '../sessions/sessionQueries'

export type StreamPhase = 'idle' | 'streaming' | 'done' | 'error' | 'aborted'

export type UseChatStreamOptions = { onSessionId?: (sessionId: string) => void }

export type UseChatStream = {
  phase: StreamPhase
  state: StreamState
  question: string | null
  send: (question: string, sessionId: string | null) => Promise<void>
  stop: () => void
  reset: () => void
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'error'
}

export function useChatStream(chatId: string, options?: UseChatStreamOptions): UseChatStream {
  const queryClient = useQueryClient()
  const [phase, setPhase] = useState<StreamPhase>('idle')
  const [state, setState] = useState<StreamState>(initialStreamState)
  const [question, setQuestion] = useState<string | null>(null)

  const controllerRef = useRef<AbortController | null>(null)
  const { onSessionId } = options ?? {}

  const send = useCallback(
    async (nextQuestion: string, sessionId: string | null): Promise<void> => {
      // Wysłanie w trakcie streamu jest ignorowane (kontrakt §T2).
      if (controllerRef.current !== null) return

      const controller = new AbortController()
      controllerRef.current = controller
      setQuestion(nextQuestion)
      setPhase('streaming')
      setState(initialStreamState)

      let current = initialStreamState
      let sessionIdReported = false

      try {
        const { response } = await api.POST('/api/v1/chats/{chat_id}/completions', {
          params: { path: { chat_id: chatId } },
          // Backend czyta tylko te trzy klucze, a wygenerowany typ wymaga wszystkich
          // (jak `useCreateChat`).
          body: {
            question: nextQuestion,
            stream: true,
            session_id: sessionId,
          } as unknown as components['schemas']['CompletionRequest'],
          parseAs: 'stream',
          signal: controller.signal,
        })

        if (!response.ok) {
          current = { ...current, status: 'error', error: `HTTP ${response.status}` }
          setState(current)
          setPhase('error')
          return
        }

        for await (const frame of readSse(response, controller.signal)) {
          current = reduce(current, frame)
          setState(current)
          if (!sessionIdReported && current.sessionId !== null) {
            sessionIdReported = true
            onSessionId?.(current.sessionId)
          }
        }

        // `stop()` i `reset()` ustawiły już fazę — nie nadpisujemy jej po wyjściu z pętli.
        if (controller.signal.aborted) return
        if (current.status === 'error') {
          setPhase('error')
          return
        }

        setPhase('done')
        void queryClient.invalidateQueries({ queryKey: sessionKeys.all(chatId) })
      } catch (error) {
        if (controller.signal.aborted) return
        setState({ ...current, status: 'error', error: errorText(error) })
        setPhase('error')
      } finally {
        if (controllerRef.current === controller) controllerRef.current = null
      }
    },
    [chatId, onSessionId, queryClient],
  )

  const stop = useCallback(() => {
    const controller = controllerRef.current
    if (controller === null) return
    controller.abort()
    setPhase('aborted')
  }, [])

  const reset = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null
    setPhase('idle')
    setState(initialStreamState)
    setQuestion(null)
  }, [])

  // Odmontowanie hooka przerywa trwający stream.
  useEffect(
    () => () => {
      controllerRef.current?.abort()
    },
    [],
  )

  return { phase, state, question, send, stop, reset }
}
