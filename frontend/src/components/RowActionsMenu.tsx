/**
 * Menu ⋮ akcji wiersza (kontrakt WP E3-7 §C2): na szerokości < md zastępuje rząd przycisków,
 * dzięki czemu akcje są widoczne bez przewijania poziomego. Klik pozycji woła jej `onClick`
 * i zamyka menu; Esc zamyka je obsługą `Menu` MUI. Pozycja `disabled` nie woła `onClick`.
 */

import { useState } from 'react'
import type { JSX, ReactNode } from 'react'
import MoreVertIcon from '@mui/icons-material/MoreVert'
import IconButton from '@mui/material/IconButton'
import ListItemIcon from '@mui/material/ListItemIcon'
import ListItemText from '@mui/material/ListItemText'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'

export type RowActionItem = {
  key: string
  label: string
  icon?: ReactNode
  onClick: () => void
  disabled?: boolean
}

export type RowActionsMenuProps = {
  items: RowActionItem[]
  ariaLabel: string
}

export function RowActionsMenu(props: RowActionsMenuProps): JSX.Element {
  const { items, ariaLabel } = props
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)

  function handleClose(): void {
    setAnchorEl(null)
  }

  return (
    <>
      <IconButton
        aria-label={ariaLabel}
        data-testid="row-actions-menu"
        onClick={(event) => setAnchorEl(event.currentTarget)}
      >
        <MoreVertIcon />
      </IconButton>
      <Menu anchorEl={anchorEl} open={anchorEl !== null} onClose={handleClose}>
        {items.map((item) => (
          <MenuItem
            key={item.key}
            data-testid={`row-action-${item.key}`}
            disabled={item.disabled}
            onClick={() => {
              item.onClick()
              handleClose()
            }}
          >
            {item.icon === undefined ? null : <ListItemIcon>{item.icon}</ListItemIcon>}
            <ListItemText>{item.label}</ListItemText>
          </MenuItem>
        ))}
      </Menu>
    </>
  )
}
