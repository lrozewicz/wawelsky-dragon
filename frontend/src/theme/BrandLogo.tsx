import { type JSX } from 'react'
import { useTranslation } from 'react-i18next'

// Własny, minimalny znak smoka: łeb z dwoma rogami i otwartym pyskiem.
// Oko jest wycięte z sylwetki (`fillRule="evenodd"`), więc prześwieca tłem w obu trybach.
// Rysunek autorski, nie kopia cudzego logo; kolor dziedziczony z otoczenia (`currentColor`).
const DRAGON =
  'M14 31C10 30 8 26 9 23L3 21L9 18L7 14C7 11 10 8 14 8L11 2L17 6L19 3L20 8C24 10 26 14 25 18C24 23 22 27 20 31ZM17 11.4A1.6 1.6 0 1 0 17 14.6A1.6 1.6 0 0 0 17 11.4Z'

export function BrandLogo(props: { size?: number }): JSX.Element {
  const { t } = useTranslation()
  const size = props.size ?? 32

  return (
    <svg
      role="img"
      aria-label={t('app.name')}
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="currentColor"
    >
      <path d={DRAGON} fillRule="evenodd" />
    </svg>
  )
}
