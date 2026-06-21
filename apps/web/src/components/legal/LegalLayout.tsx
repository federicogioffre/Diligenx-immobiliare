import Link from 'next/link'
import type { ReactNode } from 'react'

const NAV = [
  { href: '/privacy',  label: 'Privacy Policy' },
  { href: '/cookies',  label: 'Cookie Policy' },
  { href: '/terms',    label: 'Termini di Servizio' },
  { href: '/dpa',      label: 'DPA' },
  { href: '/security', label: 'Security Overview' },
]

interface Props {
  title: string
  subtitle?: string
  /** Show a "DRAFT — pending legal review" banner. Default: true. */
  draft?: boolean
  /** Last updated date in dd/mm/yyyy. */
  lastUpdated?: string
  children: ReactNode
}

/**
 * Shared layout for compliance / legal pages: side nav, draft banner,
 * "last updated" line, and the prose container that styles the children
 * via the @tailwindcss/typography ``prose`` classes.
 */
export default function LegalLayout({
  title,
  subtitle,
  draft = true,
  lastUpdated,
  children,
}: Props) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-[16rem_1fr] gap-8">
      <aside className="lg:sticky lg:top-20 self-start">
        <nav className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
          <p className="px-2 pb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Compliance
          </p>
          <ul className="flex flex-col">
            {NAV.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="block px-2 py-1.5 rounded-md text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition-colors"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </aside>

      <main className="max-w-2xl">
        <header className="mb-6">
          <h1 className="text-3xl font-semibold text-slate-900 tracking-tight">{title}</h1>
          {subtitle && <p className="mt-2 text-slate-600">{subtitle}</p>}
          {lastUpdated && (
            <p className="mt-2 text-xs text-slate-500">Ultimo aggiornamento: {lastUpdated}</p>
          )}
        </header>

        {draft && (
          <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            <div className="flex items-start gap-2">
              <svg className="w-4 h-4 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <div>
                <p className="font-semibold">Bozza — in attesa di revisione legale</p>
                <p className="mt-1 leading-relaxed">
                  Il testo definitivo sarà pubblicato a valle della validazione da
                  parte del nostro consulente privacy. Per la versione contrattuale
                  attuale o per richieste specifiche, scrivere a{' '}
                  <a href="mailto:privacy@diligenx.example" className="underline hover:no-underline">
                    privacy@diligenx.example
                  </a>
                  .
                </p>
              </div>
            </div>
          </div>
        )}

        <article className="prose prose-slate prose-sm sm:prose-base max-w-none">
          {children}
        </article>
      </main>
    </div>
  )
}
