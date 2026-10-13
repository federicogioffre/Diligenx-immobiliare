'use client'

import { useEffect } from 'react'

// App-wide error boundary. Catches uncaught render/runtime errors in any
// route segment and shows a branded recovery screen instead of a white
// page. `reset()` re-renders the segment; a full reload is offered as a
// fallback for corrupted client state.
export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    // Server logs capture the backend side; this is the only place the
    // client-side stack is visible until a browser-side error tracker
    // (Sentry) is wired in.
    console.error('[diligenx] uncaught error:', error)
  }, [error])

  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="w-12 h-12 bg-red-100 rounded-xl flex items-center justify-center mb-6">
        <svg className="w-6 h-6 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
        </svg>
      </div>
      <h1 className="text-2xl font-semibold text-slate-900">
        Qualcosa è andato storto
      </h1>
      <p className="mt-3 text-sm text-slate-500 max-w-md">
        Si è verificato un errore imprevisto. Riprova: se il problema
        persiste, ricarica la pagina o riprova più tardi.
      </p>
      {error.digest && (
        <p className="mt-2 text-xs text-slate-400 font-mono">
          Codice errore: {error.digest}
        </p>
      )}
      <div className="mt-8 flex items-center gap-3">
        <button
          onClick={reset}
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-semibold transition-colors shadow-sm"
        >
          Riprova
        </button>
        <button
          onClick={() => window.location.reload()}
          className="bg-surface hover:bg-slate-50 text-slate-700 border border-slate-200 px-4 py-2 rounded-lg text-sm font-semibold transition-colors"
        >
          Ricarica la pagina
        </button>
      </div>
    </div>
  )
}
