import { useCallback, useEffect, useState } from 'react'
import type { Dashboard } from './types'

// 1. the FastAPI backend computes the numbers live (dev: Vite proxies /api to 127.0.0.1:8000; Docker: same origin)
// 2. fallback: the dashboard.json the 23:10 UTC task last wrote (dev: Vite serves ../data/paper at /data)
const API_URL = `${import.meta.env.BASE_URL}api/dashboard`
const FILE_URL = `${import.meta.env.BASE_URL}data/dashboard.json`

export type Source = 'api' | 'file'

async function fetchJson(url: string): Promise<Dashboard> {
  const res = await fetch(`${url}?t=${Date.now()}`, { cache: 'no-store', headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  const type = res.headers.get('content-type') ?? ''
  if (!type.includes('json')) throw new Error(`not JSON (${type || 'no content type'})`)
  const json = (await res.json()) as Dashboard
  if (json.schema !== 1) throw new Error(`unexpected schema ${String(json.schema)}; rebuild the front end`)
  return json
}

export function useDashboard(pollMs = 60_000) {
  const [data, setData] = useState<Dashboard | null>(null)
  const [source, setSource] = useState<Source | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      let json: Dashboard
      let src: Source = 'api'
      try {
        json = await fetchJson(API_URL)
      } catch (apiErr) {
        try {
          json = await fetchJson(FILE_URL)
          src = 'file'
        } catch (fileErr) {
          const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))
          throw new Error(`API: ${msg(apiErr)}; file: ${msg(fileErr)}`)
        }
      }
      setData(json)
      setSource(src)
      setError(null)
      setFetchedAt(new Date())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const id = window.setInterval(() => void refresh(), pollMs)
    return () => window.clearInterval(id)
  }, [refresh, pollMs])

  return { data, source, error, loading, fetchedAt, refresh }
}
