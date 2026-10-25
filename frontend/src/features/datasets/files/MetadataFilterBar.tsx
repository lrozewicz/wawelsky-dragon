/**
 * Filtr metadanych listy dokumentów (kontrakt WP E6-1b §4, spec 08 §7.14 b): przycisk „Filtr
 * metadanych” i chip „Metadane: n warunków” nad tabelą. Klik otwiera Popover 390 px z kreatorem
 * warunków w trybie ręcznym (`modes=['manual']` — wartość widoku jest wymuszana do `manual`
 * na granicy widoku, dopisek TL) i przyciskami „Zastosuj”/„Wyczyść”. Roboczy stan kreatora
 * (logika + warunki) żyje w rodzicu (`DatasetFilesTab`), więc przetrwa zamknięcie popovera;
 * „Zastosuj” commituje go do zapytania listy (`metadata_condition`) i wraca na stronę 1.
 * Otwarcie z pustym stanem tworzy pierwszy wiersz warunku (SC-E6-1b-04 krok 1: „Warunek 1”
 * widoczny od razu); × chipa i „Wyczyść” usuwają filtr i czyszczą stan roboczy.
 */
import { useState } from 'react'
import type { JSX, MouseEvent } from 'react'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import Popover from '@mui/material/Popover'
import Stack from '@mui/material/Stack'
import CloseIcon from '@mui/icons-material/Close'
import { useTranslation } from 'react-i18next'

import { MetadataConditionBuilder } from '../../metadata/MetadataConditionBuilder'
import type { MetaCondition, MetaFilter } from '../../metadata/types'

export type MetadataFilterBarProps = {
  /** Bieżący dataset — kreator czyta z niego klucze i znane wartości (`useMetaKeys`). */
  datasetId: string
  /** Roboczy stan kreatora (żyje w rodzicu — przetrwa zamknięcie popovera). */
  logic: 'and' | 'or'
  conditions: MetaCondition[]
  /** Liczba warunków aktywnego (zastosowanego) filtra; 0 = chip ukryty. */
  activeCount: number
  /** Zmiana stanu roboczego z kreatora. */
  onChange: (logic: 'and' | 'or', conditions: MetaCondition[]) => void
  /** „Zastosuj”: commit stanu roboczego do zapytania listy; popover zamyka się sam. */
  onApply: () => void
  /** Chip × i „Wyczyść”: usunięcie filtra i wyczyszczenie stanu roboczego. */
  onClear: () => void
}

/** Świeży wiersz warunku po otwarciu/wyczyszczeniu kreatora (jak „+ Warunek” bez podpowiedzi). */
function emptyCondition(): MetaCondition {
  return { key: '', op: '=', value: '' }
}

export function MetadataFilterBar(props: MetadataFilterBarProps): JSX.Element {
  const { datasetId, logic, conditions, activeCount, onChange, onApply, onClear } = props
  const { t } = useTranslation()
  // Kotwica popovera (element przycisku) — `null` = zamknięty (wzorzec: `FileFilter`).
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)

  function open(event: MouseEvent<HTMLButtonElement>): void {
    // Kreator w trybie ręcznym bez wiersza to ślepy zaułek — pierwszy (pusty) warunek od razu;
    // pusty klucz jest oznaczony `aria-invalid`, a podpowiedzi kluczy są pod ręką w comboboxie.
    if (conditions.length === 0) {
      onChange('and', [emptyCondition()])
    }
    setAnchor(event.currentTarget)
  }

  function clear(): void {
    onClear()
    // Po wyczyszczeniu kreator zostaje otwarty z świeżym pustym wierszem — użytkownik może
    // układać filtr od nowa bez ponownego otwierania popovera.
    if (anchor !== null) {
      onChange('and', [emptyCondition()])
    }
  }

  // Coercja po stronie widoku (dopisek TL): kreator dostaje `method: 'manual'`, nawet gdy stan
  // roboczy rodzica jeszcze go nie niesie; tryby auto/semi_auto do filtra listy nie trafiają.
  const builderValue: MetaFilter = { method: 'manual', logic, manual: conditions, semi_auto: [] }

  return (
    <>
      <Button size="small" data-testid="metadata-filter" onClick={open}>
        {t('metadata.filter.title')}
      </Button>
      {activeCount > 0 ? (
        <Chip
          size="small"
          data-testid="metadata-filter-chip"
          label={t('metadata.listFilter.chip', { count: activeCount })}
          onDelete={onClear}
          // Wąski wiersz narzędzi (QA V12-z-1, C15): chip nie może zawijać „Prześlij plik"
          // do drugiej linii. `flex-wrap` łamie wiersz po BAZOWYCH rozmiarach, więc samo
          // `min-width: 0` nie wystarcza — od `md` chip ma `flex-basis: 0` i rośnie w wolne
          // miejsce wiersza (etykieta z wielokropkiem, `.MuiChip-label`), a na xs zostaje
          // przy naturalnym rozmiarze (własny wiersz slotu filtra).
          sx={{ minWidth: 0, flex: { xs: '0 1 auto', md: '1 1 0' } }}
          // × z aria-label wg kontraktu §4 (wzorzec MUI: svg z aria-label — e2e klika po
          // atrybucie `[aria-label="Usuń filtr metadanych"]`; bez nadmiarowego pudełka IconButton,
          // które wystawało kwadratem poza zaokrąglony chip).
          deleteIcon={<CloseIcon aria-label={t('metadata.listFilter.remove')} />}
        />
      ) : null}
      <Popover
        open={anchor !== null}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
        // Domyślny marginThreshold=16 pozwalał popoverowi 390 px wyjść 16 px poza lewą
        // krawędź okna 390 px (mierzone 2026-10-13: paper x=-16); 0 = krawędź w krawędź.
        marginThreshold={0}
        slotProps={{
          paper: {
            // 390 px (kontrakt §4); na wąskim ekranie pełna szerokość okna (R-UI-01).
            sx: { width: { xs: 'min(100vw, 390px)', sm: 390 }, maxWidth: '100vw' },
          },
        }}
      >
        <Stack spacing={2} sx={{ p: 2 }}>
          <MetadataConditionBuilder
            value={builderValue}
            onChange={(next) => onChange(next.logic === 'or' ? 'or' : 'and', next.manual)}
            datasetIds={[datasetId]}
            modes={['manual']}
            // Komunikat braku metadanych z linkiem do Konfiguracji (kontrakt §4).
            datasetConfigLinkId={datasetId}
          />
          <Stack direction="row" spacing={1} sx={{ justifyContent: 'flex-end' }}>
            <Button onClick={clear}>{t('metadata.listFilter.clear')}</Button>
            <Button
              variant="contained"
              onClick={() => {
                onApply()
                setAnchor(null)
              }}
            >
              {t('metadata.listFilter.apply')}
            </Button>
          </Stack>
        </Stack>
      </Popover>
    </>
  )
}
