// Augmentacja statycznych danych trasy TanStack Router.
// `fullBleed` jest używane przez AppLayout (T6b) do wykrycia widoków pełnoekranowych.
declare module '@tanstack/react-router' {
  interface StaticDataRouteOption {
    fullBleed?: boolean
  }
}

export {}
