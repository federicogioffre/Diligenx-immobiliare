'use client'

import { Fragment, useEffect, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import {
  api,
  AgentRunRead,
  AnalysisStageEvent,
  AnalysisStreamEvent,
  DealRead,
  DocumentRead,
  MissingDocumentRead,
  OpenQuestionRead,
  CompanyProfileRead,
  Priority,
  RedFlagRead,
  RiskScoreResponse,
  openAnalysisStream,
} from '@/lib/api'
import DealTabs from '@/components/DealTabs'
import UploadZone from '@/components/UploadZone'
import ErrorAlert from '@/components/ui/ErrorAlert'
import Spinner from '@/components/ui/Spinner'
import StatusBadge from '@/components/ui/StatusBadge'

// ── Constants ──────────────────────────────────────────────────────────────

const DOC_STATUS: Record<string, { label: string; cls: string }> = {
  pending:    { label: 'In attesa',    cls: 'bg-slate-100 text-slate-500' },
  processing: { label: 'Elaborazione', cls: 'bg-amber-50 text-amber-600' },
  processed:  { label: 'Completato',   cls: 'bg-emerald-50 text-emerald-600' },
  failed:     { label: 'Errore',       cls: 'bg-red-50 text-red-600' },
}

const STAGE_LABELS: Record<string, string> = {
  intake: 'Intake',
  document_router: 'Classificazione documenti',
  contract_analysis: 'Analisi contratti',
  corporate_governance: 'Governance societaria',
  corporate_intro_extraction: 'Informazioni societarie',
  tax_analysis: 'Analisi fiscale',
  financial_analysis: 'Analisi finanziaria',
  red_flag_aggregation: 'Aggregazione red flag',
  report_generation: 'Generazione report',
}

const TOTAL_STAGES = 9

// ── Types ──────────────────────────────────────────────────────────────────

interface AnalysisSummary {
  clauseCount: number
  redFlagCount: number
  documentCount: number
}

interface StageRow {
  agent_name: string
  label: string
  status: string
  duration_seconds: number | null
  error_message: string | null
}

// ── Stage progress bar ─────────────────────────────────────────────────────

function StageIcon({ status }: { status: string }) {
  if (status === 'running') {
    return <div className="w-3.5 h-3.5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
  }
  if (status === 'completed') {
    return (
      <div className="w-4 h-4 bg-emerald-500 rounded-full flex items-center justify-center">
        <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      </div>
    )
  }
  if (status === 'failed') {
    return (
      <div className="w-4 h-4 bg-red-500 rounded-full flex items-center justify-center">
        <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </div>
    )
  }
  return <div className="w-4 h-4 border-2 border-slate-200 rounded-full" />
}

function AnalysisProgress({ stages, analyzing }: { stages: StageRow[]; analyzing: boolean }) {
  const completedCount = stages.filter((s) => s.status === 'completed').length
  const pct = Math.round((completedCount / TOTAL_STAGES) * 100)
  const incomplete = !analyzing && completedCount < TOTAL_STAGES

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5 mb-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          {analyzing && <div className="w-3.5 h-3.5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />}
          <span className="text-sm font-semibold text-slate-800">
            {analyzing ? 'Analisi in corso…' : incomplete ? 'Analisi incompleta' : 'Pipeline completata'}
          </span>
        </div>
        <span className="text-xs font-medium text-slate-400 tabular-nums">
          {completedCount} / {TOTAL_STAGES}
        </span>
      </div>

      {/* Progress bar */}
      {incomplete && (
        <p role="alert" className="mb-4 text-sm text-amber-800">
          Alcune fasi non sono state completate. I risultati disponibili possono
          includere quelli dell&apos;analisi precedente. Riesegui l&apos;analisi
          prima di considerare aggiornati i rilievi e il report.
        </p>
      )}
      <div className="w-full bg-slate-100 rounded-full h-1.5 mb-5">
        <div
          className="bg-blue-600 h-1.5 rounded-full transition-all duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Stage list */}
      <div className="space-y-3">
        {stages.map((stage, i) => (
          <div key={stage.agent_name} className="flex items-center gap-3">
            <StageIcon status={stage.status} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <span
                  className={`text-sm truncate ${
                    stage.status === 'completed' ? 'text-slate-700' :
                    stage.status === 'running'   ? 'text-blue-700 font-medium' :
                    stage.status === 'failed'    ? 'text-red-600' :
                                                   'text-slate-400'
                  }`}
                >
                  {stage.label}
                </span>
                <div className="flex items-center gap-2 shrink-0">
                  {stage.status === 'running' && (
                    <span className="text-xs text-blue-400 animate-pulse">In esecuzione…</span>
                  )}
                  {stage.duration_seconds != null && stage.status !== 'running' && (
                    <span className="text-xs text-slate-400 tabular-nums">{stage.duration_seconds.toFixed(1)}s</span>
                  )}
                </div>
              </div>
              {stage.error_message && (
                <p className="text-xs text-red-500 mt-0.5 truncate" title={stage.error_message}>
                  {stage.error_message.slice(0, 80)}{stage.error_message.length > 80 ? '…' : ''}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Risk score ─────────────────────────────────────────────────────────────

const RISK_LEVELS: Record<string, { label: string; bg: string; text: string; bar: string; border: string }> = {
  low:      { label: 'Rischio Basso',     bg: 'bg-emerald-50', text: 'text-emerald-700', bar: 'bg-emerald-500', border: 'border-emerald-200' },
  medium:   { label: 'Rischio Medio',     bg: 'bg-amber-50',   text: 'text-amber-700',   bar: 'bg-amber-400',   border: 'border-amber-200' },
  high:     { label: 'Rischio Alto',      bg: 'bg-orange-50',  text: 'text-orange-700',  bar: 'bg-orange-500',  border: 'border-orange-200' },
  critical: { label: 'Rischio Critico',   bg: 'bg-red-50',     text: 'text-red-700',     bar: 'bg-red-500',     border: 'border-red-200' },
}

const SEV_BAR: Record<string, string> = {
  low: 'bg-slate-300', medium: 'bg-amber-400', high: 'bg-orange-500',
}

const SEV_PILL: Record<RedFlagRead['severity'], string> = {
  high:     'bg-orange-50 text-orange-700',
  medium:   'bg-amber-50 text-amber-700',
  low:      'bg-slate-100 text-slate-600',
}

const SEV_LABEL: Record<RedFlagRead['severity'], string> = {
  high: 'Alto', medium: 'Medio', low: 'Basso',
}

const SEV_ORDER: RedFlagRead['severity'][] = ['high', 'medium', 'low']

// Compact severity breakdown of the deal's red flags. Mirrors the workspace
// insights widget visually but is fed from the already-loaded flag list, so
// no extra request is needed.
function RedFlagSeverityWidget({ flags }: { flags: RedFlagRead[] }) {
  const counts: Record<RedFlagRead['severity'], number> = { high: 0, medium: 0, low: 0 }
  for (const f of flags) counts[f.severity] += 1
  const total = flags.length

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5">
      <div className="flex items-baseline justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-800">Red flag per gravità</h3>
        <span className="text-xs text-slate-400 tabular-nums">{total} totali</span>
      </div>
      <div className="space-y-2.5">
        {SEV_ORDER.map((sev) => {
          const count = counts[sev]
          const pct = total === 0 ? 0 : Math.round((count / total) * 100)
          return (
            <div key={sev}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-slate-700">{SEV_LABEL[sev]}</span>
                <span className={`text-xs font-semibold px-2 py-0.5 rounded-md tabular-nums ${SEV_PILL[sev]}`}>
                  {count}
                </span>
              </div>
              <div className="w-full h-1.5 rounded-full bg-slate-100 overflow-hidden">
                <div
                  className={`h-full ${SEV_BAR[sev]} transition-all`}
                  style={{ width: `${Math.max(pct, count > 0 ? 4 : 0)}%` }}
                  aria-label={`${SEV_LABEL[sev]}: ${count} (${pct}%)`}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Follow-up card: open questions + missing documents ───────────────────

const PRIORITY_PILL: Record<Priority, string> = {
  high:   'bg-red-50 text-red-700',
  medium: 'bg-amber-50 text-amber-700',
  low:    'bg-slate-100 text-slate-600',
}

const PRIORITY_LABEL: Record<Priority, string> = {
  high: 'Alta', medium: 'Media', low: 'Bassa',
}

const PRIORITY_BORDER: Record<Priority, string> = {
  high:   'border-l-red-500',
  medium: 'border-l-amber-400',
  low:    'border-l-slate-300',
}

// Truncate so the card stays compact; the report endpoint has the full text.
const FOLLOWUP_PREVIEW_LIMIT = 5

function ReportLanguageSelect({
  deal,
  onChanged,
}: {
  deal: DealRead
  onChanged: (d: DealRead) => void
}) {
  const [saving, setSaving] = useState(false)

  async function handleChange(value: string) {
    setSaving(true)
    try {
      const updated = await api.deals.update(deal.id, {
        report_language: value as 'it' | 'en' | 'auto',
      })
      onChanged(updated)
    } catch {
      /* leave previous value on failure */
    } finally {
      setSaving(false)
    }
  }

  return (
    <label className="flex items-center gap-1.5 text-xs text-slate-500" title="Lingua del report e dell'analisi AI">
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
      </svg>
      <select
        value={deal.report_language ?? 'auto'}
        onChange={(e) => handleChange(e.target.value)}
        disabled={saving}
        className="bg-transparent border border-slate-200 rounded-lg px-1.5 py-1 text-xs text-slate-600 hover:border-slate-300 focus:outline-none focus:border-blue-400 disabled:opacity-50"
      >
        <option value="auto">Auto</option>
        <option value="it">Italiano</option>
        <option value="en">English</option>
      </select>
    </label>
  )
}

function CorporateIntroCard({ profiles }: { profiles: CompanyProfileRead[] }) {
  // Rows we surface in the deal-page summary table — short, scannable.
  // The full per-field detail (Pledge, Business, Duration, ...) is in
  // the generated report. Here we show what an analyst needs at a glance.
  const ROWS: { key: keyof CompanyProfileRead; label: string }[] = [
    { key: 'legal_form',         label: 'Forma' },
    { key: 'registered_office',  label: 'Sede legale' },
    { key: 'corporate_capital',  label: 'Capitale' },
    { key: 'shareholders',       label: 'Soci' },
    { key: 'managing_body',      label: 'Organo amministrativo' },
    { key: 'auditors',           label: 'Sindaci' },
  ]

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5 space-y-5">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-slate-800">Informazioni societarie</h3>
        <span className="text-xs text-slate-400 tabular-nums">
          {profiles.length} societ{profiles.length === 1 ? 'à' : 'à'}
        </span>
      </div>

      <div className="space-y-5">
        {profiles.map((p) => (
          <div key={p.id} className="rounded-xl border border-slate-100 bg-slate-50/40 p-4">
            <div className="flex items-baseline justify-between mb-3 gap-2">
              <h4 className="text-sm font-semibold text-slate-900 truncate">
                {p.company_name}
              </h4>
              {p.confidence != null && (
                <span className="text-[11px] text-slate-400 tabular-nums shrink-0">
                  Confidenza {(p.confidence * 100).toFixed(0)}%
                </span>
              )}
            </div>
            <dl className="grid grid-cols-1 sm:grid-cols-[8rem_1fr] gap-x-4 gap-y-2 text-sm">
              {ROWS.map(({ key, label }) => {
                const value = p[key]
                if (!value || typeof value !== 'string') return null
                return (
                  <Fragment key={String(key)}>
                    <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
                    <dd className="text-slate-700 whitespace-pre-wrap">{value}</dd>
                  </Fragment>
                )
              })}
            </dl>
          </div>
        ))}
      </div>
    </div>
  )
}

function FollowUpCard({
  questions,
  missing,
}: {
  questions: OpenQuestionRead[]
  missing: MissingDocumentRead[]
}) {
  const totalQ = questions.length
  const totalM = missing.length
  const visibleQ = questions.slice(0, FOLLOWUP_PREVIEW_LIMIT)
  const visibleM = missing.slice(0, FOLLOWUP_PREVIEW_LIMIT)

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5 space-y-5">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-slate-800">Da seguire</h3>
        <span className="text-xs text-slate-400 tabular-nums">
          {totalQ + totalM} elemento{totalQ + totalM === 1 ? '' : 'i'}
        </span>
      </div>

      {totalQ > 0 && (
        <FollowUpSection
          title="Domande aperte"
          subtitle={`${totalQ} sollevate dalla pipeline`}
          items={visibleQ}
          renderItem={(q) => (
            <FollowUpRow
              key={q.id}
              priority={q.priority}
              title={q.question}
            />
          )}
          extra={totalQ - visibleQ.length}
        />
      )}

      {totalM > 0 && (
        <FollowUpSection
          title="Documenti mancanti"
          subtitle={`${totalM} categori${totalM === 1 ? 'a non fornita' : 'e non fornite'}`}
          items={visibleM}
          renderItem={(m) => (
            <FollowUpRow
              key={m.id}
              priority={m.priority}
              title={m.expected_item}
              subtitle={m.reason}
            />
          )}
          extra={totalM - visibleM.length}
        />
      )}
    </div>
  )
}

function FollowUpSection<T>({
  title,
  subtitle,
  items,
  renderItem,
  extra,
}: {
  title: string
  subtitle: string
  items: T[]
  renderItem: (item: T) => React.ReactNode
  extra: number
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-2.5">
        <span className="text-xs font-semibold text-slate-700 uppercase tracking-wide">
          {title}
        </span>
        <span className="text-xs text-slate-400">{subtitle}</span>
      </div>
      <div className="space-y-2">
        {items.map(renderItem)}
        {extra > 0 && (
          <p className="text-xs text-slate-400 pl-3">
            …e altr{extra === 1 ? 'o 1' : `i ${extra}`} non mostrat{extra === 1 ? 'o' : 'i'}.
          </p>
        )}
      </div>
    </div>
  )
}

function FollowUpRow({
  priority,
  title,
  subtitle,
}: {
  priority: Priority
  title: string
  subtitle?: string
}) {
  return (
    <div className={`border-l-2 ${PRIORITY_BORDER[priority]} pl-3 py-1`}>
      <div className="flex items-start justify-between gap-2 mb-0.5">
        <p className="text-sm text-slate-800 leading-snug">{title}</p>
        <span className={`shrink-0 text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wide ${PRIORITY_PILL[priority]}`}>
          {PRIORITY_LABEL[priority]}
        </span>
      </div>
      {subtitle && <p className="text-xs text-slate-500 leading-snug">{subtitle}</p>}
    </div>
  )
}

function RiskScoreWidget({ rs }: { rs: RiskScoreResponse }) {
  const lvl = RISK_LEVELS[rs.risk_level] ?? RISK_LEVELS.medium
  const totalDeductions = rs.deductions.red_flags.impact + rs.deductions.observations.impact +
    rs.deductions.information_requests.impact + rs.deductions.missing_documents.impact

  return (
    <div className={`${lvl.bg} border ${lvl.border} rounded-2xl p-5 mb-4`}>
      <div className="flex items-start gap-5">
        {/* Score circle */}
        <div className="text-center shrink-0">
          <div className={`text-4xl font-bold tabular-nums ${lvl.text}`}>{rs.score}</div>
          <div className="text-xs text-slate-400 mt-0.5 font-medium">/ 100</div>
        </div>

        {/* Bar + deductions */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-1.5">
            <span className={`text-sm font-bold ${lvl.text}`}>{lvl.label}</span>
            {totalDeductions > 0 && (
              <span className="text-xs text-slate-500">−{totalDeductions} pt</span>
            )}
          </div>
          <div className="w-full bg-white/60 rounded-full h-2 mb-3">
            <div className={`${lvl.bar} h-2 rounded-full transition-all duration-700`} style={{ width: `${rs.score}%` }} />
          </div>

          {/* Deduction pills */}
          <div className="flex flex-wrap gap-1.5">
            {rs.deductions.red_flags.count > 0 && (
              <span className="text-xs px-2 py-0.5 bg-red-100 text-red-700 rounded-full font-medium">
                {rs.deductions.red_flags.count} red flag
              </span>
            )}
            {rs.deductions.observations.count > 0 && (
              <span className="text-xs px-2 py-0.5 bg-amber-100 text-amber-700 rounded-full font-medium">
                {rs.deductions.observations.count} osservazioni
              </span>
            )}
            {rs.deductions.information_requests.count > 0 && (
              <span className="text-xs px-2 py-0.5 bg-blue-100 text-blue-700 rounded-full font-medium">
                {rs.deductions.information_requests.count} richieste
              </span>
            )}
            {rs.deductions.missing_documents.count > 0 && (
              <span className="text-xs px-2 py-0.5 bg-slate-200 text-slate-600 rounded-full font-medium">
                {rs.deductions.missing_documents.count} doc mancanti
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Category breakdown */}
      {rs.categories.length > 0 && (
        <div className="mt-4 pt-4 border-t border-white/50 space-y-2">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Rischio per categoria</p>
          {rs.categories.map((cat) => (
            <div key={cat.category} className="flex items-center gap-2.5 text-xs">
              <span className={`w-2 h-2 rounded-full shrink-0 ${SEV_BAR[cat.max_severity] ?? 'bg-slate-300'}`} />
              <span className="flex-1 text-slate-700 capitalize">{cat.category.replace(/_/g, ' ')}</span>
              <span className="text-slate-400">{cat.count} flag</span>
              <span className={`font-semibold ${lvl.text}`}>−{cat.impact}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────

export default function DealPage() {
  const params = useParams()
  const dealId = Number(params.id)

  const [deal, setDeal]           = useState<DealRead | null>(null)
  const [docs, setDocs]           = useState<DocumentRead[]>([])
  const [agentRuns, setAgentRuns] = useState<AgentRunRead[]>([])
  const [summary, setSummary]     = useState<AnalysisSummary | null>(null)
  const [riskScore, setRiskScore] = useState<RiskScoreResponse | null>(null)
  const [redFlags, setRedFlags]   = useState<RedFlagRead[]>([])
  const [openQuestions, setOpenQuestions]       = useState<OpenQuestionRead[]>([])
  const [missingDocs, setMissingDocs]           = useState<MissingDocumentRead[]>([])
  const [companyProfiles, setCompanyProfiles]   = useState<CompanyProfileRead[]>([])
  const [streamStages, setStreamStages] = useState<AnalysisStageEvent[]>([])

  const [analyzing, setAnalyzing]   = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [error, setError]           = useState('')

  const docPollRef      = useRef<ReturnType<typeof setInterval> | null>(null)
  const analysisPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const sseCleanupRef   = useRef<(() => void) | null>(null)

  useEffect(() => {
    // Auth guard is enforced by middleware.ts; 401s redirect automatically.
    fetchAll()
    return () => {
      if (docPollRef.current)      clearInterval(docPollRef.current)
      if (analysisPollRef.current) clearInterval(analysisPollRef.current)
      if (sseCleanupRef.current)   sseCleanupRef.current()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dealId])

  async function fetchAll() {
    try {
      const [d, docList, runs] = await Promise.all([
        api.deals.get(dealId),
        api.documents.list(dealId),
        api.deals.agentRuns(dealId),
      ])
      setDeal(d); setDocs(docList); setAgentRuns(runs)
      scheduleDocPoll(docList)
      if (d.status === 'analyzing') { setAnalyzing(true); startAnalysisStream() }
      if (d.status === 'reviewed' || d.status === 'closed') {
        try { setRiskScore(await api.deals.getRiskScore(dealId)) } catch { /* ok */ }
        try { setRedFlags(await api.deals.redFlags(dealId)) } catch { /* ok */ }
        try { setOpenQuestions(await api.deals.openQuestions(dealId)) } catch { /* ok */ }
        try { setMissingDocs(await api.deals.missingDocuments(dealId)) } catch { /* ok */ }
        try { setCompanyProfiles(await api.deals.companyProfiles(dealId)) } catch { /* ok */ }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Errore nel caricamento')
    }
  }

  function scheduleDocPoll(docList: DocumentRead[]) {
    if (docPollRef.current) clearInterval(docPollRef.current)
    if (!docList.some((d) => d.status === 'pending' || d.status === 'processing')) return
    docPollRef.current = setInterval(async () => {
      const fresh = await api.documents.list(dealId)
      setDocs(fresh)
      if (!fresh.some((d) => d.status === 'pending' || d.status === 'processing')) {
        clearInterval(docPollRef.current!)
      }
    }, 3000)
  }

  async function onAnalysisComplete() {
    if (sseCleanupRef.current)   { sseCleanupRef.current(); sseCleanupRef.current = null }
    if (analysisPollRef.current) { clearInterval(analysisPollRef.current); analysisPollRef.current = null }
    setAnalyzing(false)
    try {
      const [d, runs, clauses, flags, score, questions, missing, profiles] = await Promise.all([
        api.deals.get(dealId),
        api.deals.agentRuns(dealId),
        api.deals.clauseFindings(dealId),
        api.deals.redFlags(dealId),
        api.deals.getRiskScore(dealId).catch(() => null),
        api.deals.openQuestions(dealId).catch(() => [] as OpenQuestionRead[]),
        api.deals.missingDocuments(dealId).catch(() => [] as MissingDocumentRead[]),
        api.deals.companyProfiles(dealId).catch(() => [] as CompanyProfileRead[]),
      ])
      setDeal(d); setAgentRuns(runs); setRedFlags(flags)
      setOpenQuestions(questions); setMissingDocs(missing); setCompanyProfiles(profiles)
      if (score) setRiskScore(score)
      setSummary({ clauseCount: clauses.length, redFlagCount: flags.length, documentCount: docs.filter((d) => d.status === 'processed').length })
    } catch { /* best-effort */ }
  }

  function startAnalysisStream() {
    if (sseCleanupRef.current) { sseCleanupRef.current(); sseCleanupRef.current = null }
    sseCleanupRef.current = openAnalysisStream(
      dealId,
      (payload: AnalysisStreamEvent) => {
        setStreamStages(payload.stages)
        if (payload.deal_status !== 'analyzing') onAnalysisComplete()
      },
      () => onAnalysisComplete(),
      () => startAnalysisPoll(),
    )
  }

  function startAnalysisPoll() {
    if (analysisPollRef.current) clearInterval(analysisPollRef.current)
    analysisPollRef.current = setInterval(async () => {
      try {
        const [d, runs] = await Promise.all([api.deals.get(dealId), api.deals.agentRuns(dealId)])
        setDeal(d); setAgentRuns(runs)
        if (d.status !== 'analyzing') { clearInterval(analysisPollRef.current!); onAnalysisComplete() }
      } catch { /* keep polling */ }
    }, 8000)
  }

  /**
   * Refresh the documents list after the UploadZone component reports
   * a successful upload. Called per file, not per batch.
   * scheduleDocPoll kicks off status polling (pending → processed).
   */
  async function handleUploaded() {
    const fresh = await api.documents.list(dealId)
    setDocs(fresh)
    scheduleDocPoll(fresh)
  }

  async function handleDelete(docId: number, filename: string) {
    if (!confirm(`Eliminare "${filename}"?`)) return
    setDeletingId(docId)
    try {
      await api.documents.delete(docId)
      const fresh = await api.documents.list(dealId)
      setDocs(fresh); scheduleDocPoll(fresh)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Eliminazione fallita')
    } finally { setDeletingId(null) }
  }

  async function handleAnalyze() {
    setAnalyzing(true); setError(''); setSummary(null); setRiskScore(null); setStreamStages([])
    try {
      await api.deals.analyze(dealId)
      const d = await api.deals.get(dealId)
      setDeal(d); startAnalysisStream()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Analisi fallita')
      setAnalyzing(false)
    }
  }

  function fmtSize(bytes: number) {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  function buildStageRows(): StageRow[] {
    const STAGE_ORDER = Object.keys(STAGE_LABELS)
    if (analyzing && streamStages.length > 0) {
      return streamStages.map((s) => ({
        agent_name: s.agent_name, label: STAGE_LABELS[s.agent_name] ?? s.agent_name,
        status: s.status, duration_seconds: s.duration_seconds, error_message: s.error_message,
      }))
    }
    if (agentRuns.length > 0) {
      const runByName = Object.fromEntries(agentRuns.map((r) => [r.agent_name, r]))
      return STAGE_ORDER.map((name) => {
        const run = runByName[name]
        return run
          ? { agent_name: name, label: STAGE_LABELS[name] ?? name, status: run.status, duration_seconds: run.duration_seconds, error_message: run.error_message }
          : { agent_name: name, label: STAGE_LABELS[name] ?? name, status: 'pending', duration_seconds: null, error_message: null }
      })
    }
    return []
  }

  if (!deal) {
    return error
      ? <ErrorAlert error={error} />
      : (
        <div className="flex items-center gap-2 text-slate-500 text-sm">
          <Spinner />
          Caricamento…
        </div>
      )
  }

  const stageRows = buildStageRows()
  const showProgress = analyzing || agentRuns.length > 0
  const processedCount = docs.filter((d) => d.status === 'processed').length

  return (
    <div>
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-slate-400 mb-4">
        <Link href="/dashboard" className="hover:text-slate-600 transition-colors">Dashboard</Link>
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        <span className="text-slate-600 font-medium truncate">{deal.title}</span>
      </div>

      {/* Deal header */}
      <div className="flex items-start justify-between mb-2">
        <h1 className="text-xl font-bold text-slate-900 leading-tight">{deal.title}</h1>
        <div className="shrink-0 ml-3 flex items-center gap-2">
          <ReportLanguageSelect deal={deal} onChanged={(d) => setDeal(d)} />
          <StatusBadge status={deal.status} />
        </div>
      </div>
      {deal.description && <p className="text-sm text-slate-500 mb-5">{deal.description}</p>}

      <DealTabs dealId={dealId} />

      {/* Documents section */}
      <section className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-slate-800">Documenti</h2>
          <span className="text-xs text-slate-400">{docs.length} totali · {processedCount} elaborati</span>
        </div>

        <UploadZone
          dealId={dealId}
          existingNames={docs.map((d) => d.filename)}
          onUploaded={handleUploaded}
        />

        {docs.length === 0 ? (
          <div className="text-center py-10 bg-white rounded-2xl border border-slate-200 border-dashed">
            <svg className="w-8 h-8 text-slate-300 mx-auto mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <p className="text-sm text-slate-400">Nessun documento. Carica un PDF, DOCX o TXT.</p>
          </div>
        ) : (
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Documento</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Stato</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Lingua</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Dim.</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Pag.</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {docs.map((doc) => {
                  const ds = DOC_STATUS[doc.status] ?? { label: doc.status, cls: 'bg-slate-100 text-slate-500' }
                  return (
                    <tr key={doc.id} className="hover:bg-slate-50 transition-colors">
                      <td className="px-4 py-3 font-medium text-slate-800 max-w-xs truncate" title={doc.filename}>
                        {doc.filename}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full ${ds.cls}`}>
                          {doc.status === 'processing' && (
                            <span className="w-1.5 h-1.5 bg-amber-400 rounded-full animate-pulse" />
                          )}
                          {ds.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-500 uppercase text-xs font-medium">{doc.language ?? '—'}</td>
                      <td className="px-4 py-3 text-slate-400 text-xs">{fmtSize(doc.file_size)}</td>
                      <td className="px-4 py-3 text-slate-400 text-xs">{doc.page_count ?? '—'}</td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => handleDelete(doc.id, doc.filename)}
                          disabled={deletingId === doc.id}
                          className="text-slate-300 hover:text-red-500 transition-colors disabled:opacity-40"
                          title="Elimina documento"
                        >
                          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Analysis section */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-slate-800">Analisi AI</h2>
          <button
            onClick={handleAnalyze}
            disabled={analyzing || processedCount === 0}
            className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-50 transition-colors shadow-sm"
          >
            {analyzing ? (
              <>
                <Spinner size="sm" tone="white" />
                In corso…
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                Avvia Analisi
              </>
            )}
          </button>
        </div>

        <ErrorAlert error={error} className="mb-4" />

        {!showProgress && !analyzing && processedCount === 0 && (
          <div className="text-center py-10 bg-white rounded-2xl border border-slate-200 border-dashed">
            <svg className="w-8 h-8 text-slate-300 mx-auto mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            <p className="text-sm text-slate-400">Carica e attendi l&apos;elaborazione dei documenti per avviare l&apos;analisi.</p>
          </div>
        )}

        {showProgress && <AnalysisProgress stages={stageRows} analyzing={analyzing} />}

        {riskScore && <RiskScoreWidget rs={riskScore} />}

        {summary && (
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: 'Documenti',  value: summary.documentCount, icon: '📄', color: 'text-slate-700' },
              { label: 'Clausole',   value: summary.clauseCount,   icon: '📋', color: 'text-blue-700' },
              { label: 'Red Flags',  value: summary.redFlagCount,  icon: '⚑',  color: 'text-red-600' },
            ].map(({ label, value, icon, color }) => (
              <div key={label} className="bg-white rounded-2xl border border-slate-200 shadow-sm p-4 text-center">
                <div className={`text-2xl font-bold tabular-nums ${color}`}>{value}</div>
                <div className="text-xs text-slate-400 mt-1 font-medium">{label}</div>
              </div>
            ))}
          </div>
        )}

        {summary && redFlags.length > 0 && <RedFlagSeverityWidget flags={redFlags} />}

        {summary && companyProfiles.length > 0 && (
          <CorporateIntroCard profiles={companyProfiles} />
        )}

        {summary && (openQuestions.length > 0 || missingDocs.length > 0) && (
          <FollowUpCard questions={openQuestions} missing={missingDocs} />
        )}

        {/* Quick links after analysis */}
        {(deal.status === 'reviewed' || deal.status === 'closed') && (
          <div className="flex gap-3 mt-4">
            <Link
              href={`/deals/${dealId}/findings`}
              className="flex-1 flex items-center justify-center gap-2 bg-white hover:bg-slate-50 border border-slate-200 hover:border-slate-300 text-slate-700 py-2.5 rounded-xl text-sm font-medium transition-colors"
            >
              <svg className="w-4 h-4 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              Vedi Findings
            </Link>
            <Link
              href={`/deals/${dealId}/report`}
              className="flex-1 flex items-center justify-center gap-2 bg-white hover:bg-slate-50 border border-slate-200 hover:border-slate-300 text-slate-700 py-2.5 rounded-xl text-sm font-medium transition-colors"
            >
              <svg className="w-4 h-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Vedi Report
            </Link>
          </div>
        )}
      </section>
    </div>
  )
}
