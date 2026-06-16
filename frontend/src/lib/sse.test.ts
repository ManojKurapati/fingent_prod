import { describe, expect, it, vi } from 'vitest'
import { subscribeJob } from './sse'
import type { JobEvent } from './types'

// A minimal fake EventSource we can drive from tests (jsdom has no EventSource).
class FakeEventSource {
  static instances: FakeEventSource[] = []
  url: string
  onerror: ((ev: unknown) => void) | null = null
  listeners: Record<string, ((ev: MessageEvent) => void)[]> = {}
  closed = false
  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }
  addEventListener(type: string, cb: (ev: MessageEvent) => void) {
    ;(this.listeners[type] ??= []).push(cb)
  }
  emit(type: string, data: unknown) {
    const ev = { data: JSON.stringify(data) } as MessageEvent
    for (const cb of this.listeners[type] ?? []) cb(ev)
  }
  close() {
    this.closed = true
  }
}

describe('subscribeJob', () => {
  it('parses step events and forwards them', () => {
    const events: JobEvent[] = []
    subscribeJob('job-1', { onEvent: (e) => events.push(e) }, FakeEventSource as never)
    const es = FakeEventSource.instances.at(-1)!
    expect(es.url).toContain('/jobs/job-1/events')

    es.emit('step', { job_id: 'job-1', type: 'step', payload: { step: 'data-intake', status: 'completed' } })
    expect(events).toHaveLength(1)
    expect(events[0].payload.step).toBe('data-intake')
  })

  it('returns an unsubscribe that closes the stream', () => {
    const unsubscribe = subscribeJob('job-2', { onEvent: () => {} }, FakeEventSource as never)
    const es = FakeEventSource.instances.at(-1)!
    unsubscribe()
    expect(es.closed).toBe(true)
  })

  it('invokes onError when the stream errors', () => {
    const onError = vi.fn()
    subscribeJob('job-3', { onEvent: () => {}, onError }, FakeEventSource as never)
    const es = FakeEventSource.instances.at(-1)!
    es.onerror?.({})
    expect(onError).toHaveBeenCalled()
  })
})
