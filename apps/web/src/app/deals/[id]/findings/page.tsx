'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { api, ClauseFindingRead, DocumentRead, RedFlagRead } from '@/lib/api'
import DealTabs from '@/components/DealTabs'

// ── Relevance ──────────────────────────────────────────────────────────────

const RELEVANCE: Record<string, { label: string; cls: string }> = {
  high:   { label: 'Alta',   cls: 'bg-emerald-50 text-emerald-700 border border-emerald-200' },
  medium: { label: 'Media',  cls: 'bg-amber-50 text-amber-700 border border-amber-200' },
  low:    { label: 'Bassa',  cls: 'bg-slate-100 text-slate-500 border border-slate-200' },
}

// ── Severity ───────────────────────────────────────────────────────────────

const SEVERITY: Record<string, { label: string; badge: string; left: string }> = {
  low:      { label: 'BASSO',    badge: 'bg-slate-100 text-slate-600',    left: 'border-l-slate-300' },
  medium:   { label: 'MEDIO',    badge: 'bg-amber-50 text-amber-700',     left: 'border-l-amber-400' },
  high:     { label: 'ALTO',     badge: 'bg-orange-50 text-orange-700',   left: 'border-l-orange-500' },
  critical: { label: 'CRITICO',  badge: 'bg-red-50 text-red-700',         left: 'border-l-red-500' },
}

// ── Expandable text ────────────────────────────────────────────────────────

function ExpandableText({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false)
  const limit = 320
  const needsToggle = text.length > limit

  return (
    <div>
      <p className="text-sm text-slate-600 leading-relaxed whitespace-pre-wrap">
        {needsToggle && !expanded ? text.slice(0, limit) + '…' : text}
      </p>
      {needsToggle && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-1.5 text-xs text-blue-600 hover:text-blue-800 font-medium"
        >
          {expanded ? 'Mostra meno ↑' : 'Mostra tutto ↓'}
        </button>
      )}
    </div>
  )
}

// ── Filter pill ────────────────────────────────────────────────────────────

function FilterPill({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
        active
          ? 'bg-slate-900 text-white'
          : 'bg-white text-slate-500 border border-slate-200 hover:border-slate-300 hover:text-slate-700'
      }`}
    >
      {children}
    </button>
  )
}

// ── Clause card ────────────────────────────────────────────────────────────

function ClauseCard({ c, docMap, index }: { c: ClauseFindingRead; docMap: Map<number, string>; index: number }) {
  const filename = docMap.get(c.document_id)
  const rel = c.relevance_score ? (RELEVANCE[c.relevance_score] ?? RELEVANCE.low) : null

  return (
    <div className="bg-white rounded-2xl border border-slate-200 border-l-4 border-l-blue-500 shadow-sm p-5">
      {/* Header */}
      <div className="flex flex-wrap items-start gap-2 mb-3">
        <span className="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded-full bg-blue-50 text-blue-600 text-xs font-bold">
          {index}
        </span>
        <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold bg-slate-100 text-slate-600">
          {c.clause_type.replace(/_/g, ' ')}
        </span>
        {rel && (
          <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold ${rel.cls}`}>
            {rel.label} rilevanza
          </span>
        )}
      </div>

      <h3 className="text-sm font-semibold text-slate-900 mb-2 leading-snug">{c.title}</h3>
      <ExpandableText text={c.content} />

      {/* Footer */}
      <div className="flex flex-wrap items-center gap-3 mt-3 pt-3 border-t border-slate-100 text-xs text-slate-400">
        {filename
          ? <span className="flex items-center gap-1"><svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>{filename}</span>
          : <span>Doc {c.document_id}</span>
        }
        {c.page_number != null && <span>Pag. {c.page_number}</span>}
        {c.confidence != null && <span>Conf. {(c.confidence * 100).toFixed(0)}%</span>}
        {c.relevance_reason && (
          <span className="ml-auto text-slate-300 italic max-w-xs truncate" title={c.relevance_reason}>
            {c.relevance_reason}
          </span>
        )}
      </div>
    </div>
  )
}

// ── Red flag card ──────────────────────────────────────────────────────────

