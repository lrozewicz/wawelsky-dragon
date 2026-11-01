import { type JSX } from 'react'
import Box from '@mui/material/Box'
import { useTranslation } from 'react-i18next'

import logoFullDark from './brand/logo-full.png'
import logoFullLight from './brand/logo-full-light.png'
import logoMarkDark from './brand/logo-mark.png'
import logoMarkLight from './brand/logo-mark-light.png'

// Proporcje `brand/logo-full.png` (640 × 330); druga wersja różni się o 3 px, wyrównuje ją `contain`.
const FULL_RATIO = 330 / 640

/**
 * Oficjalny logotyp. `full` (znak + napis) tam, gdzie jest miejsce; `mark` (sam smok) w wąskich
 * miejscach (zwinięte menu, pasek mobilny). `size` to szerokość obrazu w px.
 * Każdy wariant ma wersję na jasne i ciemne tło. Przełącza je CSS, bo tryb „system” jest znany
 * dopiero przeglądarce; ukryty obraz (`display: none`) nie trafia do drzewa dostępności.
 */
export function BrandLogo(props: { size?: number; variant?: 'full' | 'mark' }): JSX.Element {
  const { t } = useTranslation()
  const variant = props.variant ?? 'mark'
  const size = props.size ?? 32
  const height = variant === 'full' ? Math.round(size * FULL_RATIO) : size
  const image = { alt: t('app.name'), width: size, height }
  const base = { flexShrink: 0, objectFit: 'contain' } as const

  return (
    <>
      <Box
        component="img"
        src={variant === 'full' ? logoFullLight : logoMarkLight}
        {...image}
        sx={[
          { ...base, display: 'block' },
          (theme) => theme.applyStyles('dark', { display: 'none' }),
        ]}
      />
      <Box
        component="img"
        src={variant === 'full' ? logoFullDark : logoMarkDark}
        {...image}
        sx={[
          { ...base, display: 'none' },
          (theme) => theme.applyStyles('dark', { display: 'block' }),
        ]}
      />
    </>
  )
}
