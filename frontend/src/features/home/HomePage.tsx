/**
 * Strona Home `/` (08 §7.2): baner powitalny, sekcja ostatnich baz wiedzy i sekcja aplikacji
 * z przełącznikiem Chat | Search | Agent (Agent tylko przy włączonej fladze `FEATURE_AGENT`).
 */

import { useState } from 'react'
import type { ReactNode } from 'react'
import Stack from '@mui/material/Stack'
import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import Typography from '@mui/material/Typography'
import { useRouteContext } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import { getFeatureFlags } from '../../app/env'
import PageContainer from '../../components/PageContainer'

import { RecentSection } from './RecentSection'
import { ResourceMiniCard } from './ResourceMiniCard'
import { useRecentChats, useRecentDatasets } from './queries'

type AppsTab = 'chat' | 'search' | 'agent'

export function HomePage() {
  const { t } = useTranslation()
  // Kontekst trasy jest częściowy (`strict: false`) — bierzemy z niego wyłącznie profil sesji.
  const user = useRouteContext({ strict: false, select: (context) => context.auth?.user ?? null })
  const flags = getFeatureFlags()
  const [tab, setTab] = useState<AppsTab>('chat')

  const datasets = useRecentDatasets()
  const chats = useRecentChats()

  // Konta bez nickname wita e-mail (08 §7.2 — baner zawsze wita konkretną osobę).
  const nickname = user !== null && user.nickname !== '' ? user.nickname : (user?.email ?? '')

  const isChatTab = tab === 'chat'
  let appsEmpty: ReactNode
  if (tab === 'chat') {
    appsEmpty = <ResourceMiniCard title={t('home.chat.empty')} href="/chats?isCreate=true" />
  } else if (tab === 'search') {
    // TODO E4-4: GET /searches — endpointu nie ma jeszcze w openapi.json, więc bez żądania.
    appsEmpty = <Typography color="text.secondary">{t('home.search.empty')}</Typography>
  } else {
    appsEmpty = <Typography color="text.secondary">{t('home.agent.empty')}</Typography>
  }

  return (
    <PageContainer title={t('nav.home')}>
      <Stack spacing={4}>
        <Typography component="h1" variant="h4" data-testid="home-banner">
          {t('home.banner', { nickname })}
        </Typography>

        <RecentSection
          testId="home-section-datasets"
          title={t('home.datasets.title')}
          items={datasets.data}
          isPending={datasets.isPending}
          isError={datasets.isError}
          onRetry={() => void datasets.refetch()}
          empty={
            <ResourceMiniCard title={t('home.datasets.empty')} href="/datasets?isCreate=true" />
          }
          seeAll={<ResourceMiniCard title={t('home.seeAll')} href="/datasets" />}
          renderItem={(dataset) => (
            <ResourceMiniCard
              title={dataset.name}
              description={dataset.description}
              filesCount={dataset.document_count}
              href={'/dataset/files/' + dataset.id}
            />
          )}
        />

        <RecentSection
          testId="home-section-apps"
          title={t('home.apps.title')}
          items={isChatTab ? chats.data : undefined}
          isPending={isChatTab && chats.isPending}
          isError={isChatTab && chats.isError}
          onRetry={() => void chats.refetch()}
          empty={appsEmpty}
          seeAll={
            isChatTab ? <ResourceMiniCard title={t('home.seeAll')} href="/chats" /> : undefined
          }
          action={
            <ToggleButtonGroup
              exclusive
              size="small"
              value={tab}
              onChange={(_event, next: AppsTab | null) => {
                if (next !== null) setTab(next)
              }}
            >
              <ToggleButton value="chat">{t('home.apps.chat')}</ToggleButton>
              <ToggleButton value="search">{t('home.apps.search')}</ToggleButton>
              {flags.agent ? (
                <ToggleButton value="agent">{t('home.apps.agent')}</ToggleButton>
              ) : null}
            </ToggleButtonGroup>
          }
          renderItem={(chat) => (
            <ResourceMiniCard
              title={chat.name}
              description={chat.description}
              href={'/chat/' + chat.id}
            />
          )}
        />
      </Stack>
    </PageContainer>
  )
}
