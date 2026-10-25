/**
 * Hooki TanStack Query eksportu/importu bazy wiedzy (kontrakt WP E7-2 §4).
 * Klucze w przestrzeni `['kb-transfer', …]`. Mutacje nie unieważniają cache'u: trwałe zadania
 * żyją w pasku zadań (`taskStore.ts`, T2) i są odpytywane przez `useTaskPolling`, a podgląd
 * eksportu to jednorazowe pytanie przy otwarciu dialogu (T3).
 */

import { queryOptions, useMutation, useQuery } from '@tanstack/react-query'

import {
  createImport,
  deleteImport,
  previewExport,
  startExport,
  startImport,
  stopTask,
} from './api'

export const kbTransferKeys = {
  all: ['kb-transfer'] as const,
  exportPreview: (datasetId: string) => ['kb-transfer', 'export-preview', datasetId] as const,
  importSession: (importId: string) => ['kb-transfer', 'import', importId] as const,
}

/** Trasa 1 — podgląd zawartości paczki dla dialogu eksportu (`enabled: false` go nie woła). */
export function exportPreviewQueryOptions(datasetId: string, enabled: boolean) {
  return queryOptions({
    queryKey: kbTransferKeys.exportPreview(datasetId),
    enabled,
    queryFn: () => previewExport(datasetId),
  })
}

export function useExportPreview(datasetId: string, enabled: boolean) {
  return useQuery(exportPreviewQueryOptions(datasetId, enabled))
}

/** Trasa 2 — start eksportu; 409 `export_in_progress` wraca jako `WdApiError` z `details.task_id`. */
export function useStartExport() {
  return useMutation({
    mutationFn: (vars: { datasetId: string; includeVectors: boolean }) =>
      startExport(vars.datasetId, vars.includeVectors),
  })
}

/** Trasa 4 — zatrzymanie zadania (eksportu albo importu). */
export function useStopTask() {
  return useMutation({
    mutationFn: (taskId: string) => stopTask(taskId),
  })
}

/** Trasa 6 — założenie sesji importu (przed pierwszą porcją). */
export function useCreateImport() {
  return useMutation({
    mutationFn: (vars: { fileName: string; sizeBytes: number }) =>
      createImport(vars.fileName, vars.sizeBytes),
  })
}

/** Trasa 9 — start importu po walidacji paczki; 409 `name_conflict` niesie `details.suggested_name`. */
export function useStartImport() {
  return useMutation({
    mutationFn: (vars: { importId: string; name: string; embeddingModel: string | null }) =>
      startImport(vars.importId, vars.name, vars.embeddingModel),
  })
}

/** Trasa 10 — porzucenie sesji importu („Anuluj” w oknie wysyłki). */
export function useDeleteImport() {
  return useMutation({
    mutationFn: (importId: string) => deleteImport(importId),
  })
}
