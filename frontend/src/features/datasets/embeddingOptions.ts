/**
 * Opcje modelu embeddingu dla dialogu „Utwórz dataset” (08 §7.3, kontrakt WP E3-3a §T2).
 * Z rejestru modeli (`GET /api/v1/models`) zostają tylko modele embeddingu; id opcji to
 * `model_id`, bo takiego formatu wymaga `embedding_model` w `POST /datasets`
 * (`<model_name>@<provider_name>` albo 32-znakowe hex id — kontrakt §Fakty API).
 * `defaultId` wskazuje model domyślny instancji (`/users/me/models.embd_id`, czyli NAZWA),
 * a gdy lista pusta — pusty string, co blokuje zapis w dialogu.
 */

import type { Model } from '../chats/modelsQuery'

export type EmbeddingOption = { id: string; label: string }

export function buildEmbeddingOptions(
  models: Model[],
  defaultName: string,
): { options: EmbeddingOption[]; defaultId: string } {
  const options = models
    .filter((model) => model.model_type.includes('embedding'))
    .map((model) => ({ id: model.model_id, label: model.name }))

  // Brak dopasowania po nazwie (np. domyślny model usunięty z rejestru) → pierwsza opcja.
  const matched = options.find((option) => option.label === defaultName)
  const defaultId = matched?.id ?? options[0]?.id ?? ''

  return { options, defaultId }
}
