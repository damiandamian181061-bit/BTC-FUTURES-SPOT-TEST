import { useCallback, useEffect, useState } from 'react'
import type { Dashboard } from './types'

// Dev: vite.config.ts serves ../data/paper at /data. Built site: scripts/copy-data.mjs puts the file in dist/data/.
const DATA_URL = `${import.meta.env.BASE_URL}data/dashboard.json`

export function useDashboard(pollMs = 60_000) {
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${DATA_URL}?t=${Date.now()}`, { cache: 'no-store' })
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      const json = (await res.json()) as Dashboard
      if (json.schema !== 1) throw new Error(`unexpected schema ${String(json.schema)}; rebuild the front end`)
      setData(json)
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

  return { data, error, loading, fetchedAt, refresh }
}
