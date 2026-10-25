/**
 * Widoczność pozycji ⋮ „Eksportuj” (kontrakt WP E7-2 §8): właściciel bazy albo superuser.
 * Członek zespołu (permission `team`) nie widzi pozycji — K19 §Uprawnienia zwraca 403 `forbidden`.
 * `tenant_id` jest w liście datasetów (`DatasetListed`), `id` i `is_superuser` w profilu sesji.
 */

import type { AuthUser } from '../auth/authState'
import type { DatasetListed } from '../datasets/queries'

/** Fragment listy datasetów potrzebny do decyzji (`DatasetListed` niesie `tenant_id`). */
export type ExportableDataset = Pick<DatasetListed, 'tenant_id'>

/** Fragment profilu bieżącego użytkownika potrzebny do decyzji. */
export type CurrentUser = Pick<AuthUser, 'id' | 'is_superuser'>

/** `true`, gdy bieżący użytkownik może otworzyć dialog eksportu tej bazy wiedzy. */
export function canExport(dataset: ExportableDataset, me: CurrentUser): boolean {
  return dataset.tenant_id === me.id || me.is_superuser
}
