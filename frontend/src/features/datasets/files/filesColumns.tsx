/**
 * Kolumny siatki plików datasetu (kontrakt WP E3-3b §T5, spec 08 §7.4). `buildColumns` dostaje
 * zależności komponentu (callbacki akcji, identyfikator datasetu, język) i zwraca definicje
 * kolumn (plik nie zna `DatasetFilesTab`). Etykiety z `i18n` — odświeżają się z rodzicem.
 * Od WP E6-1b T5a: kolumna „Metadane” (gdy `showMetadata`, ≥ 1536 px, kontrakt E6-1b §4) pokazuje
 * do 2 chipów `klucz: wartość` + „+N”; pusta komórka = „—”, chipy z wielokropkiem i `title` (U2).
 */

import type { JSX, ReactNode } from 'react'
import CodeOutlinedIcon from '@mui/icons-material/CodeOutlined'
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined'
import ImageOutlinedIcon from '@mui/icons-material/ImageOutlined'
import InsertDriveFileOutlinedIcon from '@mui/icons-material/InsertDriveFileOutlined'
import PictureAsPdfIcon from '@mui/icons-material/PictureAsPdf'
import SlideshowOutlinedIcon from '@mui/icons-material/SlideshowOutlined'
import TableChartOutlinedIcon from '@mui/icons-material/TableChartOutlined'
import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import Switch from '@mui/material/Switch'
import Typography from '@mui/material/Typography'
import type { GridColDef } from '@mui/x-data-grid'
import { Link } from '@tanstack/react-router'

import { RowActionsMenu } from '../../../components/RowActionsMenu'
import type { RowActionItem } from '../../../components/RowActionsMenu'
import { i18n } from '../../../i18n'
import type { Language } from '../../../i18n'
import { formatDateTime, formatNumber } from '../../../lib/format'
import { summarizeMeta } from '../../metadata/convert'
import { chunksLinkProps } from '../chunks/links'
import { CHUNK_METHODS } from '../queries'
import { ParsingStatusCell } from './ParsingStatusCell'
import type { ParsingStatusDoc } from './ParsingStatusCell'
import type { DocumentRow } from './queries'

/** Ikona pliku wg rozszerzenia (nieznane → ogólna); przy md–xl znika, by nazwa miała miejsce (T3). */
const FILE_TYPE_ICONS: Record<string, typeof InsertDriveFileOutlinedIcon> = {
  pdf: PictureAsPdfIcon,
  doc: DescriptionOutlinedIcon,
  docx: DescriptionOutlinedIcon,
  odt: DescriptionOutlinedIcon,
  rtf: DescriptionOutlinedIcon,
  txt: DescriptionOutlinedIcon,
  md: DescriptionOutlinedIcon,
  xls: TableChartOutlinedIcon,
  xlsx: TableChartOutlinedIcon,
  csv: TableChartOutlinedIcon,
  ppt: SlideshowOutlinedIcon,
  pptx: SlideshowOutlinedIcon,
  png: ImageOutlinedIcon,
  jpg: ImageOutlinedIcon,
  jpeg: ImageOutlinedIcon,
  gif: ImageOutlinedIcon,
  webp: ImageOutlinedIcon,
  svg: ImageOutlinedIcon,
  html: CodeOutlinedIcon,
  htm: CodeOutlinedIcon,
  json: CodeOutlinedIcon,
  xml: CodeOutlinedIcon,
}

function FileTypeIcon(props: { suffix: string }): JSX.Element {
  const Icon = FILE_TYPE_ICONS[props.suffix.toLowerCase()] ?? InsertDriveFileOutlinedIcon
  return <Icon fontSize="small" color="action" sx={{ display: { md: 'none', xl: 'block' } }} />
}

/** Czy metoda chunkowania ma tłumaczenie `datasets.method.<nazwa>` (inaczej pokazujemy surowy tekst). */
function isKnownMethod(method: string): boolean {
  return CHUNK_METHODS.some((known) => known === method)
}

