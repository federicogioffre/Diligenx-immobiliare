'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { api, ClauseFindingRead, DocumentRead, RedFlagRead } from '@/lib/api'
import DealTabs from '@/components/DealTabs'
import ErrorAlert from '@/components/ui/ErrorAlert'
import SeverityBadge, {
  severityLeftBorder,
  type Severity,
} from '@/components/ui/SeverityBadge'
import Spinner from '@/components/ui/Spinner'

// ── Relevance ──────────────────────────────────────────────────────────────

const RELEVANCE: Record<string, { label: string; cls: string }> = {
  high:   { label: 'Alta',   cls: 'bg-emerald-50 text-emerald-700 border border-emerald-200' },
  medium: { label: 'Media',  cls: 'bg-amber-50 text-amber-700 border border-amber-200' },
  low:    { label: 'Bassa',  cls: 'bg-slate-100 text-slate-500 border border-slate-200' },
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

// ── Remedy and impact ──────────────────────────────────────────────────────

// Two axes, because the two professions tag a finding differently: the
// remedy is the instrument that answers it (what a law firm's risk memo
// assigns), the impact is what it hits (what a financial adviser's
// key-findings page assigns).

type Remedy = NonNullable<RedFlagRead['remedy_type']>
type Impact = NonNullable<RedFlagRead['impact']>

const REMEDY: Record<Remedy, string> = {
  indemnity: 'Indennizzo',
  warranty: 'Garanzia',
  price_adjustment: 'Prezzo',
  earn_out: 'Earn-out',
  condition_precedent: 'Condizione sospensiva',
  pre_closing_verification: 'Verifica pre-closing',
  post_closing_action: 'Post-closing',
  information_request: 'Informazioni',
}

// Order used for the filter chips: the instruments that change the contract
// come first, the ones that only require an action come last.
const REMEDY_ORDER: Remedy[] = [
  'indemnity',
  'warranty',
  'price_adjustment',
  'earn_out',
  'condition_precedent',
  'pre_closing_verification',
  'post_closing_action',
  'information_request',
]

const IMPACT: Record<Impact, string> = {
  value: 'Valore',
  spa: 'Contratto',
  other: 'Altro',
}

const IMPACT_ORDER: Impact[] = ['value', 'spa', 'other']

/** "Euro 240.000 · es. 2022" — the figures the source document stated. */
function formatFigures(f: RedFlagRead): string | null {
  const payload = f.structured_payload_json
  if (!payload) return null

  const bits: string[] = []
  if (typeof payload.amount_eur === 'number') {
    bits.push('Euro ' + payload.amount_eur.toLocaleString('it-IT', { maximumFractionDigits: 0 }))
  }
  if (payload.fiscal_years?.length) {
    bits.push('es. ' + payload.fiscal_years.join(', '))
  }
  return bits.length ? bits.join(' · ') : null
}

/** Preserve all reviewed sources, including evidence with no verified page. */
function sourceCitations(f: RedFlagRead, docMap: Map<number, string>): { documentId: number; label: string }[] {
  const sources = new Map<number, Set<number>>()
  const payload = f.structured_payload_json as Record<string, unknown> | null
  const add = (documentId: unknown, page: unknown) => {
    if (typeof documentId !== 'number' || !Number.isInteger(documentId) || !docMap.has(documentId)) return
    const pages = sources.get(documentId) ?? new Set<number>()
    if (typeof page === 'number' && Number.isInteger(page) && page > 0) pages.add(page)
    sources.set(documentId, pages)
  }
  if (payload?.grounding_reviewed === true) {
    for (const [key, pageKey] of [['source_pages', 'page'], ['evidence', 'source_page']]) {
      const entries = payload[key]
      if (!Array.isArray(entries)) continue
      for (const entry of entries) {
        if (entry && typeof entry === 'object' && !Array.isArray(entry)) {
          add(entry.source_document_id, entry[pageKey])
        }
      }
    }
  }
  if (!sources.size) add(f.source_document_id, f.source_page)
  return [...sources].sort(([a], [b]) => a - b).map(([id, values]) => {
    const pages = [...values].sort((a, b) => a - b)
    return { documentId: id, label: docMap.get(id)! + (pages.length
      ? `, ${pages.length === 1 ? 'pag.' : 'pagg.'} ${pages.join(', ')}`
      : '') }
  })
}

// ── Filter pill ────────────────────────────────────────────────────────────

function FilterPill({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
        active
          ? 'bg-slate-900 text-white dark:bg-blue-600'
          : 'bg-surface text-slate-500 border border-slate-200 hover:border-slate-300 hover:text-slate-700'
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
    <div className="bg-surface rounded-2xl border border-slate-200 border-l-4 border-l-blue-500 shadow-sm p-5">
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
  const severity = (f.severity ?? 'medium') as Severity
  const citations = sourceCitations(f, docMap)
  const figures = formatFigures(f)

  return (
    <div className={`bg-surface rounded-2xl border border-slate-200 border-l-4 ${severityLeftBorder(severity)} shadow-sm p-5`}>
      {/* Header */}
      <div className="flex flex-wrap items-start gap-2 mb-3">
        <span className="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded-full bg-slate-100 text-slate-500 text-xs font-bold">
          {index}
        </span>
        <SeverityBadge severity={severity} />
        <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-slate-100 text-slate-600">
          {f.category.replace(/_/g, ' ')}
        </span>
        {f.remedy_type && (
          <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-indigo-50 text-indigo-700 border border-indigo-100">
            {REMEDY[f.remedy_type]}
          </span>
        )}
        {f.impact && (
          <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-violet-50 text-violet-700 border border-violet-100">
            {IMPACT[f.impact]}
          </span>
        )}
      </div>

      <h3 className="text-sm font-semibold text-slate-900 mb-2 leading-snug">{f.title}</h3>
      <ExpandableText text={f.issue} />

      {/* Risk / Recommendation — the actionable part of a professional
          red-flag entry. Rendered only when the pipeline produced them. */}
      {f.risk && (
        <div className="mt-2 rounded-lg bg-orange-50/60 border border-orange-100 px-3 py-2">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-orange-700">Rischio</span>
          <p className="text-sm text-slate-700 mt-0.5">{f.risk}</p>
        </div>
      )}
      {f.recommendation && (
        <div className="mt-2 rounded-lg bg-emerald-50/60 border border-emerald-100 px-3 py-2">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-emerald-700">Raccomandazione</span>
          <p className="text-sm text-slate-700 mt-0.5">{f.recommendation}</p>
        </div>
      )}

      {/* Footer */}
      <div className="flex flex-wrap items-center gap-3 mt-3 pt-3 border-t border-slate-100 text-xs text-slate-400">
        {citations.map(({ documentId, label }) => (
          <span key={documentId} className="flex items-center gap-1">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
            {label}
          </span>
        ))}
        {figures && <span className="font-semibold text-slate-500 tabular-nums">{figures}</span>}
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
  // Null means "no filter on this axis". The two are independent, so a
  // lawyer can ask for everything that needs a clause, or everything that
  // an indemnity answers, or both at once.
  const [remedyFilter, setRemedyFilter] = useState<Remedy | null>(null)
  const [impactFilter, setImpactFilter] = useState<Impact | null>(null)

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
        <Spinner />
        Caricamento…
      </div>
    </div>
  )
  if (error) return (
    <div>
      <DealTabs dealId={dealId} />
      <ErrorAlert error={error} />
    </div>
  )

  const visibleClauses = clauseFilter === 'high'
    ? clauses.filter(c => !c.relevance_score || c.relevance_score === 'high')
    : clauses

  // Only offer a chip for a tag that some flag actually carries: a wall of
  // dead filters is worse than none.
  const presentRemedies = REMEDY_ORDER.filter(r => flags.some(f => f.remedy_type === r))
  const presentImpacts = IMPACT_ORDER.filter(i => flags.some(f => f.impact === i))

  const visibleFlags = flags.filter(f => {
    if (flagFilter === 'important' && f.severity !== 'high') return false
    if (remedyFilter && f.remedy_type !== remedyFilter) return false
    if (impactFilter && f.impact !== impactFilter) return false
    return true
  })

  const countBy = (predicate: (f: RedFlagRead) => boolean) =>
    flags.filter(f => (flagFilter === 'important' ? f.severity === 'high' : true) && predicate(f))
      .length

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
          <div className="text-center py-10 bg-surface rounded-2xl border border-slate-200 border-dashed">
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
              Solo Alti
            </FilterPill>
            <FilterPill active={flagFilter === 'all'} onClick={() => setFlagFilter('all')}>
              Tutti ({flags.length})
            </FilterPill>
          </div>
        </div>

        {(presentRemedies.length > 0 || presentImpacts.length > 0) && (
          <div className="flex flex-col gap-2 mb-4">
            {presentRemedies.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400 mr-1">
                  Rimedio
                </span>
                <FilterPill active={remedyFilter === null} onClick={() => setRemedyFilter(null)}>
                  Tutti
                </FilterPill>
                {presentRemedies.map(r => (
                  <FilterPill
                    key={r}
                    active={remedyFilter === r}
                    onClick={() => setRemedyFilter(remedyFilter === r ? null : r)}
                  >
                    {REMEDY[r]} ({countBy(f => f.remedy_type === r)})
                  </FilterPill>
                ))}
              </div>
            )}
            {presentImpacts.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400 mr-1">
                  Impatto
                </span>
                <FilterPill active={impactFilter === null} onClick={() => setImpactFilter(null)}>
                  Tutti
                </FilterPill>
                {presentImpacts.map(i => (
                  <FilterPill
                    key={i}
                    active={impactFilter === i}
                    onClick={() => setImpactFilter(impactFilter === i ? null : i)}
                  >
                    {IMPACT[i]} ({countBy(f => f.impact === i)})
                  </FilterPill>
                ))}
              </div>
            )}
          </div>
        )}

        {visibleFlags.length === 0 ? (
          <div className="text-center py-10 bg-surface rounded-2xl border border-slate-200 border-dashed">
            <svg className="w-8 h-8 text-slate-200 mx-auto mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 21v-4m0 0V5a2 2 0 012-2h6.5l1 1H21l-3 6 3 6h-8.5l-1-1H5a2 2 0 00-2 2zm9-13.5V9" />
            </svg>
            <p className="text-sm text-slate-400">
              {flags.length === 0
                ? 'Nessun red flag identificato.'
                : remedyFilter || impactFilter
                  ? 'Nessun red flag con questi filtri. Rimuovi un filtro per vedere gli altri.'
                  : 'Nessun red flag con severity alta. Mostra "Tutti" per vedere i minori.'}
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
