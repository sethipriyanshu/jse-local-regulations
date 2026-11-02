export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

/** JSON fetch against the backend. Errors carry FastAPI's `detail` message when present. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: 'same-origin',
    ...init,
    headers: { 'Content-Type': 'application/json', ...init.headers },
  })
  if (!res.ok) {
    let message = res.statusText
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') message = body.detail
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(res.status, message)
  }
  return (await res.json()) as T
}

export type Health = { status: 'ok' | 'degraded'; db: string; env: string }
