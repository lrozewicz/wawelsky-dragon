import { Outlet, createRootRouteWithContext } from '@tanstack/react-router'

import type { RouterContext } from '../app/routerContext'

export const Route = createRootRouteWithContext<RouterContext>()({ component: () => <Outlet /> })
