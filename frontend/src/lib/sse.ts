// SSE client for live job progress — FROZEN CONTRACT.
//
// Subscribes to `GET /jobs/{id}/events` and forwards parsed JobEvents. The
// EventSource implementation is injectable so it can be unit-tested without a
// browser/network (jsdom has no EventSource).

import type { JobEvent } from './types'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

// The event `type`s the backend emits (format_sse sets the SSE `event:` field).
const EVENT_TYPES = ['message', 'step', 'status', 'progress'] as const

interface EventSourceLike {
  addEventListener(type: string, cb: (ev: MessageEvent) => void): void
  close(): void
  onerror: ((ev: unknown) => void) | null
}

type EventSourceCtor = new (url: string) => EventSourceLike

export interface SubscribeHandlers {
  onEvent: (event: JobEvent) => void
  onError?: (error: unknown) => void
}

export function subscribeJob(
  jobId: string,
  handlers: SubscribeHandlers,
  EventSourceImpl: EventSourceCtor = globalThis.EventSource as unknown as EventSourceCtor,
): () => void {
  const source = new EventSourceImpl(`${BASE}/jobs/${jobId}/events`)

  const onMessage = (ev: MessageEvent) => {
    try {
      handlers.onEvent(JSON.parse(ev.data) as JobEvent)
    } catch (err) {
      handlers.onError?.(err)
    }
  }
  for (const type of EVENT_TYPES) source.addEventListener(type, onMessage)
  source.onerror = (err) => handlers.onError?.(err)

  return () => source.close()
}
