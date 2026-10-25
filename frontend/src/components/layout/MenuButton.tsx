// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/dashboard/components/MenuButton.tsx (MIT). Zmiany: eksport named, import typu `IconButtonProps` przez `import type`, formatowanie Prettier.
import Badge, { badgeClasses } from '@mui/material/Badge'
import IconButton from '@mui/material/IconButton'
import type { IconButtonProps } from '@mui/material/IconButton'

export interface MenuButtonProps extends IconButtonProps {
  showBadge?: boolean
}

export function MenuButton({ showBadge = false, ...props }: MenuButtonProps) {
  return (
    <Badge
      color="error"
      variant="dot"
      invisible={!showBadge}
      sx={{ [`& .${badgeClasses.badge}`]: { right: 2, top: 2 } }}
    >
      <IconButton size="small" {...props} />
    </Badge>
  )
}
