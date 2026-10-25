// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/crud-dashboard/hooks/useDialogs/DialogsContext.ts (MIT). Zmiany: importy typów przez `import type`, formatowanie Prettier.
import * as React from 'react'
import type { CloseDialog, OpenDialog } from './useDialogs'

const DialogsContext = React.createContext<{
  open: OpenDialog
  close: CloseDialog
} | null>(null)

export default DialogsContext
