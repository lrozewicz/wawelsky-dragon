/**
 * Test dryfu: `src/api/schema.gen.ts` (commitowany) musi być bajtowo równy świeżej generacji
 * z `../backend/openapi.json`. To samo co `bun run gen:api:check`, ale programowo (vitest).
 */
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// Vitest uruchamiamy z katalogu frontendu (`bun run test:cov`), a `import.meta.url` w środowisku
// jsdom nie jest URL-em `file:` — dlatego katalogiem odniesienia jest cwd procesu.
const frontendRoot = process.cwd()
const cli = join(frontendRoot, 'node_modules', '.bin', 'openapi-typescript')
const committedSchema = join(frontendRoot, 'src', 'api', 'schema.gen.ts')
const generatedSchema = join(tmpdir(), 'schema.check.ts')

describe('schema.gen.ts', () => {
  it('jest aktualny wobec backend/openapi.json', () => {
    execFileSync(cli, ['../backend/openapi.json', '-o', generatedSchema], { cwd: frontendRoot })

    expect(readFileSync(committedSchema, 'utf8')).toBe(readFileSync(generatedSchema, 'utf8'))
  })
})
