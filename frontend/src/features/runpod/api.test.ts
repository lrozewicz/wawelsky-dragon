import { describe, expect, it } from 'vitest'

import { WdApiError } from '../admin/wdClient'

import { alternativesOf, isTerminal } from './api'
import { deploymentPercent } from './DeploymentProgress'

describe('runpod api helpers', () => {
  it('alternativesOf czyta zamienniki tylko z błędu gpu_unavailable', () => {
    const gpu = { id: 'A40', name: 'A40', vram_gb: 48 }
    const err = new WdApiError('gpu_unavailable', 'gone', 409, { alternatives: [gpu] })
    expect(alternativesOf(err)).toEqual([gpu])
    expect(alternativesOf(new WdApiError('conflict', 'x', 409, { alternatives: [gpu] }))).toEqual(
      [],
    )
    expect(alternativesOf(new Error('boom'))).toEqual([])
    expect(alternativesOf(new WdApiError('gpu_unavailable', 'gone', 409))).toEqual([])
  })

  it('stany końcowe i procent postępu', () => {
    expect(isTerminal('failed')).toBe(true)
    expect(isTerminal('terminated')).toBe(true)
    expect(isTerminal('ready')).toBe(false)
    expect(deploymentPercent('provisioning')).toBeLessThan(deploymentPercent('loading'))
    expect(deploymentPercent('ready')).toBe(100)
    expect(deploymentPercent('failed')).toBe(0)
  })
})
