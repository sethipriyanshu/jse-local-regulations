import { describe, expect, it } from 'vitest'
import { looksLikeAddress, mapStatus } from './jurisdictions'

describe('looksLikeAddress', () => {
  it.each([
    ['2201 Paul W Bryant Dr, Tuscaloosa AL', true],
    ['100B Main St', true],
    ['Tuscaloosa', false],
    ['Fulton County, GA', false],
    ['35401', false],
  ])('%s → %s', (q, expected) => expect(looksLikeAddress(q)).toBe(expected))
})

describe('mapStatus', () => {
  it('shows pilots without data as pilot, and real coverage over pilot', () => {
    expect(mapStatus({ coverage: 'none', is_pilot: true })).toBe('pilot')
    expect(mapStatus({ coverage: 'verified', is_pilot: true })).toBe('verified')
    expect(mapStatus({ coverage: 'none', is_pilot: false })).toBe('none')
    expect(mapStatus(undefined)).toBe('none')
  })
})
