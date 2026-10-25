/**
 * Strona dostawców modeli (kontrakt WP E3-6c1 §5): karta modeli domyślnych nad dwiema kolumnami —
 * lista instancji po lewej, modele wybranej instancji po prawej. Wybór trzymamy jako id;
 * domyślnie zaznaczona jest pierwsza instancja (`default`), a gdy wybrana zniknie z listy,
 * wybór wraca do pierwszej.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import Grid from '@mui/material/Grid'
import Stack from '@mui/material/Stack'
import { useQuery } from '@tanstack/react-query'

import { instancesQueryOptions } from '../providerQueries'

import { DefaultModelsCard } from './DefaultModelsCard'
import { InstanceModelsPanel } from './InstanceModelsPanel'
import { InstancesPanel } from './InstancesPanel'

export function ModelsPage(): JSX.Element {
  const { data: instances } = useQuery(instancesQueryOptions())
  const [pickedId, setPickedId] = useState<string | null>(null)

  // `find` po nieistniejącym id zwraca `undefined`, więc wybór sam wraca do pierwszej instancji.
  const selected = instances?.find((instance) => instance.id === pickedId) ?? instances?.[0] ?? null

  return (
    <Stack spacing={2}>
      <DefaultModelsCard />
      <Grid container spacing={2}>
        {/* T7 (D4): 4/8 zamiast 5/7 — panel siatki modeli na 1280 px potrzebuje ~640 px
            (zawężone kolumny), inaczej DataGrid pokazuje poziomy przewijak i chowa ✎ 🗑. */}
        <Grid size={{ xs: 12, md: 4 }}>
          <InstancesPanel selectedId={selected?.id ?? null} onSelect={setPickedId} />
        </Grid>
        <Grid size={{ xs: 12, md: 8 }}>
          <InstanceModelsPanel instance={selected} />
        </Grid>
      </Grid>
    </Stack>
  )
}
