import Link from 'next/link'

// Branded 404 — rendered for any route that doesn't exist. Server
// component: no client JS needed.
export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="w-12 h-12 bg-blue-600 rounded-xl flex items-center justify-center shadow-sm mb-6">
        <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      </div>
      <p className="text-sm font-semibold text-blue-600 tracking-wide">404</p>
      <h1 className="mt-2 text-2xl font-semibold text-slate-900">
        Pagina non trovata
      </h1>
      <p className="mt-3 text-sm text-slate-500 max-w-md">
        La pagina che cerchi non esiste o è stata spostata. Controlla
        l&apos;indirizzo oppure torna alla dashboard.
      </p>
      <div className="mt-8 flex items-center gap-3">
        <Link
          href="/dashboard"
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-semibold transition-colors shadow-sm"
        >
          Vai alla dashboard
        </Link>
        <Link
          href="/"
          className="bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 px-4 py-2 rounded-lg text-sm font-semibold transition-colors"
        >
          Home
        </Link>
      </div>
    </div>
  )
}
