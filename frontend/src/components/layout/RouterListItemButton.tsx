import * as React from 'react'
import ListItemButton from '@mui/material/ListItemButton'
import { createLink } from '@tanstack/react-router'
import type { LinkProps } from '@tanstack/react-router'

// createLink przyjmuje komponent (ListItemButton jest forwardRef) i zwraca link nawigacyjny.
export const RouterListItemButton = createLink(ListItemButton)

export function NavLink(
  props: { to: string } & Omit<React.ComponentProps<typeof ListItemButton>, 'href'>,
) {
  const { to, ...rest } = props
  // trasy dochodzą w E3-2…E3-6 — jedyne miejsce z rozluźnieniem typu `to`.
  return <RouterListItemButton to={to as LinkProps['to']} {...rest} />
}
