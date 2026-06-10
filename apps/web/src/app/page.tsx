'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { isLoggedIn } from '@/lib/auth'

/**
 * Public landing page.
 *
 * Lives inside the root layout's constrained ``<main>``; the wrapper div
 * uses ``w-screen + translate`` to escape the 6xl constraint so background
 * sections can run edge-to-edge. The NavBar component hides itself on this
 * path (see NavBar.tsx).
 */
export default function LandingPage() {
  const [authed, setAuthed] = useState(false)

  useEffect(() => {
    setAuthed(isLoggedIn())
  }, [])

  const primaryCta = authed
    ? { href: '/dashboard', label: 'Vai alla dashboard' }
    : { href: '/login', label: 'Inizia gratis' }

  return (
    <div className="relative left-1/2 -translate-x-1/2 w-screen -mt-8 -mb-8 bg-white">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-30 bg-white/80 backdrop-blur border-b border-slate-200">
        <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2.5 group">
            <div className="w-7 h-7 bg-blue-600 rounded-lg flex items-center justify-center shadow-sm">
              <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <span className="font-semibold text-slate-900 text-sm tracking-tight">Diligenx</span>
          </Link>

          <nav className="flex items-center gap-1">
            <a
              href="#funzioni"
              className="hidden sm:inline-block text-sm font-medium text-slate-600 hover:text-slate-900 px-3 py-1.5 rounded-lg hover:bg-slate-100 transition-colors"
            >
              Funzioni
            </a>
            <a
              href="#come-funziona"
              className="hidden sm:inline-block text-sm font-medium text-slate-600 hover:text-slate-900 px-3 py-1.5 rounded-lg hover:bg-slate-100 transition-colors"
            >
              Come funziona
            </a>
            <Link
              href={primaryCta.href}
              className="text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white px-3.5 py-1.5 rounded-lg transition-colors ml-1"
            >
              {authed ? 'Dashboard' : 'Accedi'}
            </Link>
          </nav>
        </div>
      </header>

      {/* ── Hero ───────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden">
        <div
          className="absolute inset-0 bg-gradient-to-b from-blue-50/60 via-white to-white pointer-events-none"
          aria-hidden
        />
        <div className="relative max-w-6xl mx-auto px-6 pt-20 sm:pt-28 pb-16 sm:pb-24 text-center">
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-blue-700 bg-blue-50 border border-blue-100 px-2.5 py-1 rounded-full">
            <span className="w-1.5 h-1.5 bg-blue-600 rounded-full" aria-hidden />
            Due diligence assistita da AI
          </span>
          <h1 className="mt-6 text-4xl sm:text-5xl lg:text-6xl font-semibold text-slate-900 tracking-tight leading-tight">
            Due diligence in ore,
            <br />
            <span className="text-blue-600">non in settimane.</span>
          </h1>
          <p className="mt-6 text-lg sm:text-xl text-slate-600 max-w-2xl mx-auto leading-relaxed">
            Carica i documenti del deal, l'AI estrae le clausole critiche,
            segnala i red flag e genera un report di due diligence pronto da
            condividere.
          </p>
          <div className="mt-10 flex items-center justify-center gap-3 flex-wrap">
            <Link
              href={primaryCta.href}
              className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-5 py-3 rounded-lg shadow-sm transition-colors"
            >
              {primaryCta.label}
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 7l5 5m0 0l-5 5m5-5H6" />
              </svg>
            </Link>
            <a
              href="#come-funziona"
              className="inline-flex items-center gap-2 bg-white hover:bg-slate-50 text-slate-700 text-sm font-semibold px-5 py-3 rounded-lg border border-slate-200 transition-colors"
            >
              Come funziona
            </a>
          </div>
          <p className="mt-6 text-xs text-slate-500">
            Nessuna carta di credito richiesta · Setup in meno di 5 minuti
          </p>
        </div>
      </section>

      {/* ── Trust strip ────────────────────────────────────────────────── */}
      <section className="border-y border-slate-100 bg-slate-50/50">
        <div className="max-w-6xl mx-auto px-6 py-6 text-center">
          <p className="text-xs uppercase tracking-widest text-slate-500 font-medium">
            Pensato per studi legali, advisor M&amp;A e team di investimento
          </p>
        </div>
      </section>

      {/* ── Features ───────────────────────────────────────────────────── */}
      <section id="funzioni" className="max-w-6xl mx-auto px-6 py-20 sm:py-28">
        <div className="text-center max-w-2xl mx-auto mb-14">
          <h2 className="text-3xl sm:text-4xl font-semibold text-slate-900 tracking-tight">
            Quattro agenti AI lavorano in parallelo sul tuo deal
          </h2>
          <p className="mt-4 text-lg text-slate-600">
            Ogni stadio della pipeline ha un compito specifico e produce
            output strutturati su cui il team può lavorare subito.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          <FeatureCard
            iconColor="bg-blue-50 text-blue-600"
            title="Estrazione clausole"
            description="Termination, indemnification, change of control, governing law e altre clausole tipiche estratte automaticamente con citazione della pagina sorgente."
            icon={
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            }
          />

          <FeatureCard
            iconColor="bg-amber-50 text-amber-600"
            title="Red flag automatici"
            description="Ogni rischio identificato è classificato per severity (low / medium / high / critical) e categoria, con spiegazione e link al documento di origine."
            icon={
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            }
          />

          <FeatureCard
            iconColor="bg-emerald-50 text-emerald-600"
            title="Report due diligence"
            description="Markdown editabile, export PDF e DOCX con branding personalizzabile. Pronto da inoltrare al cliente o al comitato investimenti."
            icon={
              <path strokeLinecap="round" strokeLinejoin="round" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
            }
          />

          <FeatureCard
            iconColor="bg-violet-50 text-violet-600"
            title="Q&A sui documenti"
            description="Fai una domanda sul deal, ricevi una risposta citata. Niente hallucination: la risposta è ancorata ai chunk del documento."
            icon={
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
            }
          />
        </div>
      </section>

      {/* ── How it works ───────────────────────────────────────────────── */}
      <section id="come-funziona" className="bg-slate-50 border-y border-slate-100">
        <div className="max-w-6xl mx-auto px-6 py-20 sm:py-28">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <h2 className="text-3xl sm:text-4xl font-semibold text-slate-900 tracking-tight">
              Tre step per il primo report
            </h2>
            <p className="mt-4 text-lg text-slate-600">
              Dalla creazione del deal al report finale, senza configurazione.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            <Step
              number="01"
              title="Crea il deal"
              description="Apri un workspace, aggiungi un deal e una breve descrizione. Tutto resta privato e isolato per cliente."
            />
            <Step
              number="02"
              title="Carica i documenti"
              description="Drag &amp; drop di PDF, DOCX o TXT — anche scansionati. OCR e parsing automatici, supporto italiano e inglese."
            />
            <Step
              number="03"
              title="Analizza"
              description="Un click avvia la pipeline. Clausole, red flag, missing documents e report sono pronti in qualche minuto."
            />
          </div>
        </div>
      </section>

      {/* ── Final CTA ──────────────────────────────────────────────────── */}
      <section className="max-w-6xl mx-auto px-6 py-20 sm:py-28">
        <div className="relative overflow-hidden rounded-2xl bg-slate-900 text-white px-8 sm:px-12 py-14 sm:py-16 text-center">
          <div
            className="absolute inset-0 opacity-30 pointer-events-none"
            style={{
              backgroundImage:
                'radial-gradient(circle at 30% 20%, rgba(59,130,246,0.45), transparent 50%), radial-gradient(circle at 80% 70%, rgba(99,102,241,0.4), transparent 55%)',
            }}
            aria-hidden
          />
          <div className="relative">
            <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight">
              Inizia il tuo primo deal oggi
            </h2>
            <p className="mt-4 text-lg text-slate-300 max-w-xl mx-auto">
              Crea un account, carica un PDF, vedi cosa estrae l'AI. Senza
              impegno, senza credit card.
            </p>
            <div className="mt-8">
              <Link
                href={primaryCta.href}
                className="inline-flex items-center gap-2 bg-white hover:bg-slate-100 text-slate-900 text-sm font-semibold px-5 py-3 rounded-lg transition-colors"
              >
                {primaryCta.label}
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13 7l5 5m0 0l-5 5m5-5H6" />
                </svg>
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* ── Footer ─────────────────────────────────────────────────────── */}
      <footer className="border-t border-slate-100">
        <div className="max-w-6xl mx-auto px-6 py-8 flex flex-col sm:flex-row items-center justify-between gap-3 text-sm text-slate-500">
          <div className="flex items-center gap-2">
            <div className="w-5 h-5 bg-blue-600 rounded-md flex items-center justify-center">
              <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <span>© {new Date().getFullYear()} Diligenx</span>
          </div>
          <div className="flex items-center gap-4">
            <Link href="/login" className="hover:text-slate-900 transition-colors">
              Accedi
            </Link>
          </div>
        </div>
      </footer>
    </div>
  )
}

// ── Local presentational components ────────────────────────────────────────

function FeatureCard({
  iconColor,
  title,
  description,
  icon,
}: {
  iconColor: string
  title: string
  description: string
  icon: React.ReactNode
}) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-6 hover:shadow-sm transition-shadow">
      <div
        className={`w-10 h-10 rounded-lg flex items-center justify-center ${iconColor}`}
      >
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          {icon}
        </svg>
      </div>
      <h3 className="mt-4 text-base font-semibold text-slate-900">{title}</h3>
      <p className="mt-2 text-sm text-slate-600 leading-relaxed">{description}</p>
    </div>
  )
}

function Step({
  number,
  title,
  description,
}: {
  number: string
  title: string
  description: string
}) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-6">
      <div className="text-xs font-semibold text-blue-600 tracking-widest">
        {number}
      </div>
      <h3 className="mt-3 text-base font-semibold text-slate-900">{title}</h3>
      <p className="mt-2 text-sm text-slate-600 leading-relaxed">{description}</p>
    </div>
  )
}
