/**
 * Mała karta zasobu na stronie Home (08 §7.2): nazwa + opis albo liczba plików.
 * Karta jest zwykłym `<a href>` (semantyka linku: ctrl/middle-click i „otwórz w nowej karcie”
 * działają), ale zwykły klik przejmuje router — bez przeładowania dokumentu (kontrakt E5-H6a §C2).
 */

import { useNavigate } from '@tanstack/react-router'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { isPlainLeftClick } from '../../lib/linkClick'

export type ResourceMiniCardProps = {
  title: string
  href: string
  description?: string | null
  filesCount?: number
}

export function ResourceMiniCard({ title, href, description, filesCount }: ResourceMiniCardProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  let subtitle: string | null = null
  if (typeof description === 'string' && description !== '') {
    subtitle = description
  } else if (filesCount !== undefined) {
    subtitle = t('home.files', { count: filesCount })
  }

  return (
    <Card
      component="a"
      href={href}
      variant="outlined"
      data-testid="resource-card"
      // Zwykły klik nawiguje routerem; modyfikatory i inne przyciski zostawiamy przeglądarce.
      onClick={(event) => {
        if (!isPlainLeftClick(event)) return
        event.preventDefault()
        void navigate({ href })
      }}
      sx={{ minWidth: 180, textDecoration: 'none' }}
    >
      <CardContent>
        {/* Kafelek bez podtytułu („Zobacz wszystkie”) zawija tytuł zamiast go ucinać. */}
        <Typography variant="subtitle1" noWrap={subtitle !== null} title={title}>
          {title}
        </Typography>
        {subtitle !== null ? (
          <Typography variant="body2" color="text.secondary" noWrap>
            {subtitle}
          </Typography>
        ) : null}
      </CardContent>
    </Card>
  )
}
