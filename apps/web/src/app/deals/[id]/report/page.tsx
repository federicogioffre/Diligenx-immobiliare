'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import DealTabs from '@/components/DealTabs'
import EmptyState from '@/components/ui/EmptyState'
import ErrorAlert from '@/components/ui/ErrorAlert'
import Spinner from '@/components/ui/Spinner'

type DownloadFormat = 'pdf' | 'docx'

// Markdown finding headings end with a [SEVERITY] token (colorized in the
// PDF/DOCX exports); on screen we render it as a colored badge instead.
const SEVERITY_BADGE: Record<string, string> = {
  HIGH: 'bg-orange-100 text-orange-700',
  MEDIUM: 'bg-amber-100 text-amber-700',
  LOW: 'bg-slate-100 text-slate-600',
}

function FindingHeading({ children }: { children?: React.ReactNode }) {
  if (typeof children === 'string') {
    const m = children.match(/^(.*?)\s*\[(HIGH|MEDIUM|LOW)\]\s*$/)
    if (m) {
      return (
        <h4 className="flex items-center gap-2 flex-wrap">
          <span>{m[1]}</span>
          <span
            className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-bold tracking-wide not-prose ${SEVERITY_BADGE[m[2]]}`}
          >
            {m[2]}
          </span>
        </h4>
      )
    }
  }
  return <h4>{children}</h4>
}

export default function ReportPage() {
  const params = useParams()
  const dealId = Number(params.id)

  const [markdown, setMarkdown] = useState<string | null>(null)
  const [loading, setLoading]   = useState(true)
  const [generating, setGenerating] = useState(false)
  const [downloading, setDownloading] = useState<DownloadFormat | null>(null)
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
      toast.success('Report generato')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Generazione fallita')
    } finally {
      setGenerating(false)
    }
  }

  async function handleDownload(format: DownloadFormat) {
    setDownloading(format); setError('')
    try {
      const blob = await api.deals.downloadReport(dealId, format)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `diligenx_report_deal-${dealId}.${format}`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      toast.success(`${format.toUpperCase()} scaricato`)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Download fallito')
    } finally {
      setDownloading(null)
    }
  }

  return (
    <div>
      <DealTabs dealId={dealId} />

      {/* Toolbar */}
      <div className="flex items-center justify-between mb-5 gap-3 flex-wrap">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Report di Due Diligence</h2>
          {markdown && <p className="text-xs text-slate-400 mt-0.5">Generato automaticamente dall&apos;AI</p>}
        </div>
        <div className="flex items-center gap-2">
          {markdown && (
            <>
              <button
                onClick={() => handleDownload('pdf')}
                disabled={downloading !== null || generating}
                className="inline-flex items-center gap-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 hover:border-slate-300 px-3.5 py-2 rounded-lg text-sm font-semibold disabled:opacity-50 transition-colors"
                title="Scarica in formato PDF"
              >
                {downloading === 'pdf' ? (
                  <Spinner size="sm" tone="slate" />
                ) : (
                  <svg className="w-4 h-4 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                )}
                PDF
              </button>
              <button
                onClick={() => handleDownload('docx')}
                disabled={downloading !== null || generating}
                className="inline-flex items-center gap-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 hover:border-slate-300 px-3.5 py-2 rounded-lg text-sm font-semibold disabled:opacity-50 transition-colors"
                title="Scarica in formato Word"
              >
                {downloading === 'docx' ? (
                  <Spinner size="sm" tone="slate" />
                ) : (
                  <svg className="w-4 h-4 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                )}
                DOCX
              </button>
              <div className="w-px h-6 bg-slate-200 mx-1" aria-hidden />
            </>
          )}
          <button
            onClick={handleGenerate}
            disabled={generating || downloading !== null}
            className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-50 transition-colors shadow-sm"
          >
            {generating ? (
              <>
                <Spinner size="sm" tone="white" />
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
      </div>

      <ErrorAlert error={error} className="mb-4" />

      {loading && (
        <div className="flex items-center gap-2 text-slate-500 text-sm">
          <Spinner />
          Caricamento…
        </div>
      )}

      {!loading && markdown == null && !error && !generating && (
        <EmptyState
          title="Nessun report generato"
          subtitle={`Esegui prima l'analisi, poi clicca "Genera Report"`}
        />
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
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{ h4: FindingHeading }}
            >
              {markdown}
            </ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  )
}
