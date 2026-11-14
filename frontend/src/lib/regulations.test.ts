import { describe, expect, it } from 'vitest'
import { exportUrl } from './regulations'

describe('exportUrl', () => {
  it('builds a plain URL by default', () => {
    expect(exportUrl('01125', 'pdf')).toBe('/api/jurisdictions/01125/export.pdf')
  })
  it('carries the address stack and filters', () => {
    const url = exportUrl('0177256', 'docx', {
      stack: ['01', '01125', '0177256'], includePending: false, address: '2201 University Blvd',
    })
    const q = new URL(url, 'http://x').searchParams
    expect(q.get('stack')).toBe('01,01125,0177256')
    expect(q.get('include_pending')).toBe('false')
    expect(q.get('address')).toBe('2201 University Blvd')
  })
})
