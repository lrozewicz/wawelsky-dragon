// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/crud-dashboard/hooks/useDialogs/DialogsProvider.tsx (MIT). Zmiany: import typu przez `import type`, punktowe `eslint-disable-next-line @typescript-eslint/no-explicit-any` (typ stosu jest heterogeniczny — DEC-038), czyszczenie timerów usuwających stos przy odmontowaniu providera (flake vitest „window is not defined” po teardownie jsdom — E3-H4 p. 5a), formatowanie Prettier.
import * as React from 'react'
import useEventCallback from '@mui/utils/useEventCallback'
import DialogsContext from './DialogsContext'
import type { DialogComponent, OpenDialog, OpenDialogOptions } from './useDialogs'

interface DialogStackEntry<P, R> {
  key: string
  open: boolean
  promise: Promise<R>
  Component: DialogComponent<P, R>
  payload: P
  onClose: (result: R) => Promise<void>
  resolve: (result: R) => void
}

export interface DialogProviderProps {
  children?: React.ReactNode
  unmountAfter?: number
}

/**
 * Provider for Dialog stacks. The subtree of this component can use the `useDialogs` hook to
 * access the dialogs API. The dialogs are rendered in the order they are requested.
 */
export default function DialogsProvider(props: DialogProviderProps) {
  const { children, unmountAfter = 1000 } = props
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- stos dialogów jest heterogeniczny (P/R różne dla każdego wpisu), jak w upstream (DEC-038)
  const [stack, setStack] = React.useState<DialogStackEntry<any, any>[]>([])
  const keyPrefix = React.useId()
  const nextId = React.useRef(0)
  // Aktywne timery usuwające wpisy ze stosu — czyszczone przy odmontowaniu providera.
  const [unmountTimers] = React.useState(() => new Set<ReturnType<typeof setTimeout>>())
  const dialogMetadata = React.useRef(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- kluczowane promise'ami o dowolnym typie wyniku, jak w upstream (DEC-038)
    new WeakMap<Promise<any>, DialogStackEntry<any, any>>(),
  )

  const requestDialog = useEventCallback<OpenDialog>(function open<P, R>(
    Component: DialogComponent<P, R>,
    payload: P,
    options: OpenDialogOptions<R> = {},
  ) {
    const { onClose = async () => {} } = options
    let resolve: ((result: R) => void) | undefined
    const promise = new Promise<R>((resolveImpl) => {
      resolve = resolveImpl
    })

    if (!resolve) {
      throw new Error('resolve not set.')
    }

    const key = `${keyPrefix}-${nextId.current}`
    nextId.current += 1

    const newEntry: DialogStackEntry<P, R> = {
      key,
      open: true,
      promise,
      Component,
      payload,
      onClose,
      resolve,
    }

    // Store metadata for reliable access during close
    dialogMetadata.current.set(promise, newEntry)

    setStack((prevStack) => [...prevStack, newEntry])
    return promise
  })

  const closeDialogUi = useEventCallback(function closeDialogUi<R>(dialog: Promise<R>) {
    setStack((prevStack) =>
      prevStack.map((entry) => (entry.promise === dialog ? { ...entry, open: false } : entry)),
    )
    const timer = setTimeout(() => {
      unmountTimers.delete(timer)
      // wait for closing animation
      setStack((prevStack) => prevStack.filter((entry) => entry.promise !== dialog))
      // WeakMap automatically cleans up when promise is garbage collected
    }, unmountAfter)
    unmountTimers.add(timer)
  })

  // Sprzątanie: callbacki timerów nie mogą trafić w środowisko po odmontowaniu providera
  // (w testach po teardownie jsdom rzucały „window is not defined” — E3-H4 p. 5a).
  React.useEffect(
    () => () => {
      for (const timer of unmountTimers) clearTimeout(timer)
      unmountTimers.clear()
    },
    [unmountTimers],
  )

  const closeDialog = useEventCallback(async function closeDialog<R>(
    dialog: Promise<R>,
    result: R,
  ) {
    const entryToClose = dialogMetadata.current.get(dialog)
    if (!entryToClose) {
      throw new Error('Dialog not found.')
    }

    try {
      await entryToClose.onClose(result)
    } finally {
      entryToClose.resolve(result)
      closeDialogUi(dialog)
    }
    return dialog
  })

  const contextValue = React.useMemo(
    () => ({ open: requestDialog, close: closeDialog }),
    [requestDialog, closeDialog],
  )

  return (
    <DialogsContext.Provider value={contextValue}>
      {children}
      {stack.map(({ key, open, Component, payload, promise }) => (
        <Component
          key={key}
          payload={payload}
          open={open}
          onClose={async (result) => {
            await closeDialog(promise, result)
          }}
        />
      ))}
    </DialogsContext.Provider>
  )
}
