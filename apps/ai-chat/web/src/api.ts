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

export type StreamEvent = { id: number; kind: string; data: { text?: string; code?: string; state?: string } }

export async function readEvents(path: string, cursor: number, signal: AbortSignal,
                                 receive: (event: StreamEvent) => void) {
  const response = await verify(await fetch('/v1' + path + '?after=' + cursor, { signal }))
  if (!response.body) throw new Error('missing_stream')
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += value
      let end = buffer.indexOf('\n\n')
      while (end >= 0) {
        const frame = buffer.slice(0, end)
        buffer = buffer.slice(end + 2)
        const fields = new Map(frame.split('\n').filter(line => line.includes(': '))
          .map(line => [line.slice(0, line.indexOf(': ')), line.slice(line.indexOf(': ') + 2)] as const))
        const kind = fields.get('event')
        if (kind) receive({ id: Number(fields.get('id') ?? 0), kind, data: JSON.parse(fields.get('data') ?? '{}') })
        end = buffer.indexOf('\n\n')
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
