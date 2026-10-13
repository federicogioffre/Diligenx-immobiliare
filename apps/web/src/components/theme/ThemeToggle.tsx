'use client'

import { ThemePreference, useTheme } from './ThemeProvider'

const ORDER: ThemePreference[] = ['system', 'light', 'dark']

const LABEL: Record<ThemePreference, string> = {
  system: 'Sistema',
  light: 'Chiaro',
  dark: 'Scuro',
}

const ICON: Record<ThemePreference, string> = {
  system: 'M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z',
  light: 'M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z',
  dark: 'M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z',
}

export function ThemeIcon({ value, className = 'w-4 h-4' }: { value: ThemePreference; className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8} aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" d={ICON[value]} />
    </svg>
  )
}

/** Compact navbar button: cycles Sistema → Chiaro → Scuro. */
export default function ThemeToggle() {
  const { preference, setPreference } = useTheme()
  const next = ORDER[(ORDER.indexOf(preference) + 1) % ORDER.length]
  return (
    <button
      type="button"
      onClick={() => setPreference(next)}
      title={`Tema: ${LABEL[preference]} (passa a ${LABEL[next]})`}
      aria-label={`Tema: ${LABEL[preference]}. Passa a ${LABEL[next]}`}
      className="inline-flex items-center justify-center w-8 h-8 rounded-lg text-slate-500 hover:text-slate-900 hover:bg-slate-100 transition-colors"
    >
      <ThemeIcon value={preference} />
    </button>
  )
}

/** Three-way choice for the account page. */
export function ThemeChooser() {
  const { preference, setPreference } = useTheme()
  return (
    <div role="radiogroup" aria-label="Tema dell'interfaccia" className="grid grid-cols-3 gap-2 max-w-md">
      {ORDER.map((p) => {
        const active = preference === p
        return (
          <button
            key={p}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => setPreference(p)}
            className={`flex flex-col items-center gap-2 rounded-xl border px-3 py-3 text-sm font-medium transition-all ${
              active
                ? 'border-blue-500 bg-blue-50 text-blue-700 ring-2 ring-blue-500/20'
                : 'border-slate-200 bg-surface text-slate-600 hover:border-slate-300 hover:text-slate-900'
            }`}
          >
            <ThemeIcon value={p} className="w-5 h-5" />
            {LABEL[p]}
          </button>
        )
      })}
    </div>
  )
}
