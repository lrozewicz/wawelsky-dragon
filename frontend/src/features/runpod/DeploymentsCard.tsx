/**
 * Sekcja „Wdrożenia” w Ustawieniach → RunPod: lista podów z datą, kosztem i trybem wygasania,
 * ręczne wyłączenie działającego poda oraz czyszczenie historii (zakończone wdrożenia).
 */

import type { JSX } from 'react'
import DeleteSweepIcon from '@mui/icons-material/DeleteSweep'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { resolveLanguage } from '../../i18n'
import { formatDateTime } from '../../lib/format'

import { deploymentsQueryOptions, useClearHistory, useTerminate } from './api'
import type { RunpodDeployment } from './api'

const STATUS_COLOR: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
  ready: 'success',
  failed: 'error',
  terminated: 'default',
  terminating: 'default',
}

export function DeploymentsCard(props: { isSuperuser: boolean }): JSX.Element {
  const { isSuperuser } = props
  const { t, i18n } = useTranslation()
  const language = resolveLanguage(i18n.language)
  const deployments = useQuery(deploymentsQueryOptions())
  const terminate = useTerminate()
  const clearHistory = useClearHistory()
  const rows = deployments.data ?? []
  const hasEnded = rows.some((row: RunpodDeployment) => !row.active)

  return (
    <Card data-testid="runpod-deployments-card">
      <CardContent>
        <Stack spacing={1.5}>
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
            <Typography variant="h6">{t('runpod.deployments.title')}</Typography>
            {isSuperuser ? (
              <Tooltip title={t('runpod.deployments.clearHistory')}>
                <span>
                  <IconButton
                    size="small"
                    aria-label={t('runpod.deployments.clearHistory')}
                    disabled={!hasEnded || clearHistory.isPending}
                    onClick={() => clearHistory.mutate()}
                    data-testid="runpod-clear-history"
                  >
                    <DeleteSweepIcon fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
            ) : null}
          </Stack>
          {rows.length === 0 ? (
            <Typography color="text.secondary">{t('runpod.deployments.empty')}</Typography>
          ) : (
            <Table size="small" aria-label={t('runpod.deployments.title')}>
              <TableHead>
                <TableRow>
                  <TableCell>{t('runpod.deployments.date')}</TableCell>
                  <TableCell>{t('runpod.deployments.model')}</TableCell>
                  <TableCell>{t('runpod.deployments.gpu')}</TableCell>
                  <TableCell>{t('runpod.deployments.status')}</TableCell>
                  <TableCell align="right">{t('runpod.deployments.cost')}</TableCell>
                  <TableCell />
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row: RunpodDeployment) => (
                  <TableRow key={row.id} data-testid={`runpod-deployment-${row.id}`}>
                    <TableCell data-testid={`runpod-date-${row.id}`}>
                      {formatDateTime(row.created_at, language)}
                    </TableCell>
                    <TableCell>{row.title}</TableCell>
                    <TableCell>
                      {t('runpod.deployments.gpuCell', {
                        name: row.gpu.name,
                        vram: row.gpu.vram_gb,
                      })}
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        color={STATUS_COLOR[row.status] ?? 'info'}
                        label={t(`runpod.status.${row.status}`, { defaultValue: row.status })}
                      />
                      {row.active ? (
                        <Typography
                          variant="caption"
                          color="text.secondary"
                          sx={{ display: 'block' }}
                          data-testid={`runpod-lifetime-${row.id}`}
                        >
                          {row.idle_shutdown_s === null
                            ? t('runpod.deployments.manualOnly')
                            : t('runpod.deployments.autoOff', {
                                minutes: Math.round(row.idle_shutdown_s / 60),
                              })}
                        </Typography>
                      ) : null}
                      {row.error ? (
                        <Typography variant="caption" color="error" sx={{ display: 'block' }}>
                          {row.error}
                        </Typography>
                      ) : null}
                    </TableCell>
                    <TableCell align="right">
                      {t('runpod.units.usd', { value: row.cost_so_far.toFixed(2) })}
                    </TableCell>
                    <TableCell align="right">
                      {row.active && isSuperuser ? (
                        <Button
                          size="small"
                          color="error"
                          disabled={terminate.isPending}
                          onClick={() => terminate.mutate(row.id)}
                          data-testid={`runpod-terminate-${row.id}`}
                        >
                          {t('runpod.deployments.terminate')}
                        </Button>
                      ) : null}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Stack>
      </CardContent>
    </Card>
  )
}
