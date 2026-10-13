import type { CreditTransaction } from './api'

const REASONS: Record<CreditTransaction['reason'], string> = {
  signup: 'Crediti di benvenuto',
  grant: 'Ricarica',
  analysis: 'Analisi',
  ask: 'Domanda sui documenti',
  report: 'Rigenerazione report',
  refund: 'Rimborso',
}

export function creditReason(t: CreditTransaction): string {
  if (t.reason === 'grant' && t.delta < 0) return 'Rettifica'
  return REASONS[t.reason] ?? t.reason
}

export function formatCredits(n: number): string {
  return `${n.toLocaleString('it-IT')} ${Math.abs(n) === 1 ? 'credito' : 'crediti'}`
}
