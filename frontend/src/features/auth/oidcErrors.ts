/**
 * Slugi błędów OIDC (07 §3.3, `OidcError.slug`) i ich mapowanie na klucze i18n (08 §5.2).
 * Backend przy nieudanym logowaniu przez dostawcę tożsamości przekierowuje na `/?error=<slug>`;
 * każdy znany slug ma własny komunikat, reszta dostaje komunikat ogólny.
 */

export const OIDC_ERROR_SLUGS = [
  'email_missing',
  'email_not_verified',
  'invalid_state',
  'invalid_token',
  'missing_code',
  'oidc_error',
  'registration_disabled',
  'token_failed',
  'user_inactive',
] as const

/** Klucz i18n komunikatu dla sluga; slug spoza listy → `auth.oidcError.unknown`. */
export function oidcErrorKey(slug: string): string {
  return (OIDC_ERROR_SLUGS as readonly string[]).includes(slug)
    ? `auth.oidcError.${slug}`
    : 'auth.oidcError.unknown'
}
