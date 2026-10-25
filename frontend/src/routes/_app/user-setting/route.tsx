import { Outlet, createFileRoute } from '@tanstack/react-router'

// Sekcja Ustawień (kontrakt WP E3-6c1 §4) — bez własnego guardu, dostępna dla każdego
// zalogowanego użytkownika (sesję pilnuje `_app`); zapis i tak ogranicza backend.
export const Route = createFileRoute('/_app/user-setting')({
  component: () => <Outlet />,
})
