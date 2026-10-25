/**
 * Schemat formularza chunku (kontrakt WP E3-4a §ChunkDialog): treść wymagana po `trim`
 * (komunikat z klucza `chunks.dialog.contentRequired`), słowa kluczowe i pytania jako listy
 * tekstów, przełącznik dostępności. Wartość po walidacji jest przycięta — `ChunkDialog`
 * wysyła `data.content`, więc `onSubmit` dostaje treść po `trim`.
 */

import { z } from 'zod'

/** Wartości formularza chunku (kontrakt WP E3-4a §ChunkDialog). */
export type ChunkFormValues = {
  content: string
  important_keywords: string[]
  questions: string[]
  available: boolean
}

export const chunkFormSchema: z.ZodType<ChunkFormValues> = z.object({
  content: z.string().trim().min(1, 'chunks.dialog.contentRequired'),
  important_keywords: z.array(z.string()),
  questions: z.array(z.string()),
  available: z.boolean(),
})
