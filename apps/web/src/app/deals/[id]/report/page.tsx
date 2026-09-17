'use client'

import React, { useEffect, useState } from 'react'
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

// Severity badge classes used to colorize [HIGH]/[MEDIUM]/[LOW] tokens that
// appear inside Key Findings table cells. The token is rendered as an
// inline badge with the colour matching the PDF/DOCX exporters.
const SEVERITY_BADGE: Record<string, string> = {
  HIGH: 'bg-orange-100 text-orange-700',
  MEDIUM: 'bg-amber-100 text-amber-700',
  LOW: 'bg-slate-100 text-slate-600',
}

const SEVERITY_TOKEN_RE = /\[(HIGH|MEDIUM|LOW)\]/

function colorizeSeverityChildren(
  children: React.ReactNode,
): React.ReactNode {
  // Replace every [HIGH]/[MEDIUM]/[LOW] token inside a string node with a
  // styled badge. Other node types pass through unchanged.
  return React.Children.map(children, (child) => {
    if (typeof child !== 'string') return child
    const parts: React.ReactNode[] = []
    let remaining = child
    let m: RegExpExecArray | null
    let i = 0
    while ((m = SEVERITY_TOKEN_RE.exec(remaining))) {
      const before = remaining.slice(0, m.index)
      const level = m[1]
      if (before) parts.push(before)
      parts.push(
        <span
          key={`sev-${i++}`}
          className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wide not-prose ${SEVERITY_BADGE[level]}`}
        >
          {level}
        </span>,
      )
      remaining = remaining.slice(m.index + m[0].length)
    }
    if (remaining) parts.push(remaining)
    return parts.length ? parts : child
  })
}

// Custom td/th that colorizes severity tokens in table cells.
function StyledTd({ children, ...props }: React.HTMLAttributes<HTMLTableCellElement>) {
  return <td {...props}>{colorizeSeverityChildren(children)}</td>
}

export default function ReportPage() {
  const params = useParams()
  const dealId = Number(params.id)

  const [markdown, setMarkdown] = useState<string | null>(null)
  const [loading, setLoading]   = useState(true)
  const [generating, setGenerating] = useState(false)
  const [downloading, setDownloading] = useState<DownloadFormat | null>(null)
  const [error, setError]       = useState('')
  const [analysisIncomplete, setAnalysisIncomplete] = useState(false)
  const [reportFailed, setReportFailed] = useState(false)

  useEffect(() => {
    // Auth guard is enforced by middleware.ts; 401s redirect automatically.
    fetchReport()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dealId])

  async function fetchReport() {
    setLoading(true); setError('')
    try {
      const [runs, deal] = await Promise.all([
        api.deals.agentRuns(dealId), api.deals.get(dealId),
      ])
      setAnalysisIncomplete(deal.status === 'analyzing' || runs.some((run) =>
        run.agent_name !== 'report_generation' && run.status !== 'completed'))
      setReportFailed(runs.some((run) =>
        run.agent_name === 'report_generation' && run.status === 'failed'))
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
      setReportFailed(false)
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
            disabled={loading || analysisIncomplete || generating || downloading !== null}
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
      {(analysisIncomplete || reportFailed) && (
        <p role="alert" className="mb-4 rounded-lg bg-amber-50 p-4 text-sm text-amber-800">
          {analysisIncomplete
            ? 'Analisi incompleta. Riesegui l’analisi prima di generare un nuovo report.'
            : 'L’ultima generazione del report non è stata completata.'}
          {markdown && ' Il report mostrato è la versione precedente conservata.'}
        </p>
      )}

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
            prose-p:text-slate-600 prose-p:leading-relaxed prose-p:text-justify prose-p:hyphens-auto
            prose-li:text-slate-600 prose-li:text-justify prose-li:hyphens-auto
            prose-strong:text-slate-800
            prose-table:border prose-table:border-slate-200 prose-table:table-fixed prose-table:text-xs
            prose-th:bg-slate-50 prose-th:text-slate-600 prose-th:font-semibold prose-th:align-top
            prose-td:border prose-td:border-slate-100 prose-td:align-top prose-td:break-words
            prose-hr:border-slate-100
            prose-code:text-blue-600 prose-code:bg-blue-50 prose-code:rounded prose-code:px-1"
          >
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{ td: StyledTd }}
            >
              {markdown}
            </ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  )
}
