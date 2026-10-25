/**
 * Strona 404 zalogowanej aplikacji (SC-E67-07 krok 5): renderowana w layoucie `_app`
 * (trasa-wildcard `_app/$`), z linkiem powrotnym do baz wiedzy.
 */

import type { JSX } from 'react'
import Button from '@mui/material/Button'
import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '../components/EmptyState'
import PageContainer from '../components/PageContainer'

export function NotFoundPage(): JSX.Element {
  const { t } = useTranslation()

  // PageContainer: te same marginesy co inne strony (karta nie przylega do krawędzi obszaru treści).
  return (
    <PageContainer>
      <EmptyState
        title={t('app.notFound.title')}
        description={t('app.notFound.description')}
        action={
          <Button component={Link} to="/datasets" variant="contained">
            {t('app.notFound.back')}
          </Button>
        }
      />
    </PageContainer>
  )
}
