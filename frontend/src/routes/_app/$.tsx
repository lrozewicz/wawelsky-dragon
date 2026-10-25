import { createFileRoute } from '@tanstack/react-router'

import { NotFoundPage } from '../../app/NotFoundPage'

// Nieznana ścieżka: guard `_app` odsyła niezalogowanych na logowanie, zalogowani widzą 404 w layoucie.
export const Route = createFileRoute('/_app/$')({ component: NotFoundPage })
