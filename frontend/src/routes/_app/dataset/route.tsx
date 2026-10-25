import type { JSX } from 'react'
import { Outlet, createFileRoute } from '@tanstack/react-router'

import { DatasetLoadError } from '../../../features/datasets/detail/DatasetLayout'

/**
 * Layout tras szczegółów datasetu (08 §7.4): renderuje sam `Outlet` — nagłówek i zakładki składnia
 * `DatasetLayout` w każdej z tras-zakładek. `errorComponent` łapie błąd loadera szczegółu
 * (nieistniejący albo niedostępny dataset) i pokazuje `Alert` z powrotem do listy baz wiedzy.
 */
export const Route = createFileRoute('/_app/dataset')({
  component: DatasetRoutesLayout,
  errorComponent: DatasetLoadError,
})

function DatasetRoutesLayout(): JSX.Element {
  return <Outlet />
}
