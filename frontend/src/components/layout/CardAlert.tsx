// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/dashboard/components/CardAlert.tsx (MIT). Zmiany: eksport named, prop `show` (brak → null), teksty i18n (alert.models.*), przycisk = link do /user-setting/model, formatowanie Prettier.
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Typography from '@mui/material/Typography'
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded'
import { Link } from '@tanstack/react-router'
import type { LinkProps } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

export function CardAlert(props: { show: boolean }) {
  const { t } = useTranslation()

  if (!props.show) return null

  return (
    <Card variant="outlined" sx={{ m: 1.5, flexShrink: 0 }}>
      <CardContent>
        <AutoAwesomeRoundedIcon fontSize="small" />
        <Typography gutterBottom sx={{ fontWeight: 600 }}>
          {t('alert.models.title')}
        </Typography>
        <Typography variant="body2" sx={{ mb: 2, color: 'text.secondary' }}>
          {t('alert.models.body')}
        </Typography>
        <Button
          variant="contained"
          size="small"
          fullWidth
          component={Link}
          // trasy dochodzą w E3-2…E3-6 — jedyne miejsce z rozluźnieniem typu `to`.
          to={'/user-setting/model' as LinkProps['to']}
        >
          {t('alert.models.action')}
        </Button>
      </CardContent>
    </Card>
  )
}
