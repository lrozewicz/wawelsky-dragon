/**
 * Lista GPU RunPod z filtrami (VRAM, region, kraj, cloud, tylko dostępne) i wyborem jednego.
 * Używana na stronie Ustawień i w oknie pytania o włączenie poda. Dane z `GET /runpod/gpus`.
 */

import { useMemo, useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import FormControlLabel from '@mui/material/FormControlLabel'
import MenuItem from '@mui/material/MenuItem'
import Radio from '@mui/material/Radio'
import Stack from '@mui/material/Stack'
import Switch from '@mui/material/Switch'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import TextField from '@mui/material/TextField'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { gpusQueryOptions } from './api'
import type { GpuFilters, RunpodGpu } from './api'

export type GpuSelection = {
  gpu: RunpodGpu
  cloud: GpuFilters['cloud']
  region: string
  country: string
}

export type GpuPickerProps = {
  model: string
  /** Początkowy dolny próg VRAM (np. VRAM poprzednio użytego GPU). */
  initialMinVram?: number
  /** Domyślnie tylko GPU, które mają teraz wolne maszyny. */
  initialOnlyAvailable?: boolean
  /** GPU zaznaczone na starcie (np. użyte poprzednio), o ile jest na liście. */
  preselectId?: string | null
  selectedId: string | null
  onSelect: (selection: GpuSelection) => void
  /** Informacja nad listą (np. że poprzednie GPU jest niedostępne). */
  notice?: JSX.Element | null
}

const AVAILABILITY_COLOR: Record<string, 'success' | 'warning' | 'error' | 'text.secondary'> = {
  HIGH: 'success',
  MEDIUM: 'warning',
  LOW: 'warning',
  NONE: 'error',
}

export function GpuPicker(props: GpuPickerProps): JSX.Element {
  const {
    model,
    initialMinVram,
    initialOnlyAvailable = false,
    selectedId,
    onSelect,
    notice,
  } = props
  const { t } = useTranslation()
  const [cloud, setCloud] = useState<GpuFilters['cloud']>('SECURE')
  const [minVram, setMinVram] = useState<string>(initialMinVram ? String(initialMinVram) : '')
  const [maxVram, setMaxVram] = useState('')
  const [region, setRegion] = useState('')
  const [country, setCountry] = useState('')
  const [onlyAvailable, setOnlyAvailable] = useState(initialOnlyAvailable)

  const filters: GpuFilters = useMemo(
    () => ({
      model,
      cloud,
      minVram: minVram === '' ? undefined : Number(minVram),
      maxVram: maxVram === '' ? undefined : Number(maxVram),
      region,
      country,
      onlyAvailable,
    }),
    [model, cloud, minVram, maxVram, region, country, onlyAvailable],
  )
  const query = useQuery(gpusQueryOptions(filters))
  const catalog = query.data

  return (
    <Stack spacing={2} data-testid="runpod-gpu-picker">
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={1.5}
        useFlexGap
        sx={{ flexWrap: 'wrap' }}
      >
        <TextField
          select
          size="small"
          label={t('runpod.filter.cloud')}
          value={cloud}
          onChange={(event) => setCloud(event.target.value as GpuFilters['cloud'])}
          sx={{ minWidth: 150 }}
          slotProps={{ htmlInput: { 'data-testid': 'runpod-filter-cloud' } }}
        >
          <MenuItem value="SECURE">{t('runpod.filter.secure')}</MenuItem>
          <MenuItem value="COMMUNITY">{t('runpod.filter.community')}</MenuItem>
        </TextField>
        <TextField
          size="small"
          type="number"
          label={t('runpod.filter.minVram')}
          value={minVram}
          onChange={(event) => setMinVram(event.target.value)}
          sx={{ width: 130 }}
          slotProps={{ htmlInput: { min: 1, 'data-testid': 'runpod-filter-min-vram' } }}
        />
        <TextField
          size="small"
          type="number"
          label={t('runpod.filter.maxVram')}
          value={maxVram}
          onChange={(event) => setMaxVram(event.target.value)}
          sx={{ width: 130 }}
          slotProps={{ htmlInput: { min: 1, 'data-testid': 'runpod-filter-max-vram' } }}
        />
        <TextField
          select
          size="small"
          label={t('runpod.filter.region')}
          value={region}
          onChange={(event) => setRegion(event.target.value)}
          sx={{ minWidth: 170 }}
          slotProps={{ htmlInput: { 'data-testid': 'runpod-filter-region' } }}
        >
          <MenuItem value="">{t('runpod.filter.any')}</MenuItem>
          {(catalog?.regions ?? []).map((item) => (
            <MenuItem key={item} value={item}>
              {t(`runpod.region.${item}`, { defaultValue: item })}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          size="small"
          label={t('runpod.filter.country')}
          value={country}
          onChange={(event) => setCountry(event.target.value)}
          sx={{ minWidth: 130 }}
          slotProps={{ htmlInput: { 'data-testid': 'runpod-filter-country' } }}
        >
          <MenuItem value="">{t('runpod.filter.any')}</MenuItem>
          {(catalog?.countries ?? []).map((item) => (
            <MenuItem key={item} value={item}>
              {item}
            </MenuItem>
          ))}
        </TextField>
        <FormControlLabel
          control={
            <Switch
              checked={onlyAvailable}
              onChange={(event) => setOnlyAvailable(event.target.checked)}
              slotProps={{ input: { 'data-testid': 'runpod-filter-available' } as never }}
            />
          }
          label={t('runpod.filter.onlyAvailable')}
        />
      </Stack>
      {notice}
      {query.isPending ? <CircularProgress size={24} aria-label={t('runpod.loading')} /> : null}
      {query.isError ? <Alert severity="error">{t('runpod.gpus.error')}</Alert> : null}
      {catalog !== undefined && catalog.gpus.length === 0 ? (
        <Alert severity="info">{t('runpod.gpus.empty')}</Alert>
      ) : null}
      {catalog !== undefined && catalog.gpus.length > 0 ? (
        <Table size="small" aria-label={t('runpod.gpus.table')}>
          <TableHead>
            <TableRow>
              <TableCell padding="checkbox" />
              <TableCell>{t('runpod.gpus.name')}</TableCell>
              <TableCell align="right">{t('runpod.gpus.vram')}</TableCell>
              <TableCell align="right">{t('runpod.gpus.price')}</TableCell>
              <TableCell>{t('runpod.gpus.availability')}</TableCell>
              <TableCell>{t('runpod.gpus.where')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {catalog.gpus.map((gpu) => {
              const selectable = gpu.fits && gpu.availability !== 'NONE'
              return (
                <TableRow
                  key={gpu.id}
                  hover={selectable}
                  selected={gpu.id === selectedId}
                  data-testid={`runpod-gpu-${gpu.id}`}
                  sx={selectable ? undefined : { opacity: 0.55 }}
                >
                  <TableCell padding="checkbox">
                    <Radio
                      checked={gpu.id === selectedId}
                      disabled={!selectable}
                      onChange={() => onSelect({ gpu, cloud, region, country })}
                      slotProps={{ input: { 'aria-label': gpu.name } }}
                    />
                  </TableCell>
                  <TableCell>{gpu.name}</TableCell>
                  <TableCell align="right">
                    {t('runpod.units.gb', { value: gpu.vram_gb })}
                  </TableCell>
                  <TableCell align="right">
                    {t('runpod.units.perHour', { value: gpu.price_per_hr.toFixed(2) })}
                  </TableCell>
                  <TableCell
                    sx={{ color: AVAILABILITY_COLOR[gpu.availability] ?? 'text.secondary' }}
                  >
                    {t(`runpod.availability.${gpu.availability}`, {
                      defaultValue: gpu.availability,
                    })}
                    {gpu.fits
                      ? ''
                      : ` — ${t('runpod.gpus.tooSmall', { min: catalog.min_vram_gb })}`}
                  </TableCell>
                  <TableCell>
                    {gpu.data_centers
                      .slice(0, 4)
                      .map((dc) => dc.id)
                      .join(', ')}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      ) : null}
    </Stack>
  )
}
