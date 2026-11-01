import type { JSX } from 'react'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import { keyframes } from '@mui/material/styles'
import { useTranslation } from 'react-i18next'

const pulse = keyframes`
  0%, 80%, 100% { opacity: 0.25; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
`

/** Wskaźnik „asystent pracuje”: od wysłania pytania do pierwszego znaku odpowiedzi. */
export function AnswerLoader(): JSX.Element {
  const { t } = useTranslation()

  return (
    <Box
      role="status"
      data-testid="answer-loader"
      sx={{ display: 'inline-flex', alignItems: 'center', gap: 1, py: 0.5 }}
    >
      <Box aria-hidden sx={{ display: 'inline-flex', gap: 0.5 }}>
        {[0, 1, 2].map((index) => (
          <Box
            key={index}
            sx={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              bgcolor: 'primary.main',
              animation: `${pulse} 1.2s ease-in-out infinite`,
              animationDelay: `${index * 0.15}s`,
              '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
            }}
          />
        ))}
      </Box>
      <Typography variant="body2" color="text.secondary">
        {t('chat.msg.analyzing')}
      </Typography>
    </Box>
  )
}
