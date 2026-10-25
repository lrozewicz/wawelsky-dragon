/**
 * Czyste funkcje magazynu wierszy paska zadań (kontrakt WP E7-2 §6). Hook: `taskStore.test.tsx`.
 */

import { beforeEach, describe, expect, it } from 'vitest'

import {
  describeTaskProgress,
  isFinishedTask,
  KB_TASK_POLL_MS,
  KB_TASK_TTL_MS,
  kbTasksStorageKey,
  readKbTasks,
} from './taskStore'
import type { StoredKbTask, WdTask } from './types'

const KEY = kbTasksStorageKey('u1')
const NOW = 1_760_000_000_000

function wdTask(overrides: Partial<WdTask> = {}): WdTask {
  return {
    task_id: 'task-1',
    kind: 'export',
    dataset_id: 'd1',
    status: 'running',
    stage: 'chunks',
    done: 3000,
    total: 7251,
    progress: 0.41,
    message: 'Chunki 3000/7251',
    error: null,
    created_at: NOW,
    finished_at: null,
    result: null,
    ...overrides,
  }
}

function storedRow(overrides: Partial<StoredKbTask> = {}): StoredKbTask {
  return {
    task_id: 'task-1',
    kind: 'export',
    label: 'Rocznik GUS 2024',
    dataset_id: 'd1',
    added_at: NOW,
    last: null,
    ...overrides,
  }
}

beforeEach(() => {
  localStorage.clear()
})

describe('kbTasksStorageKey', () => {
  it('wyprowadza klucz magazynu z identyfikatora aktora', () => {
    expect(kbTasksStorageKey('u1')).toBe('wd.kbTasks.v1:u1')
  })
})

describe('stałe magazynu', () => {
  it('odpytanie co 2 s i wiek wiersza 24 h (kontrakt §6, §2)', () => {
    // Literały, nie import stałych — inaczej zmiana wartości przechodzi niezauważona.
    expect(KB_TASK_POLL_MS).toBe(2000)
    expect(KB_TASK_TTL_MS).toBe(24 * 60 * 60 * 1000)
  })
})

describe('describeTaskProgress', () => {
  it('daje klucz i18n etapu, licznik i procent', () => {
    expect(describeTaskProgress(wdTask())).toEqual({
      stageKey: 'kbTransfer.stage.chunks',
      done: 3000,
      total: 7251,
      percent: 41,
    })
  })

  it('zaokrągla procent i zostawia pusty klucz dla zadania bez etapu', () => {
    expect(describeTaskProgress(wdTask({ stage: null, progress: 0.456 })).stageKey).toBe('')
    expect(describeTaskProgress(wdTask({ progress: 0.456 })).percent).toBe(46)
    expect(describeTaskProgress(wdTask({ progress: 1 })).percent).toBe(100)
  })
})

describe('isFinishedTask', () => {
  it('rozpoznaje statusy końcowe, brak stanu i stan w toku', () => {
    expect(isFinishedTask(null)).toBe(false)
    expect(isFinishedTask(wdTask({ status: 'queued' }))).toBe(false)
    expect(isFinishedTask(wdTask({ status: 'running' }))).toBe(false)
    expect(isFinishedTask(wdTask({ status: 'done' }))).toBe(true)
    expect(isFinishedTask(wdTask({ status: 'failed' }))).toBe(true)
    expect(isFinishedTask(wdTask({ status: 'cancelled' }))).toBe(true)
  })
})

describe('readKbTasks', () => {
  it('pusty magazyn to pusta lista', () => {
    expect(readKbTasks(KEY, NOW)).toEqual([])
  })

  it('usuwa wpisy starsze niż 24 h, świeże zostawia', () => {
    const fresh = storedRow({ task_id: 'task-fresh', last: wdTask({ status: 'done' }) })
    const stale = storedRow({ task_id: 'task-stale', added_at: NOW - 25 * 60 * 60 * 1000 })
    localStorage.setItem(KEY, JSON.stringify([stale, fresh]))

    expect(readKbTasks(KEY, NOW)).toEqual([fresh])
  })

  it('wiersz zakończony starzeje się od finished_at, nie od added_at (E67 SC-E67-02)', () => {
    const day = 24 * 60 * 60 * 1000
    const oldFinished = storedRow({
      task_id: 'task-old',
      added_at: NOW - 2 * 60 * 1000,
      finished_at: NOW - day - 1,
    })
    const freshFinished = storedRow({
      task_id: 'task-new',
      added_at: NOW - 3 * day,
      finished_at: NOW - 60 * 1000,
    })
    localStorage.setItem(KEY, JSON.stringify([oldFinished, freshFinished]))

    expect(readKbTasks(KEY, NOW)).toEqual([freshFinished])
  })

  it('nieczytelna zawartość magazynu jest równoważna z pustym', () => {
    localStorage.setItem(KEY, '{to nie jest JSON')
    expect(readKbTasks(KEY, NOW)).toEqual([])

    localStorage.setItem(KEY, '{"task_id":"task-1"}')
    expect(readKbTasks(KEY, NOW)).toEqual([])
  })

  it('pomija wpisy o niepoprawnym kształcie', () => {
    const good = storedRow()
    localStorage.setItem(
      KEY,
      JSON.stringify([
        null,
        'task-1',
        { task_id: 5, added_at: NOW },
        { task_id: 'bez-czasu' },
        { task_id: 'bez-stanu', added_at: NOW },
        { task_id: 'zly-stan', added_at: NOW, last: 'done' },
        good,
      ]),
    )

    expect(readKbTasks(KEY, NOW)).toEqual([good])
  })
})
