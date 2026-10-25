import { useEffect } from 'react'
import { useNavigate } from '@tanstack/react-router'
import type { NavigateOptions } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import useNotifications from '../../hooks/useNotifications/useNotifications'

import { oidcErrorKey } from './oidcErrors'

/**
 * Powiadomienie o błędzie OIDC przekazanym w `?error=<slug>` (08 §5.2). Pokazuje komunikat raz
 * i od razu usuwa parametr z adresu (`replace`), żeby odświeżenie strony go nie powtarzało.
 */
export function useOidcErrorNotice(error?: string): void {
  const { t } = useTranslation()
  const { show } = useNotifications()
  const navigate = useNavigate()

  useEffect(() => {
    if (error === undefined) return

    const key = oidcErrorKey(error)
    show(t(key), { key, severity: 'error' })
    // Haczyk dzielą `/` i `/login`, więc cel (`to`) nie jest tu znany typowo — zostaje bieżący
    // adres, a parametry wyszukiwania są czyszczone (jak `navigate({ search: {} })`).
    void navigate({ search: {}, replace: true } as NavigateOptions)
  }, [error, navigate, show, t])
}
