import { describe, expect, it } from 'vitest'
import { bboxOf, unionBbox } from './geo'

describe('bboxOf', () => {
  it('covers every ring of a multipolygon', () => {
    const bbox = bboxOf({
      type: 'MultiPolygon',
      coordinates: [
        [[[-88, 33], [-87, 33], [-87, 34], [-88, 33]]],
        [[[-90, 32], [-89, 32], [-89, 35], [-90, 32]]],
      ],
    })
    expect(bbox).toEqual([-90, 32, -87, 35])
  })

  it('unions boxes and handles empty input', () => {
    expect(unionBbox([[0, 0, 1, 1], [-1, 0.5, 0.5, 2]])).toEqual([-1, 0, 1, 2])
    expect(unionBbox([])).toBeNull()
  })
})