function RedFlagCard({ f, docMap, index }: { f: RedFlagRead; docMap: Map<number, string>; index: number }) {
  const sev = SEVERITY[f.severity] ?? SEVERITY.medium
  const filename = f.source_document_id != null ? docMap.get(f.source_document_id) : undefined

  return (
    <div className={`bg-white rounded-2xl border border-slate-200 border-l-4 ${sev.left} shadow-sm p-5`}>
      {/* Header */}
      <div className="flex flex-wrap items-start gap-2 mb-3">
        <span className="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded-full bg-slate-100 text-slate-500 text-xs font-bold">
          {index}
        </span>
        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-md text-xs font-bold ${sev.badge}`}>
          {sev.label}
        </span>
        <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-slate-100 text-slate-600">
          {f.category.replace(/_/g, ' ')}
        </span>
      </div>

      <h3 className="text-sm font-semibold text-slate-900 mb-2 leading-snug">{f.title}</h3>
      <ExpandableText text={f.description} />

      {/* Footer */}
      <div className="flex flex-wrap items-center gap-3 mt-3 pt-3 border-t border-slate-100 text-xs text-slate-400">
        {filename && (
          <span className="flex items-center gap-1">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
            {filename}
          </span>
        )}
        {f.confidence != null && <span>Conf. {(f.confidence * 100).toFixed(0)}%</span>}
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────

export default function FindingsPage() {
  const params = useParams()
  const dealId = Number(params.id)

  const [clauses, setClauses] = useState<ClauseFindingRead[]>([])
  const [flags, setFlags]     = useState<RedFlagRead[]>([])
  const [docMap, setDocMap]   = useState<Map<number, string>>(new Map())
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')

  const [clauseFilter, setClauseFilter] = useState<'high' | 'all'>('high')
  const [flagFilter, setFlagFilter]     = useState<'important' | 'all'>('important')

  useEffect(() => {
    // Auth guard is enforced by middleware.ts; 401s redirect automatically.
    Promise.all([api.deals.clauseFindings(dealId), api.deals.redFlags(dealId), api.documents.list(dealId)])
      .then(([c, f, docs]) => {
        setClauses(c); setFlags(f)
        setDocMap(new Map(docs.map((d: DocumentRead) => [d.id, d.filename])))
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Errore'))
      .finally(() => setLoading(false))
  }, [dealId])

  if (loading) return (
    <div>
      <DealTabs dealId={dealId} />
      <div className="flex items-center gap-2 text-slate-500 text-sm">
        <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
        Caricamento…
      </div>
    </div>
  )
  if (error) return (
    <div>
      <DealTabs dealId={dealId} />
      <p className="text-red-600 text-sm">{error}</p>
    </div>
  )

  const visibleClauses = clauseFilter === 'high'
    ? clauses.filter(c => !c.relevance_score || c.relevance_score === 'high')
    : clauses

  const visibleFlags = flagFilter === 'important'
    ? flags.filter(f => f.severity === 'high' || f.severity === 'critical')
    : flags

  return (
    <div>
      <DealTabs dealId={dealId} />

      {/* ── Clause Findings ── */}
      <section className="mb-10">
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Clausole</h2>
            <p className="text-xs text-slate-400 mt-0.5">
              {visibleClauses.length}{visibleClauses.length !== clauses.length ? ` di ${clauses.length}` : ''} clausole
            </p>
          </div>
          <div className="flex gap-1.5 ml-auto">
            <FilterPill active={clauseFilter === 'high'} onClick={() => setClauseFilter('high')}>
              Alta rilevanza
            </FilterPill>
            <FilterPill active={clauseFilter === 'all'} onClick={() => setClauseFilter('all')}>
              Tutte ({clauses.length})
            </FilterPill>
          </div>
        </div>

        {visibleClauses.length === 0 ? (
          <div className="text-center py-10 bg-white rounded-2xl border border-slate-200 border-dashed">
            <svg className="w-8 h-8 text-slate-200 mx-auto mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2" />
            </svg>
            <p className="text-sm text-slate-400">
              {clauses.length === 0
                ? "Nessuna clausola trovata. Esegui prima l'analisi."
                : 'Nessuna clausola ad alta rilevanza. Mostra "Tutte" per vedere le altre.'}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {visibleClauses.map((c, i) => <ClauseCard key={c.id} c={c} docMap={docMap} index={i + 1} />)}
          </div>
        )}
      </section>

      {/* ── Red Flags ── */}
      <section>
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Red Flags</h2>
            <p className="text-xs text-slate-400 mt-0.5">
              {visibleFlags.length}{visibleFlags.length !== flags.length ? ` di ${flags.length}` : ''} segnalazioni
            </p>
          </div>
          <div className="flex gap-1.5 ml-auto">
            <FilterPill active={flagFilter === 'important'} onClick={() => setFlagFilter('important')}>
              High / Critical
            </FilterPill>
            <FilterPill active={flagFilter === 'all'} onClick={() => setFlagFilter('all')}>
              Tutti ({flags.length})
            </FilterPill>
          </div>
        </div>

        {visibleFlags.length === 0 ? (
          <div className="text-center py-10 bg-white rounded-2xl border border-slate-200 border-dashed">
            <svg className="w-8 h-8 text-slate-200 mx-auto mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 21v-4m0 0V5a2 2 0 012-2h6.5l1 1H21l-3 6 3 6h-8.5l-1-1H5a2 2 0 00-2 2zm9-13.5V9" />
            </svg>
            <p className="text-sm text-slate-400">
              {flags.length === 0
                ? 'Nessun red flag identificato.'
                : 'Nessun red flag high/critical. Mostra "Tutti" per vedere i minori.'}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {visibleFlags.map((f, i) => <RedFlagCard key={f.id} f={f} docMap={docMap} index={i + 1} />)}
          </div>
        )}
      </section>
    </div>
  )
}
