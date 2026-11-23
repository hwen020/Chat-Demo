import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { createRoot } from 'react-dom/client'
import { api, ApiError, readEvents } from './api'
import './styles.css'

type Account = { id: string; email: string }
type Conversation = { id: string; title: string }
type Message = { id: string; seq: number; role: 'user' | 'assistant'; content: string; state: string; generation_id?: string }
type History = { messages: Message[]; before: number | null }
type Pending = { content: string; request_key: string }

function messageFor(error: unknown) {
  const messages: Record<string, string> = {
    invalid_credentials: 'Check your email and password.',
    account_exists: 'An account already uses this email.',
    invalid_input: 'Check the form and try again.',
    rate_limited: 'Too many requests. Try again in a minute.',
    generation_active: 'A reply is still in progress.',
    authentication_required: 'Your session expired. Sign in again.',
    not_found: 'This conversation is no longer available.',
    generation_timeout: 'The reply timed out. You can send another message.',
    generation_failed: 'The reply could not be completed.',
    generation_cancelled: 'Reply stopped.',
  }
  return error instanceof ApiError && messages[error.code] || 'The request could not finish. Please try again.'
}

function Brand() {
  return <div className="brand"><span className="brand-mark" aria-hidden="true">✳</span> ChatFlow</div>
}

function Auth({ onAccount }: { onAccount: (account: Account) => void }) {
  const [register, setRegister] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    setBusy(true)
    setError('')
    try {
      onAccount(await api<Account>('/auth/' + (register ? 'register' : 'login'), 'POST',
        { email: data.get('email'), password: data.get('password') }))
    } catch (err) { setError(messageFor(err)) } finally { setBusy(false) }
  }
  return <main className="auth-shell"><section className="auth-card"><Brand />
    <h1>{register ? 'Create your account' : 'Welcome back'}</h1>
    <p>Keep your conversations in one place.</p>
    <form onSubmit={submit}>
      <label>Email<input name="email" type="email" autoComplete="email" required /></label>
      <label>Password<input name="password" type="password" minLength={10}
        autoComplete={register ? 'new-password' : 'current-password'} required /></label>
      {error && <p className="error" role="alert">{error}</p>}
      <button className="primary" disabled={busy}>{register ? 'Create account' : 'Sign in'}</button>
    </form>
    <button className="text-button" onClick={() => { setRegister(!register); setError('') }}>
      {register ? 'Use an existing account' : 'Create an account'}
    </button>
  </section></main>
}

