// Operacje Dockera na kontenerach stosu wd-ci-* (wzór: tools/dev/real/kill.sh i mem-sampler.sh):
// identyfikator kontenera usługi compose, `docker restart` workera (SC-E5-H8a-03), próbka
// CPU/RSS z `docker stats --no-stream` (SC-E5-H8a-06c) i limit pamięci kontenera z `docker inspect`.
// Nigdy `pkill` — sygnały i restarty wyłącznie przez Docker po identyfikatorze kontenera.
import { execFile, execFileSync } from 'node:child_process'
import { promisify } from 'node:util'

const run = promisify(execFile)

/**
 * Identyfikator kontenera usługi compose w projekcie (np. `worker`, `fake-llm`);
 * usługa nie działa albo projekt nie istnieje → null. Bez plików compose —
 * `docker compose -p <proj> ps` czyta etykiety kontenerów (jak worker_cid w kill.sh).
 */
export function serviceContainerId(project: string, service: string): string | null {
  try {
    const out = execFileSync('docker', ['compose', '-p', project, 'ps', '-q', service], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim()
    return out === '' ? null : out
  } catch {
    return null
  }
}

/**
 * Restart kontenera (`docker restart`); blokuje do chwili ponownego startu kontenera.
 * `graceS` to czas łaski na SIGTERM przed SIGKILL (`docker restart --time`) — SC-E5-H8a-03
 * chce zabić workera, ZANIM dokończy bieżące zadanie, więc domyślnie tylko 1 s.
 */
export async function restartContainer(
  cid: string,
  timeoutMs = 180_000,
  graceS = 1,
): Promise<void> {
  await run('docker', ['restart', '--time', String(graceS), cid], { timeout: timeoutMs })
}

/** Jedna próbka `docker stats --no-stream`: procent CPU i użyta pamięć w bajtach. */
export type StatsSample = { cpu_percent: number; mem_bytes: number }

/**
 * Próbka CPU/RSS kontenera; odczyt nieudany (kontener w restarcie, chwilowy błąd Dockera)
 * → null — próbki nieudane po prostu nie wchodzą do szczytu.
 */
export async function containerStats(cid: string): Promise<StatsSample | null> {
  try {
    const { stdout } = await run(
      'docker',
      ['stats', '--no-stream', '--format', '{{.CPUPerc}}|{{.MemUsage}}', cid],
      { timeout: 30_000 },
    )
    const [cpuPart, memPart] = stdout.trim().split('|')
    const memBytes = parseDockerBytes((memPart ?? '').split('/')[0]?.trim() ?? '')
    const cpu = Number.parseFloat((cpuPart ?? '').replace('%', '').trim())
    if (memBytes === null || !Number.isFinite(cpu)) return null
    return { cpu_percent: cpu, mem_bytes: memBytes }
  } catch {
    return null
  }
}

/**
 * Limit pamięci kontenera w bajtach (`HostConfig.Memory` z `docker inspect`);
 * bez limitu (0) albo bez odczytu → null — wtedy spec porównuje z limitem z compose.
 */
export async function containerMemoryLimitBytes(cid: string): Promise<number | null> {
  try {
    const { stdout } = await run('docker', ['inspect', '--format', '{{.HostConfig.Memory}}', cid], {
      timeout: 30_000,
    })
    const value = Number(stdout.trim())
    return Number.isFinite(value) && value > 0 ? value : null
  } catch {
    return null
  }
}

/**
 * Liczba bajtów z licznika Dockera („1.2GiB”, „500MiB”, „1.5kB”) — jednostki jak w
 * `docker stats` i w `to_bytes` z tools/dev/real/mem-sampler.sh: KiB/MiB/GiB/TiB binarne,
 * kB/MB/GB/TB dziesiętne. Nierozpoznany format → null.
 */
export function parseDockerBytes(raw: string): number | null {
  const match = /^([0-9]+(?:\.[0-9]+)?)(B|kB|MB|GB|TB|KiB|MiB|GiB|TiB)$/.exec(raw.trim())
  if (match === null) return null
  const value = Number.parseFloat(match[1] ?? '')
  if (!Number.isFinite(value)) return null
  const multipliers: Record<string, number> = {
    B: 1,
    kB: 1000,
    MB: 1000 ** 2,
    GB: 1000 ** 3,
    TB: 1000 ** 4,
    KiB: 1024,
    MiB: 1024 ** 2,
    GiB: 1024 ** 3,
    TiB: 1024 ** 4,
  }
  const unit = match[2] ?? 'B'
  return Math.round(value * (multipliers[unit] ?? 1))
}
