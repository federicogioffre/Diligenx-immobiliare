'use client'

import { useEffect, useState } from 'react'
import { api, WorkspaceInsights } from '@/lib/api'
import { getWorkspaceId } from '@/lib/auth'
import EmptyState from '@/components/ui/EmptyState'
import ErrorAlert from '@/components/ui/ErrorAlert'
import Spinner from '@/components/ui/Spinner'

// ── visual maps shared with StatusBadge / SeverityBadge ──────────────────

const STATUS_META: Record<
  keyof WorkspaceInsights['deals_by_status'],
  { label: string; bar: string; pill: string }
> = {
  draft:     { label: 'Bozza',       bar: 'bg-slate-400',   pill: 'bg-slate-100 text-slate-700' },
  analyzing: { label: 'Analisi',     bar: 'bg-amber-400',   pill: 'bg-amber-50 text-amber-700' },
  reviewed:  { label: 'Revisionato', bar: 'bg-emerald-500', pill: 'bg-emerald-50 text-emerald-700' },
  closed:    { label: 'Chiuso',      bar: 'bg-blue-400',    pill: 'bg-blue-50 text-blue-700' },
}

const SEVERITY_META: Record<
  keyof WorkspaceInsights['red_flags_by_severity'],
  { label: string; bar: string; pill: string }
> = {
  high:     { label: 'Alto',    bar: 'bg-orange-500',  pill: 'bg-orange-50 text-orange-700' },
  medium:   { label: 'Medio',   bar: 'bg-amber-400',   pill: 'bg-amber-50 text-amber-700' },
  low:      { label: 'Basso',   bar: 'bg-slate-300',   pill: 'bg-slate-100 text-slate-600' },
}

// Render order is severity-descending so the worst flags sit at the top.
const SEVERITY_ORDER: (keyof typeof SEVERITY_META)[] = ['high', 'medium', 'low']

// Pipeline order is the natural lifecycle of a deal.
const STATUS_ORDER: (keyof typeof STATUS_META)[] = ['draft', 'analyzing', 'reviewed', 'closed']


export default function InsightsPage() {
  const [data, setData] = useState<WorkspaceInsights | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const insights = await api.workspaces.insights(getWorkspaceId())
        if (!cancelled) setData(insights)
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Errore nel caricamento')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-slate-500 text-sm">
        <Spinner />
        Caricamento insights…
      </div>
    )
  }

  if (error || !data) {
    return <ErrorAlert error={error || 'Nessun dato disponibile'} />
  }

  const noDeals = data.deals_total === 0

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-xl font-bold text-slate-900">Insights</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Metriche aggregate sul workspace corrente
        </p>
      </div>

      {noDeals ? (
        <EmptyState
          icon={
            <svg className="w-6 h-6 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 3v18h18M7 14l4-4 4 4 5-5" />
            </svg>
          }
          title="Nessun dato ancora"
          subtitle="Crea un deal e avvia un'analisi per popolare le statistiche"
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          <DealPipelineCard data={data} />
          <RedFlagsBySeverityCard data={data} />
          <TopCategoriesCard data={data} />
          <CompletenessCard data={data} />
        </div>
      )}
    </div>
  )
}


// ── Card: Deal pipeline ──────────────────────────────────────────────────

function DealPipelineCard({ data }: { data: WorkspaceInsights }) {
  const total = data.deals_total
  return (
    <Card title="Pipeline deal" subtitle={`${total} deal${total !== 1 ? 's' : ''} totali`}>
      <div className="space-y-3">
        {STATUS_ORDER.map((s) => {
          const count = data.deals_by_status[s]
          const pct = total === 0 ? 0 : Math.round((count / total) * 100)
          return (
            <BarRow
              key={s}
              label={STATUS_META[s].label}
              count={count}
              pct={pct}
              barClass={STATUS_META[s].bar}
              pillClass={STATUS_META[s].pill}
            />
          )
        })}
      </div>
    </Card>
  )
}


// ── Card: Red flags by severity ──────────────────────────────────────────