export type FilesColumnsContext = {
  datasetId: string
  language: Language
  /** `Switch` „Włączony” — nowy stan przełącznika. */
  onToggle: (doc: DocumentRow, enabled: boolean) => void
  /** ▶ i ↻ komórki statusu (T7: przez `ReparseDialog`, gdy dokument ma chunki). */
  onParse: (doc: ParsingStatusDoc) => void
  /** ⊗ komórki statusu. */
  onStop: (doc: ParsingStatusDoc) => void
  /** Klik w tekst statusu — dialog logu parsowania. */
  onOpenLog: (doc: ParsingStatusDoc) => void
  /** Klik w chip metody chunkowania — T7 otwiera dialog jej zmiany. */
  onOpenMethod: (doc: DocumentRow) => void
  /** Slot akcji wiersza — T6/T7 wnosi `RowActions`; bez niego komórka jest pusta. */
  renderActions?: (doc: DocumentRow) => ReactNode
  /** Wzorzec < md (kontrakt WP E3-7 §C2): kolumna akcji pierwsza, treścią menu ⋮. */
  compact?: boolean
  /** Akcje wiersza jako dane menu ⋮ — tryb compact; desktop nadal używa `renderActions`. */
  compactActions?: (doc: DocumentRow) => RowActionItem[]
  /** Kolumna „Metadane” widoczna dopiero ≥ 1536 px (kontrakt WP E6-1b §4 — TL 2026-10-13: xl; przy 1280 nie mieści się obok kolumn siatki, spec 08 §7.14 b). */
  showMetadata?: boolean
  /** `false` ukrywa „Metodę chunkowania” (md–xl) — miejsce dla „Nazwy” (E67-z2 T6). */
  showMethod?: boolean
}

