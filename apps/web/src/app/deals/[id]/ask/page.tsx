'use client'

import { useState, useEffect, useRef } from 'react'
import { useParams } from 'next/navigation'
import { api, QASource } from '@/lib/api'
import DealTabs from '@/components/DealTabs'
import ErrorAlert from '@/components/ui/ErrorAlert'

interface Message {
  type: 'question' | 'answer'
  text: string
  sources?: QASource[]
}

export default function AskPage() {
  const params = useParams()
  const dealId = Number(params.id)

  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')
  const bottomRef               = useRef<HTMLDivElement>(null)

  // Auth guard is enforced by middleware.ts; 401s redirect automatically.

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleAsk(e: React.FormEvent) {
    e.preventDefault()
    if (!question.trim() || loading) return
    const q = question.trim()
    setQuestion('')
    setError('')
    setMessages((prev) => [...prev, { type: 'question', text: q }])
    setLoading(true)
    try {
      const result = await api.deals.ask(dealId, q)
      setMessages((prev) => [...prev, { type: 'answer', text: result.answer, sources: result.sources }])
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Errore nella risposta')
    } finally {
      setLoading(false)
    }
  }

  const suggestions = [
    "Ci sono ipoteche o pignoramenti sull'immobile?",
    'Chi sono gli intestatari catastali?',
    'Il condominio ha deliberato lavori straordinari?',
  ]

  return (
    <div className="flex flex-col">
      <DealTabs dealId={dealId} />

      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Chiedi ai documenti</h2>
          <p className="text-xs text-slate-400 mt-0.5">Ricerca semantica con risposta generata dall&apos;AI</p>
        </div>
      </div>

      {/* Chat area */}
      <div className="bg-surface rounded-2xl border border-slate-200 shadow-sm min-h-[400px] flex flex-col">
        {/* Messages */}
        <div className="flex-1 p-5 space-y-4 overflow-y-auto scrollbar-thin">
          {messages.length === 0 && !loading && (
            <div className="text-center py-10">
              <div className="inline-flex items-center justify-center w-12 h-12 bg-slate-100 rounded-xl mb-4">
                <svg className="w-6 h-6 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
              </div>
              <p className="text-slate-500 font-medium mb-1 text-sm">Fai una domanda sui documenti</p>
              <p className="text-slate-400 text-xs mb-5">L&apos;AI cercherà nelle clausole e risponderà citando le fonti</p>
              <div className="flex flex-wrap justify-center gap-2">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => setQuestion(s)}
                    className="text-xs bg-slate-50 hover:bg-slate-100 border border-slate-200 text-slate-600 px-3 py-1.5 rounded-lg transition-colors"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i}>
              {msg.type === 'question' ? (
                <div className="flex justify-end">
                  <div className="bg-blue-600 text-white rounded-2xl rounded-tr-sm px-4 py-2.5 max-w-lg text-sm leading-relaxed">
                    {msg.text}
                  </div>
                </div>
              ) : (
                <div className="flex justify-start">
                  <div className="max-w-2xl">
                    <div className="bg-slate-50 border border-slate-200 rounded-2xl rounded-tl-sm px-4 py-3 text-sm text-slate-800 leading-relaxed">
                      {msg.text}
                    </div>
                    {msg.sources && msg.sources.length > 0 && (
                      <div className="mt-2 space-y-1.5">
                        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide px-1">
                          Fonti ({msg.sources.length})
                        </p>
                        {msg.sources.map((src, idx) => (
                          <div key={idx} className="bg-surface border border-slate-200 rounded-xl px-3 py-2">
                            <div className="flex items-center gap-2 text-xs text-slate-400 mb-1">
                              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                              </svg>
                              Doc {src.document_id}
                              {src.page_number != null && <span>· Pag. {src.page_number}</span>}
                            </div>
                            <p className="text-xs text-slate-600 italic leading-relaxed">
                              &ldquo;{src.excerpt}&rdquo;
                            </p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div className="flex justify-start">
              <div className="bg-slate-50 border border-slate-200 rounded-2xl rounded-tl-sm px-4 py-3 flex items-center gap-2">
                <div className="flex gap-1">
                  {[0, 1, 2].map((i) => (
                    <div
                      key={i}
                      className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce"
                      style={{ animationDelay: `${i * 0.15}s` }}
                    />
                  ))}
                </div>
                <span className="text-xs text-slate-400">Ricerca in corso…</span>
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="border-t border-slate-100 p-4">
          <ErrorAlert error={error} className="mb-3" />
          <form onSubmit={handleAsk} className="flex gap-2">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Scrivi una domanda sui documenti del deal…"
              disabled={loading}
              className="flex-1 border border-slate-200 rounded-xl px-4 py-2.5 text-sm text-slate-900 placeholder-slate-400 shadow-sm focus:outline-none focus:ring-4 focus:ring-blue-500/15 focus:border-blue-500 transition-all disabled:opacity-50"
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleAsk(e) } }}
            />
            <button
              type="submit"
              disabled={loading || !question.trim()}
              className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2.5 rounded-xl font-medium disabled:opacity-50 transition-colors flex items-center gap-1.5 text-sm shrink-0"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
              Chiedi
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
