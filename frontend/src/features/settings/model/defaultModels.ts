/**
 * Czysta logika karty „Modele domyślne” (brief E3-6c1 T5a): mapowanie bieżących modeli na
 * wartości formularza i budowa ciała PATCH. Wartością jest NAZWA modelu, pusta = brak
 * (kontrakt WP E3-6c1 §0).
 */

import type { components } from '../../../api/schema.gen'
import type { DefaultModels } from '../../models/queries'

export type DefaultsForm = {
  llm: string
  embd: string
  rerank: string
  vlm: string
}

/** Bieżące modele domyślne → wartości formularza (klucze API: llm_id, embd_id, rerank_id, img2txt_id). */
export function toDefaultsForm(models: DefaultModels): DefaultsForm {
  return {
    llm: models.llm_id,
    embd: models.embd_id,
    rerank: models.rerank_id,
    vlm: models.img2txt_id,
  }
}

/** Ciało `PATCH /api/v1/users/me/models`: tylko pola zmienione i niepuste (kontrakt §0). */
export function buildDefaultsPatch(
  initial: DefaultsForm,
  form: DefaultsForm,
): Partial<components['schemas']['UpdateDefaultModelsRequest']> {
  const patch: Partial<components['schemas']['UpdateDefaultModelsRequest']> = {}
  if (form.llm !== initial.llm && form.llm !== '') patch.llm_id = form.llm
  if (form.embd !== initial.embd && form.embd !== '') patch.embd_id = form.embd
  if (form.rerank !== initial.rerank && form.rerank !== '') patch.rerank_id = form.rerank
  if (form.vlm !== initial.vlm && form.vlm !== '') patch.img2txt_id = form.vlm
  return patch
}