function RedFlagsBySeverityCard({ data }: { data: WorkspaceInsights }) {
  const total = data.red_flags_total
  return (
    <Card
      title="Red flag per gravità"
      subtitle={total === 0 ? 'Nessun red flag rilevato' : `${total} red flag totali`}
    >
      {total === 0 ? (
        <p className="text-sm text-slate-400 italic">
          Le analisi completate non hanno prodotto red flag.
        </p>
      ) : (
        <div className="space-y-3">
          {SEVERITY_ORDER.map((sev) => {
            const count = data.red_flags_by_severity[sev]
            const pct = Math.round((count / total) * 100)
            return (
              <BarRow
                key={sev}
                label={SEVERITY_META[sev].label}
                count={count}
                pct={pct}
                barClass={SEVERITY_META[sev].bar}
                pillClass={SEVERITY_META[sev].pill}
              />
            )
          })}
        </div>
      )}
    </Card>
  )
}


// ── Card: Top categories ─────────────────────────────────────────────────

function TopCategoriesCard({ data }: { data: WorkspaceInsights }) {
  const cats = data.top_red_flag_categories
  const max = cats.length > 0 ? cats[0].count : 0
  return (
    <Card
      title="Categorie più frequenti"
      subtitle="Top 5 categorie ricorrenti tra i red flag"
    >
      {cats.length === 0 ? (
        <p className="text-sm text-slate-400 italic">
          Ancora nessuna categoria da mostrare.
        </p>
      ) : (
        <div className="space-y-3">
          {cats.map((c) => {
            const pct = max === 0 ? 0 : Math.round((c.count / max) * 100)
            return (
              <BarRow
                key={c.category}
                label={c.category}
                count={c.count}
                pct={pct}
                barClass="bg-blue-500"
                pillClass="bg-blue-50 text-blue-700"
              />
            )
          })}
        </div>
      )}
    </Card>
  )
}


// ── Card: Document completeness ──────────────────────────────────────────

function CompletenessCard({ data }: { data: WorkspaceInsights }) {
  const analyzed = data.deals_analyzed
  const incomplete = data.deals_with_missing_documents
  const complete = Math.max(0, analyzed - incomplete)
  const pct = analyzed === 0 ? 0 : Math.round((complete / analyzed) * 100)

  return (
    <Card
      title="Completezza documentale"
      subtitle={
        analyzed === 0
          ? 'Nessun deal ancora analizzato'
          : `${complete} su ${analyzed} deal con documentazione completa`
      }
    >
      {analyzed === 0 ? (
        <p className="text-sm text-slate-400 italic">
          Avvia un'analisi per ottenere il check di completezza.
        </p>
      ) : (
        <div>
          <div className="flex items-baseline justify-between mb-3">
            <span className="text-3xl font-semibold text-slate-900 tabular-nums">{pct}%</span>
            <span className="text-xs text-slate-500">
              {incomplete} con documentazione incompleta
            </span>
          </div>
          <div className="w-full h-2.5 rounded-full bg-slate-100 overflow-hidden">
            <div
              className="h-full bg-emerald-500 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}
    </Card>
  )
}


// ── Generic primitives ───────────────────────────────────────────────────

function Card({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
}) {
  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6">
      <div className="mb-5">
        <h2 className="text-base font-semibold text-slate-900">{title}</h2>
        {subtitle && (
          <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>
        )}
      </div>
      {children}
    </div>
  )
}

function BarRow({
  label,
  count,
  pct,
  barClass,
  pillClass,
}: {
  label: string
  count: number
  pct: number
  barClass: string
  pillClass: string
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs font-medium text-slate-700 capitalize">{label}</span>
        <span className={`text-xs font-semibold px-2 py-0.5 rounded-md tabular-nums ${pillClass}`}>
          {count}
        </span>
      </div>
      <div className="w-full h-1.5 rounded-full bg-slate-100 overflow-hidden">
        <div
          className={`h-full ${barClass} transition-all`}
          style={{ width: `${Math.max(pct, count > 0 ? 4 : 0)}%` }}
          aria-label={`${label}: ${count} (${pct}%)`}
        />
      </div>
    </div>
  )
}
