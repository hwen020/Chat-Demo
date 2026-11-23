export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string) { super(code) }
}

async function verify(response: Response) {
  if (response.ok) return response
  const body = await response.json().catch(() => null)
  throw new ApiError(response.status, body?.error?.code ?? 'request_failed')
}

export async function api<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal) {
  const response = await verify(await fetch('/v1' + path, {
    method, signal, credentials: 'same-origin',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  }))
  return (response.status === 204 ? undefined : await response.json()) as T
}
