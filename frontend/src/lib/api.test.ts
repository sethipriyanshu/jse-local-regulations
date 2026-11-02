import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'

function mockFetch(status: number, body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(body), { status, statusText: 'Status' })),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('api', () => {
  it('prefixes /api and parses JSON', async () => {
    mockFetch(200, { status: 'ok' })
    await expect(api('/health')).resolves.toEqual({ status: 'ok' })
    expect(fetch).toHaveBeenCalledWith('/api/health', expect.anything())
  })

  it('surfaces FastAPI detail messages as ApiError', async () => {
    mockFetch(401, { detail: 'Wrong passcode' })
    const err = (await api('/admin/login').catch((e: unknown) => e)) as ApiError
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(401)
    expect(err.message).toBe('Wrong passcode')
  })
})
