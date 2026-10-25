/**
 * Domyślny prompt systemowy czatu — tekst własny Wawelskiego Smoka (E5-7 / DEC-331), utrzymywany
 * w zgodzie bajt w bajt z `DEFAULT_PROMPT_CONFIG["system"]` w `backend/app/domain/chat/config.py`.
 * Wybór pierwszej bazy wiedzy przy pustym prompcie wypełnia tym szablonem pole „Prompt systemowy”
 * (C2 WP E5-H6e), bo walidacja wymaga w nim `{knowledge}`. Zgodność z backendem pilnuje
 * `defaultPrompt.test.ts`.
 */
export const DEFAULT_SYSTEM_PROMPT = `You are an assistant grounded in the dataset below; answer from it and keep the running conversation in mind.
Rules:
  - Walk through the dataset entries matching the question and lay them out one by one.
  - Back a full answer with the data you found (e.g. answer a Polish question about the Wawel dragon with the legend facts from the dataset).
  - Reply in the same language as the question.
  - If the dataset does not cover the question, say so openly and finish with this exact sentence: "The answer you are looking for is not found in the dataset!"
Knowledge base:
      {knowledge}
End of knowledge base.`
