/**
 * Wspólny stan pusty listy (08 §7.3): karta z przerywaną ramką, ikoną, tytułem, opisem i akcją
 * (np. „Utwórz …”). Sygnatura z kontraktu WP E3-5a §5 — używają jej kolejne listy (czaty, datasety).
 */

import type { ReactNode } from 'react'
import Box from '@mui/material/Box'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'

export type EmptyStateProps = {
  title: string
  description?: string
  action?: ReactNode
  icon?: ReactNode
}

export function EmptyState(props: EmptyStateProps) {
  const { title, description, action, icon } = props

  return (
    <Card variant="outlined" data-testid="empty-state" sx={{ borderStyle: 'dashed' }}>
      <CardContent>
        <Stack spacing={2} sx={{ alignItems: 'center', textAlign: 'center', py: 2 }}>
          {icon !== undefined ? <Box sx={{ color: 'text.secondary' }}>{icon}</Box> : null}
          <Typography variant="h6">{title}</Typography>
          {description !== undefined ? (
            <Typography variant="body2" color="text.secondary">
              {description}
            </Typography>
          ) : null}
          {action}
        </Stack>
      </CardContent>
    </Card>
  )
}
