'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { isLoggedIn } from '@/lib/auth'
import Logo from '@/components/brand/Logo'

/**
 * Public landing page.
 *
 * Rendered full-bleed (see MainContainer); the in-app NavBar and footer hide
 * themselves on this path and the page draws its own header and footer.
 */
export default function LandingPage() {
  const [authed, setAuthed] = useState(false)
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    setAuthed(isLoggedIn())
    const onScroll = () => setScrolled(window.scrollY > 12)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  const primaryCta = authed
    ? { href: '/dashboard', label: 'Vai alla dashboard' }
    : { href: '/login', label: 'Inizia gratis' }

  return (
    <div className="bg-white text-slate-900 overflow-x-clip">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <header
        className={`fixed inset-x-0 top-0 z-40 transition-all duration-300 ${
          scrolled ? 'bg-ink/75 backdrop-blur-xl border-b border-white/10' : 'bg-transparent border-b border-transparent'
        }`}
      >
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <Link href="/" className="rounded-lg">
            <Logo tone="dark" />
          </Link>

          <nav className="flex items-center gap-1">
            {[
              { href: '#funzioni', label: 'Funzioni' },
              { href: '#come-funziona', label: 'Come funziona' },
              { href: '#sicurezza', label: 'Sicurezza' },
            ].map((l) => (
              <a
                key={l.href}
                href={l.href}
                className="hidden md:inline-block text-sm font-medium text-slate-300 hover:text-white px-3 py-1.5 rounded-lg transition-colors"
              >
                {l.label}
              </a>
            ))}
            {!authed && (
              <Link
                href="/login"
                className="hidden sm:inline-block text-sm font-medium text-slate-300 hover:text-white px-3 py-1.5 rounded-lg transition-colors"
              >
                Accedi
              </Link>
            )}
            <Link
              href={primaryCta.href}
              className="ml-1 inline-flex items-center gap-1.5 text-sm font-semibold bg-white text-ink hover:bg-slate-100 px-3.5 py-1.5 rounded-lg transition-colors shadow-[0_0_0_1px_rgb(255_255_255/0.1),0_4px_16px_-4px_rgb(129_140_248/0.6)]"
            >
              {authed ? 'Dashboard' : 'Inizia gratis'}
              <Arrow className="w-3.5 h-3.5" />
            </Link>
          </nav>
        </div>
      </header>

      {/* ── Hero ───────────────────────────────────────────────────────── */}
      <section className="relative z-10 isolate flow-root bg-ink text-white">
        <div className="absolute inset-0 bg-grid mask-radial -z-10" aria-hidden />
        <div
          className="absolute -top-40 left-1/2 -translate-x-1/2 w-[1100px] h-[640px] -z-10 opacity-70 blur-3xl"
          style={{
            background:
              'radial-gradient(closest-side at 35% 45%, rgb(74 85 232 / 0.55), transparent), radial-gradient(closest-side at 70% 40%, rgb(139 92 246 / 0.4), transparent), radial-gradient(closest-side at 50% 80%, rgb(56 189 248 / 0.18), transparent)',
          }}
          aria-hidden
        />

        <div className="max-w-6xl mx-auto px-4 sm:px-6 pt-36 sm:pt-44 pb-10 text-center">
          <a
            href="#funzioni"
            className="animate-fade-up inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] pl-1.5 pr-3 py-1 text-xs font-medium text-slate-300 hover:bg-white/[0.08] transition-colors backdrop-blur"
          >
            <span className="rounded-full bg-blue-500/20 text-blue-200 px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ring-blue-400/30">
              Nuovo
            </span>
            Revisione fiscale e finanziaria nella pipeline
            <Arrow className="w-3 h-3 text-slate-400" />
          </a>

          <h1 className="animate-fade-up [animation-delay:80ms] mt-8 text-[2.75rem] leading-[1.05] sm:text-6xl lg:text-[5.25rem] font-semibold tracking-[-0.035em]">
            La due diligence,
            <br />
            <span className="font-display font-normal italic tracking-[-0.01em] text-gradient pr-2">in ore</span>
            <span className="text-slate-400"> — non in settimane.</span>
          </h1>

          <p className="animate-fade-up [animation-delay:160ms] mt-7 text-lg sm:text-xl text-slate-400 max-w-2xl mx-auto leading-relaxed">
            Carica la data room. Agenti AI specializzati leggono contratti, atti
            societari, bilanci e documenti fiscali, segnalano i red flag con la
            citazione della fonte e preparano il report per il cliente.
          </p>

          <div className="animate-fade-up [animation-delay:240ms] mt-10 flex items-center justify-center gap-3 flex-wrap">
            <Link
              href={primaryCta.href}
              className="group inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold px-5 py-3 rounded-xl shadow-glow transition-all"
            >
              {primaryCta.label}
              <Arrow className="w-4 h-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
            <a
              href="#come-funziona"
              className="inline-flex items-center gap-2 bg-white/[0.06] hover:bg-white/[0.1] text-white text-sm font-semibold px-5 py-3 rounded-xl ring-1 ring-inset ring-white/15 transition-colors backdrop-blur"
            >
              Guarda come funziona
            </a>
          </div>

          <ul className="animate-fade-up [animation-delay:320ms] mt-8 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs text-slate-500">
            {['Nessuna carta di credito', 'Provider AI in modalità no-training', 'Solo cookie tecnici'].map((t) => (
              <li key={t} className="inline-flex items-center gap-1.5">
                <Check className="w-3.5 h-3.5 text-blue-400" />
                {t}
              </li>
            ))}
          </ul>
        </div>

        {/* Product preview */}
        <div className="relative z-10 max-w-6xl mx-auto px-4 sm:px-6 -mb-32 sm:-mb-52">
          <div className="animate-fade-up [animation-delay:420ms] relative mx-auto max-w-5xl">
            <div className="absolute -inset-x-10 -top-10 h-1/2 bg-gradient-to-b from-blue-500/25 via-violet-500/10 to-transparent blur-3xl -z-10" aria-hidden />
            <ProductPreview />
          </div>
        </div>
      </section>

      {/* ── Capabilities strip ─────────────────────────────────────────── */}
      <section className="relative">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 pt-44 sm:pt-72 pb-6">
          <p className="text-center text-xs uppercase tracking-[0.2em] text-slate-500 font-medium">
            Pensato per studi legali, advisor M&amp;A e team di investimento
          </p>
          <dl className="mt-8 grid grid-cols-2 md:grid-cols-4 gap-px overflow-hidden rounded-2xl border border-slate-200 bg-slate-200">
            {[
              { k: '9', v: 'fasi di analisi, tracciate una per una' },
              { k: '11', v: 'aree di due diligence nel report' },
              { k: 'IT · EN', v: 'report bilingue, nella lingua dei documenti' },
              { k: 'p. 4', v: 'ogni red flag cita documento e pagina' },
            ].map((s) => (
              <Reveal key={s.k} className="bg-white px-6 py-7">
                <dt className="text-3xl sm:text-4xl font-semibold tracking-[-0.03em] text-slate-900">{s.k}</dt>
                <dd className="mt-2 text-sm text-slate-500 leading-snug">{s.v}</dd>
              </Reveal>
            ))}
          </dl>
        </div>
      </section>

      {/* ── Features (bento) ───────────────────────────────────────────── */}
      <section id="funzioni" className="scroll-mt-20 max-w-6xl mx-auto px-4 sm:px-6 py-24 sm:py-32">
        <SectionHeading
          eyebrow="Funzioni"
          title={<>Un team di specialisti AI, <Serif>al lavoro</Serif> su ogni documento</>}
          subtitle="Ogni fase della pipeline ha un compito preciso e produce output strutturati su cui il team può lavorare subito."
        />

        <div className="mt-16 grid grid-cols-1 md:grid-cols-6 gap-4">
          <BentoCard className="md:col-span-4" eyebrow="Red flag" title="Ogni rischio ancorato alla fonte">
            <p>
              Issue, rischio e raccomandazione per ciascun red flag, con severity,
              area di due diligence e strumento di tutela suggerito. Una revisione
              indipendente verifica le citazioni sul testo: ciò che non trova
              riscontro diventa una domanda aperta, non un finding.
            </p>
            <FlagPreview />
          </BentoCard>

          <BentoCard className="md:col-span-2" eyebrow="Q&A" title="Chiedi alla data room">
            <p>Domande in linguaggio naturale, risposte con le citazioni dei documenti.</p>
            <ChatPreview />
          </BentoCard>

          <BentoCard className="md:col-span-2" eyebrow="Contratti" title="Estrazione clausole" icon={ICONS.doc}>
            <p>
              Change of control, prelazione, non concorrenza, recesso, legge
              applicabile: estratte e verificate sul testo sorgente.
            </p>
          </BentoCard>

          <BentoCard className="md:col-span-2" eyebrow="Fiscale" title="Revisione documentale fiscale" icon={ICONS.scale}>
            <p>
              Avvisi di accertamento, cartelle, crediti d&apos;imposta, transfer
              pricing. Periodi accertabili calcolati per anno d&apos;imposta.
            </p>
          </BentoCard>

          <BentoCard className="md:col-span-2" eyebrow="Finanziario" title="Lettura legale dei bilanci" icon={ICONS.chart}>
            <p>
              Continuità aziendale, perdite ex art. 2446 c.c., covenant, debt-like
              items e garanzie, dalle note integrative e dalle relazioni.
            </p>
          </BentoCard>

          <BentoCard className="md:col-span-3" eyebrow="Societario" title="Informazioni societarie consolidate" icon={ICONS.building}>
            <p>
              Visure, statuti, libri soci e verbali riconciliati in un&apos;unica
              scheda per società: un valore per campo, preso dalla fonte più
              autorevole, e le discordanze tra atti societari segnalate.
            </p>
          </BentoCard>

          <BentoCard className="md:col-span-3" eyebrow="Report" title="Pronto da inviare al cliente" icon={ICONS.report}>
            <p>
              Executive summary, key findings per area, richieste di
              informazioni e appendice documenti. Export in PDF e DOCX.
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              {['Markdown', 'PDF', 'DOCX', 'Italiano', 'English'].map((t) => (
                <span key={t} className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600 ring-1 ring-inset ring-slate-200">
                  {t}
                </span>
              ))}
            </div>
          </BentoCard>
        </div>
      </section>

      {/* ── How it works ───────────────────────────────────────────────── */}
      <section id="come-funziona" className="scroll-mt-16 relative isolate border-y border-slate-200 bg-slate-50/70">
        <div className="absolute inset-0 bg-grid-light mask-fade-b -z-10" aria-hidden />
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-24 sm:py-32">
          <SectionHeading
            eyebrow="Come funziona"
            title={<>Dalla data room al report, <Serif>in tre passi</Serif></>}
            subtitle="Nessuna configurazione: crei l'operazione, carichi i documenti, avvii l'analisi."
          />

          <div className="relative mt-16 grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="hidden md:block absolute top-[2.25rem] left-[16%] right-[16%] h-px bg-gradient-to-r from-transparent via-blue-300 to-transparent" aria-hidden />
            {[
              {
                n: '01',
                t: 'Crea l’operazione',
                d: 'Apri un workspace, indica le società target e, se c’è, carica la LOI. Ogni workspace resta isolato dagli altri.',
              },
              {
                n: '02',
                t: 'Carica la data room',
                d: 'PDF, DOCX o TXT, anche scansionati: OCR, parsing e riconoscimento della lingua sono automatici.',
              },
              {
                n: '03',
                t: 'Avvia l’analisi',
                d: 'Segui le fasi in tempo reale. Clausole, red flag, documenti mancanti e report arrivano al termine.',
              },
            ].map((s) => (
              <Reveal key={s.n} className="relative">
                <div className="h-full rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                  <span className="relative z-10 inline-flex h-12 w-12 items-center justify-center rounded-xl bg-ink font-mono text-sm font-medium text-white shadow-lg ring-4 ring-slate-50">
                    {s.n}
                  </span>
                  <h3 className="mt-5 text-lg font-semibold text-slate-900">{s.t}</h3>
                  <p className="mt-2 text-sm text-slate-600 leading-relaxed">{s.d}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ── Security ───────────────────────────────────────────────────── */}
      <section id="sicurezza" className="scroll-mt-16 max-w-6xl mx-auto px-4 sm:px-6 py-24 sm:py-32">
        <div className="relative isolate overflow-hidden rounded-3xl bg-ink px-6 sm:px-12 py-14 sm:py-16 text-white">
          <div className="absolute inset-0 bg-grid mask-radial opacity-60 -z-10" aria-hidden />
          <div className="absolute -right-24 -top-24 h-80 w-80 rounded-full bg-blue-600/30 blur-3xl -z-10" aria-hidden />
          <div className="grid gap-12 lg:grid-cols-5 lg:items-center">
            <div className="lg:col-span-2">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-300">Sicurezza</p>
              <h2 className="mt-4 text-3xl sm:text-4xl font-semibold tracking-tight">
                Documenti riservati, <Serif className="text-blue-200">trattati come tali</Serif>
              </h2>
              <p className="mt-4 text-slate-400 leading-relaxed">
                La data room di un&apos;operazione è tra i materiali più sensibili
                di uno studio. Diligenx è costruito attorno a questo.
              </p>
              <Link
                href="/security"
                className="mt-8 inline-flex items-center gap-1.5 text-sm font-semibold text-white hover:text-blue-200 transition-colors"
              >
                Leggi la pagina sicurezza <Arrow className="w-4 h-4" />
              </Link>
            </div>
            <div className="lg:col-span-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
              {[
                { t: 'Isolamento per workspace', d: 'Ogni query è filtrata per proprietario, workspace e operazione.', i: ICONS.lock },
                { t: 'Cifratura', d: 'TLS in transito, cifratura at rest presso i provider di storage.', i: ICONS.shield },
                { t: 'AI senza addestramento', d: 'I contenuti inviati ai modelli non vengono usati per addestrarli.', i: ICONS.cpu },
                { t: 'Nessun tracker', d: 'Solo cookie tecnici di sessione. Nessuna profilazione.', i: ICONS.eye },
              ].map((f) => (
                <div key={f.t} className="border-gradient rounded-2xl bg-white/[0.03] p-5">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/[0.06] text-blue-300 ring-1 ring-inset ring-white/10">
                    <Icon d={f.i} className="w-4 h-4" />
                  </div>
                  <h3 className="mt-4 text-sm font-semibold">{f.t}</h3>
                  <p className="mt-1.5 text-sm text-slate-400 leading-relaxed">{f.d}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── Final CTA ──────────────────────────────────────────────────── */}
      <section className="max-w-6xl mx-auto px-4 sm:px-6 pb-24 sm:pb-32">
        <Reveal className="relative isolate overflow-hidden rounded-3xl border border-slate-200 bg-gradient-to-b from-blue-50/80 to-white px-6 sm:px-12 py-16 sm:py-20 text-center">
          <div className="absolute inset-0 bg-grid-light mask-radial -z-10" aria-hidden />
          <h2 className="text-3xl sm:text-5xl font-semibold tracking-tight text-slate-900">
            Il tuo primo report, <Serif className="text-gradient-brand">oggi</Serif>
          </h2>
          <p className="mt-5 text-lg text-slate-600 max-w-xl mx-auto">
            Crea un account, carica un documento e guarda cosa estrae l&apos;AI.
            Senza impegno.
          </p>
          <div className="mt-9 flex items-center justify-center gap-3 flex-wrap">
            <Link
              href={primaryCta.href}
              className="group inline-flex items-center gap-2 bg-ink hover:bg-ink-800 text-white text-sm font-semibold px-5 py-3 rounded-xl shadow-lg transition-colors"
            >
              {primaryCta.label}
              <Arrow className="w-4 h-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
            <Link
              href="/security"
              className="inline-flex items-center gap-2 bg-white hover:bg-slate-50 text-slate-700 text-sm font-semibold px-5 py-3 rounded-xl ring-1 ring-inset ring-slate-200 transition-colors"
            >
              Sicurezza e privacy
            </Link>
          </div>
        </Reveal>
      </section>

      {/* ── Footer ─────────────────────────────────────────────────────── */}
      <footer className="border-t border-slate-200 bg-slate-50/60">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-14 grid gap-10 sm:grid-cols-2 lg:grid-cols-4">
          <div className="lg:col-span-2">
            <Logo />
            <p className="mt-4 max-w-sm text-sm text-slate-500 leading-relaxed">
              Due diligence legale assistita da AI per operazioni di M&amp;A.
              L&apos;output non sostituisce un parere legale.
            </p>
          </div>
          <FooterColumn
            title="Prodotto"
            links={[
              { href: '#funzioni', label: 'Funzioni' },
              { href: '#come-funziona', label: 'Come funziona' },
              { href: '/login', label: 'Accedi' },
            ]}
          />
          <FooterColumn
            title="Legale"
            links={[
              { href: '/privacy', label: 'Privacy' },
              { href: '/cookies', label: 'Cookie' },
              { href: '/terms', label: 'Termini' },
              { href: '/dpa', label: 'DPA' },
              { href: '/security', label: 'Sicurezza' },
            ]}
          />
        </div>
        <div className="border-t border-slate-200">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 text-xs text-slate-500">
            © {new Date().getFullYear()} Diligenx
          </div>
        </div>
      </footer>
    </div>
  )
}

// ── Product mockups (static, illustrative) ─────────────────────────────────

const STAGES: { name: string; state: 'done' | 'running' | 'queued' }[] = [
  { name: 'Intake', state: 'done' },
  { name: 'Classificazione', state: 'done' },
  { name: 'Contratti', state: 'done' },
  { name: 'Societario', state: 'done' },
  { name: 'Fiscale', state: 'done' },
  { name: 'Finanziario', state: 'running' },
  { name: 'Red flag', state: 'queued' },
  { name: 'Report', state: 'queued' },
]

const FINDINGS: { sev: 'ALTO' | 'MEDIO' | 'BASSO'; area: string; text: string; remedy: string; src: string }[] = [
  { sev: 'ALTO', area: 'Contratti', text: 'Change of control: recesso del fornitore principale', remedy: 'Condizione sospensiva', src: 'Supply_Agreement.pdf · p. 12' },
  { sev: 'ALTO', area: 'Fiscale', text: 'Avviso di accertamento IRES notificato, es. 2021', remedy: 'Indennizzo', src: 'Avviso_2021.pdf · p. 1' },
  { sev: 'MEDIO', area: 'Societario', text: 'Clausola di prelazione statutaria sulle quote', remedy: 'Verifica pre-closing', src: 'Statuto.pdf · p. 4' },
  { sev: 'BASSO', area: 'Finanziario', text: 'Leasing operativi non riflessi nella PFN', remedy: 'Aggiustamento prezzo', src: 'Bilancio_2023.pdf · p. 31' },
]

const SEV_CLS = {
  ALTO: 'bg-orange-500/15 text-orange-300 ring-orange-400/25',
  MEDIO: 'bg-amber-400/15 text-amber-200 ring-amber-300/25',
  BASSO: 'bg-white/10 text-slate-300 ring-white/15',
}

function ProductPreview() {
  return (
    <div className="border-gradient rounded-2xl bg-ink-900/80 p-1.5 shadow-2xl shadow-blue-950/50 backdrop-blur" role="img" aria-label="Anteprima dell'interfaccia di Diligenx: fasi dell'analisi e key findings di un'operazione di esempio">
      <div className="overflow-hidden rounded-xl bg-ink-800/90 ring-1 ring-white/5 text-left">
        {/* Window chrome */}
        <div className="flex items-center gap-2 border-b border-white/5 px-4 py-3">
          <span className="h-2.5 w-2.5 rounded-full bg-white/15" />
          <span className="h-2.5 w-2.5 rounded-full bg-white/15" />
          <span className="h-2.5 w-2.5 rounded-full bg-white/15" />
          <div className="mx-auto hidden sm:flex items-center gap-1.5 rounded-md bg-white/[0.04] px-3 py-1 text-[11px] text-slate-500 ring-1 ring-inset ring-white/5">
            <Icon d={ICONS.lock} className="w-3 h-3" /> app.diligenx.it/deals/atlas
          </div>
        </div>

        <div className="grid md:grid-cols-[220px_1fr]">
          {/* Pipeline */}
          <aside className="hidden md:block border-r border-white/5 p-4">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Pipeline</p>
            <ul className="mt-3 space-y-1">
              {STAGES.map((s) => (
                <li
                  key={s.name}
                  className={`flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] ${
                    s.state === 'running' ? 'bg-blue-500/10 text-white ring-1 ring-inset ring-blue-400/20' : s.state === 'done' ? 'text-slate-300' : 'text-slate-600'
                  }`}
                >
                  {s.state === 'done' && (
                    <span className="flex h-4 w-4 items-center justify-center rounded-full bg-emerald-400/15 text-emerald-300">
                      <Check className="w-2.5 h-2.5" />
                    </span>
                  )}
                  {s.state === 'running' && <span className="h-4 w-4 rounded-full border-2 border-blue-400 border-t-transparent animate-spin" />}
                  {s.state === 'queued' && <span className="h-4 w-4 rounded-full border border-dashed border-slate-600" />}
                  {s.name}
                </li>
              ))}
            </ul>
            <div className="mt-5 rounded-lg bg-white/[0.03] p-3 ring-1 ring-inset ring-white/5">
              <div className="flex justify-between text-[11px] text-slate-500">
                <span>Bilanci</span>
                <span className="font-mono text-slate-400">38/52</span>
              </div>
              <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/5">
                <div className="h-full w-[73%] rounded-full bg-gradient-to-r from-blue-500 to-violet-400" />
              </div>
            </div>
          </aside>

          {/* Findings */}
          <div className="p-4 sm:p-6">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="text-[11px] font-medium text-slate-500">Project Atlas · Acquisizione Alfa S.r.l.</p>
                <p className="mt-1 text-base font-semibold text-white">Key Findings</p>
              </div>
              <div className="flex gap-2 text-[11px]">
                <span className="rounded-md bg-orange-500/15 px-2 py-1 font-semibold text-orange-300 ring-1 ring-inset ring-orange-400/25">2 alti</span>
                <span className="rounded-md bg-amber-400/15 px-2 py-1 font-semibold text-amber-200 ring-1 ring-inset ring-amber-300/25">1 medio</span>
                <span className="rounded-md bg-white/10 px-2 py-1 font-semibold text-slate-300 ring-1 ring-inset ring-white/15">1 basso</span>
              </div>
            </div>
            <ul className="mt-5 divide-y divide-white/5 rounded-xl ring-1 ring-inset ring-white/5 bg-white/[0.02]">
              {FINDINGS.map((f) => (
                <li key={f.text} className="grid grid-cols-[auto_1fr] sm:grid-cols-[auto_1fr_auto] items-center gap-x-3 gap-y-1 px-3.5 py-3">
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ring-1 ring-inset ${SEV_CLS[f.sev]}`}>{f.sev}</span>
                  <div className="min-w-0">
                    <p className="truncate text-[13px] text-slate-200">{f.text}</p>
                    <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-slate-500">
                      <span>{f.area}</span>
                      <span className="text-slate-700">·</span>
                      <Icon d={ICONS.link} className="w-3 h-3" />
                      <span className="truncate font-mono">{f.src}</span>
                    </p>
                  </div>
                  <span className="hidden sm:inline-block rounded-md bg-blue-500/10 px-2 py-1 text-[11px] font-medium text-blue-200 ring-1 ring-inset ring-blue-400/20">
                    {f.remedy}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}

function FlagPreview() {
  return (
    <div className="mt-6 rounded-xl border border-slate-200 bg-slate-50/80 p-4 text-sm">
      <div className="flex items-center gap-2">
        <span className="rounded-md bg-orange-50 px-2 py-0.5 text-xs font-bold text-orange-700 ring-1 ring-inset ring-orange-200">ALTO</span>
        <span className="text-xs font-medium text-slate-500">Contratti · Change of control</span>
        <span className="ml-auto hidden sm:inline-flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-200">
          <Check className="w-3 h-3" /> Citazione verificata
        </span>
      </div>
      <blockquote className="mt-3 border-l-2 border-blue-500 pl-3 text-slate-700 leading-relaxed">
        «In caso di mutamento del controllo del Cliente, il Fornitore avrà facoltà di
        <mark className="mx-0.5 rounded bg-blue-100 px-1 text-blue-900">recedere dal Contratto con preavviso di 30 giorni</mark>»
      </blockquote>
      <p className="mt-3 flex items-center gap-1.5 font-mono text-xs text-slate-500">
        <Icon d={ICONS.doc} className="w-3.5 h-3.5" /> Supply_Agreement.pdf · p. 12
      </p>
    </div>
  )
}

function ChatPreview() {
  return (
    <div className="mt-6 space-y-2.5 text-sm">
      <div className="ml-auto w-fit max-w-[90%] rounded-2xl rounded-br-md bg-ink px-3.5 py-2 text-white">
        Ci sono garanzie rilasciate a favore di terzi?
      </div>
      <div className="w-fit max-w-[95%] rounded-2xl rounded-bl-md border border-slate-200 bg-white px-3.5 py-2.5 text-slate-700 shadow-sm">
        Sì, una fideiussione a favore di Banca X per € 1,2 mln.
        <span className="ml-1 inline-flex items-center rounded bg-blue-50 px-1.5 text-[11px] font-semibold text-blue-700 ring-1 ring-inset ring-blue-200">
          [1]
        </span>
        <p className="mt-1.5 font-mono text-[11px] text-slate-400">[1] Nota_integrativa_2023.pdf · p. 18</p>
      </div>
    </div>
  )
}

// ── Local presentational components ────────────────────────────────────────

/**
 * Fades its content in as it scrolls into view, through a CSS scroll-driven
 * animation (`.reveal` in globals.css). Browsers without support, crawlers
 * and visitors without JS simply see the content: nothing starts hidden.
 */
function Reveal({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <div className={`reveal ${className}`}>{children}</div>
}

function SectionHeading({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow: string
  title: React.ReactNode
  subtitle: string
}) {
  return (
    <Reveal className="text-center max-w-3xl mx-auto">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-600">{eyebrow}</p>
      <h2 className="mt-4 text-3xl sm:text-5xl font-semibold text-slate-900 tracking-tight leading-[1.1]">{title}</h2>
      <p className="mt-5 text-lg text-slate-600 leading-relaxed max-w-2xl mx-auto">{subtitle}</p>
    </Reveal>
  )
}

function Serif({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <span className={`font-display font-normal italic tracking-normal ${className}`}>{children}</span>
}

function BentoCard({
  eyebrow,
  title,
  icon,
  className = '',
  children,
}: {
  eyebrow: string
  title: string
  icon?: string
  className?: string
  children: React.ReactNode
}) {
  return (
    <Reveal className={className}>
      <div className="group h-full rounded-2xl border border-slate-200 bg-white p-6 sm:p-7 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:shadow-lg hover:border-slate-300">
        {icon && (
          <div className="mb-5 flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-50 to-violet-50 text-blue-600 ring-1 ring-inset ring-blue-100 transition-transform group-hover:scale-105">
            <Icon d={icon} className="w-5 h-5" />
          </div>
        )}
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">{eyebrow}</p>
        <h3 className="mt-1.5 text-lg font-semibold text-slate-900">{title}</h3>
        <div className="mt-2 text-sm text-slate-600 leading-relaxed">{children}</div>
      </div>
    </Reveal>
  )
}

function FooterColumn({ title, links }: { title: string; links: { href: string; label: string }[] }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-900">{title}</p>
      <ul className="mt-4 space-y-2.5 text-sm">
        {links.map((l) => (
          <li key={l.href}>
            <Link href={l.href} className="text-slate-500 hover:text-slate-900 transition-colors">
              {l.label}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}

const ICONS = {
  doc: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
  scale: 'M12 3v18m-7-4h14M5 7l-3 6a3 3 0 006 0L5 7zm14 0l-3 6a3 3 0 006 0l-3-6zM5 7h14M12 3l-2 2m2-2l2 2',
  chart: 'M3 3v18h18M8 17V11m4 6V7m4 10v-4',
  building: 'M3 21h18M5 21V7l7-4 7 4v14M9 9h1m4 0h1M9 13h1m4 0h1M9 17h1m4 0h1',
  report: 'M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
  lock: 'M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z',
  shield: 'M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z',
  cpu: 'M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z',
  eye: 'M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88',
  link: 'M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1',
}

function Icon({ d, className = 'w-5 h-5' }: { d: string; className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8} aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" d={d} />
    </svg>
  )
}

function Arrow({ className = 'w-4 h-4' }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2} aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14m-6-6l6 6-6 6" />
    </svg>
  )
}

function Check({ className = 'w-4 h-4' }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3} aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  )
}