export function buildColumns(ctx: FilesColumnsContext): GridColDef<DocumentRow>[] {
  const { language } = ctx

  return [
    {
      field: 'name',
      headerName: i18n.t('datasets.files.col.name'),
      flex: 1,
      // < md tabela przewija się poziomo → 160 px (T3); md–xl bez „Metody” (T6) nazwa ma ~180 px.
      minWidth: ctx.compact === true ? 160 : 90,
      sortable: true, // serwerowo po `name` (kontrakt WP E3-H2a §K1, DEC-138)
      renderCell: (params) => (
        // Nazwa: jedna linia z wielokropkiem (U2 / R-UI-03; ujednolicone w QA V13-z-1 W3 —
        // wcześniej dwa wiersze łamały nazwę w środku słowa, a obok inny wiersz miał
        // wielokropek), pełna nazwa w `title`; `Link` bez `sx` — styl w `a`.
        <Stack
          direction="row"
          sx={{
            alignItems: 'center',
            gap: 1,
            minWidth: 0,
            '& a': {
              color: 'text.primary',
              fontWeight: 500,
              textDecoration: 'none',
              '&:hover': { textDecoration: 'underline' },
              minWidth: 0,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              lineHeight: 1.3,
            },
          }}
        >
          <FileTypeIcon suffix={params.row.suffix} />
          <Link {...chunksLinkProps(ctx.datasetId, params.row.id)} title={params.row.name}>
            {params.row.name}
          </Link>
        </Stack>
      ),
    },
    {
      field: 'create_time',
      headerName: i18n.t('datasets.files.col.uploaded'),
      // „11 paź 2026, 01:12” ma ~136 px treści, a nagłówek ze strzałką sortu ~149 px (pomiar
      // T7; 160 ucinało nagłówek wielokropkiem).
      width: 170,
      renderCell: (params) => formatDateTime(params.row.create_time, language),
    },
    {
      field: 'enabled',
      headerName: i18n.t('datasets.files.col.enabled'),
      width: 90,
      sortable: false,
      filterable: false,
      disableColumnMenu: true,
      renderCell: (params) => (
        <Switch
          size="small"
          checked={params.row.status === '1'}
          data-testid={`doc-enabled-${params.row.id}`}
          // Etykieta trafia na sam `input` — inaczej czytnik ekranu nie nazwałby przełącznika.
          slotProps={{ input: { 'aria-label': i18n.t('datasets.files.col.enabled') } }}
          onChange={(event) => ctx.onToggle(params.row, event.target.checked)}
        />
      ),
    },
    {
      field: 'chunk_count',
      headerName: i18n.t('datasets.files.col.chunks'),
      // Nagłówek „Chunks” ma ~68 px z paddingiem (pomiar T7); liczby są krótsze.
      width: 72,
      sortable: false,
      renderCell: (params) => formatNumber(params.row.chunk_count, language),
    },
    ...(ctx.showMethod !== false
      ? [
          {
            field: 'chunk_method',
            headerName: i18n.t('datasets.files.col.method'),
            // Nagłówek „Metoda chunkowania” (U8): ~148,5 px treści + 20 px paddingu → 173 bez wielokropka.
            width: 173,
            sortable: false,
            renderCell: (params) =>
              isKnownMethod(params.row.chunk_method) ? (
                <Chip
                  size="small"
                  variant="outlined"
                  label={i18n.t(`datasets.method.${params.row.chunk_method}`)}
                  onClick={() => ctx.onOpenMethod(params.row)}
                />
              ) : (
                <Typography variant="body2">{params.row.chunk_method}</Typography>
              ),
          } satisfies GridColDef<DocumentRow>,
        ]
      : []),
    {
      field: 'run',
      headerName: i18n.t('datasets.files.col.status'),
      // Najszerszy stan (parsing z paskiem 52 px, „W kolejce” z ⊗) mieści się w ~158 px (T7).
      width: 160,
      sortable: false,
      renderCell: (params) => (
        <ParsingStatusCell
          doc={params.row}
          onParse={ctx.onParse}
          onStop={ctx.onStop}
          onOpenLog={ctx.onOpenLog}
        />
      ),
    },
    // Kolumna „Metadane” (E6-1b §4): do 2 chipów + „+N”; długa wartość z wielokropkiem i pełnym `title`
    // (też na etykiecie — testy e2e czytają atrybut z elementu tekstu); T3: chipy zawijają się do 2. linii.
    ...(ctx.showMetadata === true
      ? [
          {
            field: 'meta_fields',
            headerName: i18n.t('datasets.files.col.metadata'),
            // 190 px (T3): przy 1600 px siatka ma ~1310 px, kolumna „Nazwa” zostaje ≥ 220 px.
            width: 190,
            sortable: false,
            filterable: false,
            disableColumnMenu: true,
            renderCell: (params) => {
              const chips = summarizeMeta(params.row.meta_fields)
              if (chips.length === 0) {
                return (
                  <Typography variant="body2" color="text.disabled">
                    {i18n.t('datasets.files.col.metadataEmpty')}
                  </Typography>
                )
              }
              const visible = chips.slice(0, 2)
              const hidden = chips.slice(2)
              return (
                <Stack
                  direction="row"
                  sx={{
                    minWidth: 0,
                    maxHeight: '100%',
                    overflow: 'hidden',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: '2px 4px',
                  }}
                >
                  {visible.map((chip) => (
                    <Chip
                      key={chip.key}
                      size="small"
                      variant="outlined"
                      label={chip.text}
                      title={chip.full}
                      sx={{
                        minWidth: 0,
                        maxWidth: '100%',
                        '& .MuiChip-label': {
                          minWidth: 0,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        },
                      }}
                      slotProps={{ label: { title: chip.full } }}
                    />
                  ))}
                  {hidden.length > 0 ? (
                    <Chip
                      size="small"
                      variant="outlined"
                      label={`+${hidden.length}`}
                      title={hidden.map((chip) => chip.full).join('\n')}
                      // „+N” nigdy nie skraca się — to widoczna informacja o ukrytych polach.
                      sx={{ flexShrink: 0 }}
                    />
                  ) : null}
                </Stack>
              )
            },
          } satisfies GridColDef<DocumentRow>,
        ]
      : []),
    {
      field: 'actions',
      headerName: i18n.t('datasets.files.col.actions'),
      // Desktop: 3 przyciski `small` (36 px) + ⋮ (44 px) + 3 odstępy + padding = 178; kompakt: samo ⋮, 84 px mieści nagłówek „Actions” (T8; E3-7 §C2).
      width: ctx.compact === true ? 84 : 178,
      sortable: false,
      filterable: false,
      disableColumnMenu: true,
      renderCell: (params) =>
        ctx.compact === true && ctx.compactActions !== undefined ? (
          <RowActionsMenu
            items={ctx.compactActions(params.row)}
            ariaLabel={i18n.t('common.rowActions')}
          />
        ) : (
          (ctx.renderActions?.(params.row) ?? null)
        ),
    },
  ]
}
