import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist', 'coverage', '.tanstack', 'src/routeTree.gen.ts']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
    ],
    languageOptions: { ecmaVersion: 2023, globals: globals.browser },
  },
  {
    // Harness e2e: fixture'y Playwrighta wołają `use(...)` z API Playwrighta (nie hook Reacta),
    // a `base.extend<{}>` deklaruje brak nowych fixture'ów — reguły Reacta tu nie pasują.
    files: ['e2e/**/*.ts', 'playwright.config.ts'],
    rules: {
      'react-hooks/rules-of-hooks': 'off',
      '@typescript-eslint/no-empty-object-type': 'off',
    },
  },
  {
    files: ['src/features/**/*.{ts,tsx}', 'src/components/**/*.{ts,tsx}'],
    rules: { 'max-lines': ['error', { max: 300, skipBlankLines: false, skipComments: false }] },
  },
  {
    // 08 §12 p. 6 — surowy fetch tylko w warstwie api i strumieniu SSE.
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/api/**', 'src/lib/sse.ts', '**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: "CallExpression[callee.name='fetch']",
          message:
            'Surowe fetch() jest zakazane — użyj klienta z src/api (wyjątek: src/api/**, src/lib/sse.ts) (08 §12 p. 6).',
        },
      ],
    },
  },
  {
    // 08 §10.1 — zakaz literałów tekstowych w JSX; 08 §12 p. 6 — zakaz surowego fetch.
    // Blok nadpisuje poprzedni dla tych katalogów, dlatego powtarza tu selektor fetch.
    files: [
      'src/features/**/*.{ts,tsx}',
      'src/components/**/*.{ts,tsx}',
      'src/routes/**/*.{ts,tsx}',
    ],
    ignores: ['**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: 'JSXText[value=/\\S/]',
          message: 'Literały w JSX są zakazane — użyj t() (08 §10.1).',
        },
        {
          selector: "CallExpression[callee.name='fetch']",
          message:
            'Surowe fetch() jest zakazane — użyj klienta z src/api (wyjątek: src/api/**, src/lib/sse.ts) (08 §12 p. 6).',
        },
      ],
    },
  },
])
