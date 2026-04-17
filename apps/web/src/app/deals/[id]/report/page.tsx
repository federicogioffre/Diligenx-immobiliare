'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import ReactMarkdown from 'react-markdown'
import { api } from '@/lib/api'
import DealTabs from '@/components/DealTabs'

export default function ReportPage() {
  const params = useParams()
  const dealId = Number(params.id)

  const [markdown, setMarkdown] = useState<string | null>(null)
  const [loading, setLoading]   = useState(true)
  const [generating, setGenerating] = useState(false)
  const [error, setError]       = useState('')

  useEffect(() => {
    // Auth guard is enforced by middleware.ts; 401s redirect automatically.
    fetchReport()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dealId])

  async function fetchReport() {
    setLoading(true); setError('')
    try {
      const data = await api.deals.getReport(dealId)
      setMarkdown(data.markdown)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Errore'
      if (msg.includes('404') || msg.includes('No report')) {
        setMarkdown(null)
      } else {
        setError(msg)
      }
    } finally {
      setLoading(false)
    }
  }

  async function handleGenerate() {
    setGenerating(true); setError('')
    try {
      const data = await api.deals.generateReport(dealId)
      setMarkdown(data.markdown)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Generazione fallita')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div>
      <DealTabs dealId={dealId} />

      {/* Toolbar */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Report di Due Diligence</h2>
          {markdown && <p className="text-xs text-slate-400 mt-0.5">Generato automaticamente dall&apos;AI</p>}
        </div>
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-50 transition-colors shadow-sm"
        >
          {generating ? (
            <>
              <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
              Generazione…
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              {markdown ? 'Rigenera' : 'Genera Report'}
            </>
          )}
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-4 py-3 mb-4">
          <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-slate-500 text-sm">
          <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
          Caricamento…
        </div>
      )}

      {!loading && markdown == null && !error && !generating && (
        <div className="text-center py-20 bg-white rounded-2xl border border-slate-200 border-dashed">
          <div className="inline-flex items-center justify-center w-12 h-12 bg-slate-100 rounded-xl mb-4">
            <svg className="w-6 h-6 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
          <p className="text-slate-600 font-medium mb-1">Nessun report generato</p>
          <p className="text-slate-400 text-sm">Esegui prima l&apos;analisi, poi clicca &quot;Genera Report&quot;</p>
        </div>
      )}

      {markdown && (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm">
          <div className="px-8 py-6 prose prose-slate prose-sm max-w-none
            prose-headings:font-semibold prose-headings:text-slate-900
            prose-h1:text-xl prose-h2:text-base prose-h3:text-sm
            prose-p:text-slate-600 prose-p:leading-relaxed
            prose-li:text-slate-600
            prose-strong:text-slate-800
            prose-table:border prose-table:border-slate-200
            prose-th:bg-slate-50 prose-th:text-slate-600 prose-th:font-semibold
            prose-td:border prose-td:border-slate-100
            prose-hr:border-slate-100
            prose-code:text-blue-600 prose-code:bg-blue-50 prose-code:rounded prose-code:px-1"
          >
            <ReactMarkdown>{markdown}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  )
}