function Workspace({ account, logout }: { account: Account; logout: () => void }) {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selected, setSelected] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [before, setBefore] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [network, setNetwork] = useState('')
  const [posting, setPosting] = useState(false)
  const [running, setRunning] = useState(false)
  const [activeRun, setActiveRun] = useState('')
  const [stopping, setStopping] = useState(false)
  const [pending, setPending] = useState<Pending | null>(null)
  const [mobile, setMobile] = useState(false)
  const [edit, setEdit] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [title, setTitle] = useState('')
  const stream = useRef<AbortController | null>(null)
  const selectedRef = useRef('')
  const current = conversations.find(item => item.id === selected)
  const storageKey = (id: string) => 'chatflow:pending:' + account.id + ':' + id
  const base = (id: string) => '/conversations/' + id

  useEffect(() => {
    const controller = new AbortController()
    api<Conversation[]>('/conversations', 'GET', undefined, controller.signal)
      .then(items => {
        setConversations(items)
        if (!selectedRef.current) select(linkedConversation() || items[0]?.id || '', 'replace')
      }).catch(err => { if (!controller.signal.aborted) setError(messageFor(err)) })
    const onBack = () => select(linkedConversation(), 'none')
    window.addEventListener('popstate', onBack)
    return () => { controller.abort(); stream.current?.abort(); window.removeEventListener('popstate', onBack) }
  }, [])

  function linkedConversation() {
    return window.location.pathname.match(/^\/c\/([\da-f-]{36})$/i)?.[1] ?? ''
  }

  function select(id: string, navigation: 'push' | 'replace' | 'none' = 'push') {
    const path = id ? '/c/' + id : '/'
    if (path !== window.location.pathname) {
      if (navigation === 'push') window.history.pushState(null, '', path)
      if (navigation === 'replace') window.history.replaceState(null, '', path)
    }
    setActiveRun(''); setStopping(false)
    stream.current?.abort()
    selectedRef.current = id
    setSelected(id)
    setMessages([]); setBefore(null); setError(''); setNetwork(''); setRunning(false)
    setEdit(false); setConfirmDelete(false); setMobile(false); setDraft('')
    const saved = id && sessionStorage.getItem(storageKey(id))
    setPending(saved ? JSON.parse(saved) as Pending : null)
    if (id) void refresh(id, true)
  }

  async function refresh(id: string, resume = false) {
    try {
      const history = await api<History>(base(id) + '/messages')
      if (selectedRef.current !== id) return
      setMessages(history.messages); setBefore(history.before)
      const active = history.messages.find(item => item.state === 'pending')
      if (resume && active?.generation_id) void follow(id, active.generation_id)
    } catch (err) { if (selectedRef.current === id) setError(messageFor(err)) }
  }

  async function follow(id: string, run: string) {
    stream.current?.abort()
    const controller = new AbortController()
    stream.current = controller
    setRunning(true); setActiveRun(run)
    let cursor = 0
    let content = ''
    let terminal = false
    let code = ''
    const root = base(id) + '/generations/' + run
    try {
      for (let attempt = 0; attempt < 4 && !terminal && !controller.signal.aborted; attempt++) {
        try {
          await readEvents(root + '/events', cursor, controller.signal, event => {
            if (event.id && event.id <= cursor) return
            if (event.id) cursor = event.id
            if (event.kind === 'delta') {
              content += event.data.text ?? ''
              const reply = content
              setMessages(items => items.map(item => item.generation_id === run ? { ...item, content: reply } : item))
            }
            if (['done', 'error', 'reset'].includes(event.kind)) {
              terminal = true
              if (event.kind === 'error') code = event.data.code ?? 'generation_failed'
            }
          })
          if (!terminal) {
            const state = await api<{ state: string; error_code?: string }>(root, 'GET', undefined, controller.signal)
            terminal = ['complete', 'failed'].includes(state.state)
            code = state.error_code ?? ''
          }
        } catch (err) {
          if (controller.signal.aborted) return
          if (err instanceof ApiError && err.status === 410) { terminal = true; break }
          if (err instanceof ApiError && [401, 404].includes(err.status)) throw err
        }
        if (!terminal) {
          setNetwork('Reconnecting to the reply…')
          await new Promise(resolve => setTimeout(resolve, 400 * (attempt + 1)))
        }
      }
      if (controller.signal.aborted) return
      if (!terminal) setNetwork('Connection interrupted. Reopen the conversation to resume.')
      else setNetwork('')
      await refresh(id)
      if (code && selectedRef.current === id) setError(messageFor(new ApiError(500, code)))
    } catch (err) {
      if (!controller.signal.aborted) setError(messageFor(err))
    } finally {
      if (stream.current === controller) {
        setRunning(false)
        if (terminal) setActiveRun('')
      }
    }
  }

  async function stopReply() {
    const id = selected
    const run = activeRun
    if (!run || stopping) return
    setStopping(true)
    try {
      await api(base(id) + '/generations/' + run + '/cancel', 'POST', {})
      if (selectedRef.current !== id) return
      stream.current?.abort()
      setActiveRun(''); setRunning(false); setNetwork('')
      await refresh(id)
    } catch (err) { if (selectedRef.current === id) setError(messageFor(err)) }
    finally { if (selectedRef.current === id) setStopping(false) }
  }

  async function create() {
    try {
      const item = await api<Conversation>('/conversations', 'POST', { title: 'New conversation' })
      setConversations(items => [item, ...items]); select(item.id)
    } catch (err) { setError(messageFor(err)) }
  }

  async function send(event: FormEvent) {
    event.preventDefault()
    const id = selected
    if (!id || posting || running || !(pending || draft.trim())) return
    const payload = pending ?? { content: draft.trim(), request_key: crypto.randomUUID() }
    sessionStorage.setItem(storageKey(id), JSON.stringify(payload))
    setPending(payload); setPosting(true); setError('')
    try {
      const run = await api<{ id: string }>(base(id) + '/messages', 'POST', payload)
      sessionStorage.removeItem(storageKey(id))
      if (selectedRef.current !== id) return
      setDraft(''); setPending(null)
      await refresh(id)
      if (selectedRef.current === id) void follow(id, run.id)
    } catch (err) {
      if (selectedRef.current === id) setError(messageFor(err))
      if (err instanceof ApiError && [400, 401, 404, 409, 422, 429].includes(err.status)) {
        sessionStorage.removeItem(storageKey(id))
        if (selectedRef.current === id) setPending(null)
      }
    } finally { setPosting(false) }
  }

  async function rename(event: FormEvent) {
    event.preventDefault()
    try {
      const item = await api<Conversation>(base(selected), 'PATCH', { title })
      setConversations(items => items.map(value => value.id === item.id ? item : value))
      setEdit(false)
    } catch (err) { setError(messageFor(err)) }
  }

  async function remove() {
    try {
      await api(base(selected), 'DELETE')
      const others = conversations.filter(item => item.id !== selected)
      setConversations(others); select(others[0]?.id ?? '')
    } catch (err) { setError(messageFor(err)); setConfirmDelete(false) }
  }

  async function loadOlder() {
    const id = selected
    try {
      const history = await api<History>(base(id) + '/messages?before=' + before)
      if (selectedRef.current === id) {
        setMessages(items => [...history.messages, ...items]); setBefore(history.before)
      }
    } catch (err) { setError(messageFor(err)) }
  }

  return <div className="workspace">
    {mobile && <div className="scrim" aria-hidden="true" onClick={() => setMobile(false)} />}
    <aside className={mobile ? 'sidebar open' : 'sidebar'} aria-label="Conversations"
      onKeyDown={event => { if (event.key === 'Escape') setMobile(false) }}>
      <div className="sidebar-heading"><Brand /><button className="drawer-close"
        aria-label="Close conversations" onClick={() => setMobile(false)}>Close</button></div>
      <button className="new-chat" onClick={create}><span aria-hidden="true">＋</span> New conversation</button>
      <nav aria-label="Conversation history">
        {conversations.map(item => <button key={item.id} type="button" onClick={() => select(item.id)}
          aria-current={item.id === selected ? 'page' : undefined}>
          <span aria-hidden="true">◌</span><span>{item.title}</span>
        </button>)}
      </nav>
      <div className="account"><span className="avatar">{account.email[0].toUpperCase()}</span>
        <span title={account.email}>{account.email}</span><button onClick={async () => {
          try { await api('/auth/logout', 'POST', {}); logout() } catch (err) { setError(messageFor(err)) }
        }}>Sign out</button></div>
    </aside>
    <main className="chat">
      <header className="top">
        <button className="menu" aria-label="Open conversations" onClick={() => setMobile(true)}>☰</button>
        <div className="heading">{edit ? <form onSubmit={rename} className="rename">
          <input aria-label="Conversation title" maxLength={100} required value={title} onChange={e => setTitle(e.target.value)} />
          <button className="plain">Save</button><button type="button" className="plain" onClick={() => setEdit(false)}>Cancel</button>
        </form> : <h1>{current?.title ?? 'Workspace'}</h1>}
        </div>
        <span className="mode"><span aria-hidden="true" />Mock active</span>
        {current && !edit && <div className="actions">
          <button className="plain" onClick={() => { setTitle(current.title); setEdit(true) }}>Rename</button>
          <button className="plain" onClick={() => setConfirmDelete(true)}>Delete</button>
        </div>}
      </header>
      {confirmDelete && <div className="confirm" role="group" aria-label="Confirm conversation deletion">
        <span>Delete this conversation and its messages?</span>
        <button className="plain" onClick={() => setConfirmDelete(false)}>Cancel</button>
        <button className="primary" onClick={remove}>Delete conversation</button>
      </div>}
      <section className="thread" aria-label="Messages">
        {!messages.length ? <div className="empty">
          <span className="empty-mark" aria-hidden="true">✳</span>
          <h2>{current ? 'What would you like to explore?' : 'Start a conversation'}</h2>
          <p>{current ? 'Send a message to try a deterministic, streamed reply.' : 'Create a conversation to send your first message.'}</p>
          {!current && <button className="primary" onClick={create}>New conversation</button>}
          {current && <div className="examples">
            {['Break down a project idea', 'Explain a technical concept'].map(example =>
              <button key={example} onClick={() => setDraft(example)}>{example} <span aria-hidden="true">↗</span></button>)}
          </div>}
        </div> : <div className="messages">
          {before && <button className="plain" onClick={loadOlder}>Load earlier messages</button>}
          {messages.map(item => <article className={'message ' + item.role} key={item.id}>
            <span className="message-icon" aria-hidden="true">{item.role === 'assistant' ? '✳' : '↗'}</span>
            <div><strong>{item.role === 'assistant' ? 'ChatFlow' : 'You'}</strong>
              <p>{item.content || (item.state === 'pending' ? 'Waiting for reply…' : '')}</p>
              {item.state === 'failed' && <small>Reply incomplete</small>}
            </div>
          </article>)}
        </div>}
      </section>
      <footer className="composer-area">
        {error && <p className="error" role="alert">{error}</p>}
        {(running || network) && <p className="status" role="status">{network || 'Receiving reply…'}</p>}
        {activeRun && <button type="button" className="plain" disabled={stopping} onClick={stopReply}>Stop reply</button>}
        {current && <form className="composer" onSubmit={send}>
          <textarea aria-label="Message" placeholder="Message ChatFlow" rows={2} maxLength={4000}
            value={pending?.content ?? draft} disabled={!!pending || posting} onChange={event => setDraft(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault(); event.currentTarget.form?.requestSubmit()
            } }} />
          <button className="primary" type="submit" disabled={posting || running || !(pending || draft.trim())}>
            {pending ? 'Retry send' : 'Send'} <span aria-hidden="true">↑</span>
          </button>
        </form>}
      </footer>
    </main>
  </div>
}

function App() {
  const [account, setAccount] = useState<Account | null>(null)
  const [loading, setLoading] = useState(true)
  const [unavailable, setUnavailable] = useState(false)
  useEffect(() => {
    api<Account>('/me').then(setAccount).catch(err => {
      if (!(err instanceof ApiError && err.status === 401)) setUnavailable(true)
    }).finally(() => setLoading(false))
  }, [])
  if (loading || unavailable) return <main className="auth-shell"><section className="auth-card">
    <Brand /><p>{unavailable ? 'ChatFlow is unavailable. Reload to try again.' : 'Loading your workspace…'}</p>
  </section></main>
  return account ? <Workspace key={account.id} account={account} logout={() => setAccount(null)} /> :
    <Auth onAccount={setAccount} />
}

createRoot(document.getElementById('root')!).render(<App />)
