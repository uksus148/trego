import { useEffect, useRef, useState, type FormEvent } from 'react'
import type { ChatMessage } from '../types'

interface ChatPanelProps {
  messages: ChatMessage[]
  history: ChatMessage[][]
  busy: boolean
  editorOpen: boolean
  suggestions: string[]
  onSend: (text: string) => void
}

export function ChatPanel({ messages, history, busy, editorOpen, suggestions, onSend }: ChatPanelProps) {
  const [draft, setDraft] = useState('')
  const endRef = useRef<HTMLDivElement>(null)
  const disabled = busy || editorOpen
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, history, busy])
  const submit = (e?: FormEvent) => {
    e?.preventDefault()
    const text = draft.trim()
    if (!text || disabled) return
    onSend(text)
    setDraft('')
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4">
        {history.map((plan, index) => <section key={index} className="space-y-2 border-b border-line pb-3" aria-label="Original plan, read only">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-stone">Original plan · read only</h3>
          {plan.map((item) => <p key={item.id} className={`max-w-[90%] rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed ${item.role === 'user' ? 'ml-auto bg-ink text-white' : 'bg-white ring-1 ring-line'}`}>{item.text}</p>)}
        </section>)}
        {(editorOpen || history.length > 0) && <p className="rounded-lg bg-moss/10 px-3 py-2 text-xs text-moss">Manual edits are not sent to the assistant. A new message starts a new plan.</p>}
        {messages.length === 0 && <EmptyState suggestions={suggestions} onPick={onSend} disabled={disabled} />}
        {messages.map((m) => <p key={m.id} className={`max-w-[90%] rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed ${m.role === 'user' ? 'ml-auto bg-ink text-white' : 'bg-white ring-1 ring-line'}`}>{m.text}</p>)}
        {busy && <p className="animate-pulse text-sm text-stone">Searching the web for places and views…</p>}
        <div ref={endRef} />
      </div>
      <form onSubmit={submit} className="border-t border-line p-3">
        <div className="flex items-end gap-2 rounded-2xl bg-white p-2 ring-1 ring-line focus-within:ring-moss">
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) submit(e)
          }} rows={2} disabled={disabled} placeholder={editorOpen ? 'Cancel editing to start a new plan.' : 'Where do you want to go, and what do you want to see?'} className="min-h-0 flex-1 resize-none bg-transparent px-2 py-1 text-[15px] outline-none placeholder:text-stone disabled:opacity-50" />
          <button type="submit" disabled={disabled || !draft.trim()} className="rounded-xl bg-trail px-4 py-2 font-medium text-white transition hover:brightness-110 disabled:opacity-40">Go</button>
        </div>
      </form>
    </div>
  )
}

interface EmptyStateProps { suggestions: string[]; onPick: (text: string) => void; disabled: boolean }
function EmptyState({ suggestions, onPick, disabled }: EmptyStateProps) {
  return <div className="space-y-3 pt-2">
    <p className="text-[15px] text-stone">Describe the trip in your own words: where you start, what you want to see, and what you'd rather skip. Paste a TikTok or blog link if you saw a place there.</p>
    <div className="space-y-2">
      {suggestions.map((suggestion) => <button key={suggestion} disabled={disabled} onClick={() => onPick(suggestion)} className="block w-full rounded-xl border border-dashed border-line px-3 py-2 text-left text-sm transition hover:border-moss hover:bg-white">“{suggestion}”</button>)}
    </div>
  </div>
}
