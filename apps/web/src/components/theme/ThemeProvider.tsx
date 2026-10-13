'use client'

import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { usePathname } from 'next/navigation'

export type ThemePreference = 'light' | 'dark' | 'system'

export const THEME_STORAGE_KEY = 'dm_theme'

// Marketing landing and sign-in are designed light only.
export const LIGHT_ONLY_PATHS = ['/', '/login']

/**
 * Runs in <head> before the first paint, so a dark-mode visitor never sees a
 * white flash. Kept in sync with `applyTheme` below.
 */
export const THEME_BOOT_SCRIPT = `(function(){try{var p=location.pathname;if(${JSON.stringify(
  LIGHT_ONLY_PATHS,
)}.indexOf(p)>=0)return;var t=localStorage.getItem('${THEME_STORAGE_KEY}');var d=t==='dark'||(t!=='light'&&window.matchMedia('(prefers-color-scheme: dark)').matches);if(d)document.documentElement.classList.add('dark')}catch(e){}})()`

interface ThemeContextValue {
  preference: ThemePreference
  /** What is actually on screen once the preference and the page are applied. */
  resolved: 'light' | 'dark'
  setPreference: (p: ThemePreference) => void
}

const ThemeContext = createContext<ThemeContextValue>({
  preference: 'system',
  resolved: 'light',
  setPreference: () => {},
})

export function useTheme() {
  return useContext(ThemeContext)
}

function readPreference(): ThemePreference {
  try {
    const v = localStorage.getItem(THEME_STORAGE_KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

export default function ThemeProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const [preference, setPref] = useState<ThemePreference>('system')
  const [systemDark, setSystemDark] = useState(false)
  // Until the stored preference is read, leave the class the boot script set.
  const [ready, setReady] = useState(false)

  useEffect(() => {
    setPref(readPreference())
    setReady(true)
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    setSystemDark(mql.matches)
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [])

  const lightOnly = LIGHT_ONLY_PATHS.includes(pathname)
  const resolved: 'light' | 'dark' =
    !lightOnly && (preference === 'dark' || (preference === 'system' && systemDark)) ? 'dark' : 'light'

  useEffect(() => {
    if (ready) document.documentElement.classList.toggle('dark', resolved === 'dark')
  }, [ready, resolved])

  const setPreference = useCallback((p: ThemePreference) => {
    setPref(p)
    try {
      if (p === 'system') localStorage.removeItem(THEME_STORAGE_KEY)
      else localStorage.setItem(THEME_STORAGE_KEY, p)
    } catch {
      /* private mode: the choice lasts for this tab only */
    }
  }, [])

  return (
    <ThemeContext.Provider value={{ preference, resolved, setPreference }}>
      {children}
    </ThemeContext.Provider>
  )
}
