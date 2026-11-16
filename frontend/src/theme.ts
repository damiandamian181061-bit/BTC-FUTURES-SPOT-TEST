import { useEffect, useState } from 'react'

export type Theme = 'system' | 'light' | 'dark'
const KEY = 'btc-dashboard-theme'

function stored(): Theme {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

/** Light / dark / follow the OS. The choice lives only in this browser (localStorage). */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(stored)
  useEffect(() => {
    const el = document.documentElement
    if (theme === 'system') delete el.dataset.theme
    else el.dataset.theme = theme
    try {
      localStorage.setItem(KEY, theme)
    } catch {
      /* private window or blocked storage: the page still works */
    }
  }, [theme])
  return [theme, setTheme] as const
}
