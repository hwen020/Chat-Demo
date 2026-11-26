import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { createRoot } from 'react-dom/client'
import { api, ApiError } from './api'
import './styles.css'

type Account = { id: string; email: string }
type Chat = { id: string; title: string; contacts: string[]; group_chat: boolean }
type Message = { seq: number; sender_id: string; sender: string; content: string; created_at: string }
type Page = { messages: Message[]; before: number | null }
type OutgoingMessage = { content: string; request_key: string }
type Receipt = { type: 'ack'; request_key: string; message: Message }
  | { type: 'error'; request_key?: string; code: string }
class SocketUnavailable extends Error {}
const describe = (error: unknown) => error instanceof ApiError
  ? error.code.replaceAll('_', ' ') : 'Connection failed. Try again.'

function SignIn({ onAccount }: { onAccount: (account: Account) => void }) {
  const [register, setRegister] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setBusy(true)
    setError('')
    try {
      onAccount(await api<Account>(register ? '/auth/register' : '/auth/login', 'POST', Object.fromEntries(form)))
    } catch (err) { setError(describe(err)) } finally { setBusy(false) }
  }
  return <main className="sign-in"><form onSubmit={submit}>
    <div className="brand">ChatFlow Messenger</div>
    <h1>{register ? 'Create an account' : 'Sign in'}</h1>
    <label>Email<input name="email" type="email" required autoComplete="email" /></label>
    <label>Password<input name="password" type="password" minLength={10} required
      autoComplete={register ? 'new-password' : 'current-password'} /></label>
    {error && <p role="alert">{error}</p>}
    <button className="primary" disabled={busy}>{register ? 'Register' : 'Sign in'}</button>
    <button type="button" onClick={() => { setRegister(!register); setError('') }}>
      {register ? 'Use an existing account' : 'Create an account'}
    </button>
  </form></main>
}

function MessageSearch({ chat, close }: { chat: string; close: () => void }) {
  const [draft, setDraft] = useState('')
  const [term, setTerm] = useState('')
  const [result, setResult] = useState<Page>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function search(filter: string, before?: number) {
    setBusy(true)
    setError('')
    if (!before) { setTerm(filter); setResult(undefined) }
    const params = new URLSearchParams({ q: filter })
    if (before) params.set('before', String(before))
    try {
      const page = await api<Page>('/chats/' + chat + '/messages?' + params)
      setResult(previous => before && previous
        ? { messages: [...page.messages, ...previous.messages], before: page.before } : page)
    } catch (err) { setError(describe(err)) }
    finally { setBusy(false) }
  }

  return <div className="thread" aria-label="Message search results">
    <form className="message-search" onSubmit={event => {
      event.preventDefault()
      if (draft.trim() && !busy) void search(draft.trim())
    }}>
      <input aria-label="Search messages" type="search" maxLength={100} value={draft}
        onChange={event => setDraft(event.target.value)} />
      <button disabled={busy || !draft.trim()}>Search</button>
      <button type="button" onClick={close}>Close</button>
    </form>
    {error && <p role="alert">{error}</p>}
    {busy && <p role="status">Searching messages...</p>}
    {result?.before && <button disabled={busy} onClick={() => search(term, result.before!)}>Earlier matches</button>}
    {result && !result.messages.length && <p>No matching messages.</p>}
    {result?.messages.map(message => <article key={message.seq}>
      <small>{message.sender}</small><p>{message.content}</p>
    </article>)}
  </div>
}

function Workspace({ account, onLogout }: { account: Account; onLogout: () => void }) {
  const [chats, setChats] = useState<Chat[]>([])
  const [query, setQuery] = useState('')
  const [searchingMessages, setSearchingMessages] = useState(false)
  const [selected, setSelected] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [before, setBefore] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [busy, setBusy] = useState(false)
  const [connected, setConnected] = useState(false)
  const current = chats.find(chat => chat.id === selected)
  const view = useRef('')
  const pending = useRef<(OutgoingMessage & { chat: string }) | null>(null)
  const liveSocket = useRef<{ chat: string; socket: WebSocket }>()
  const receipts = useRef(new Map<string, (notice: Receipt) => void>())
  const bottom = useRef<HTMLDivElement>(null)

  function refresh(filter: string, signal?: AbortSignal) {
    return api<Chat[]>('/chats?q=' + encodeURIComponent(filter), 'GET', undefined, signal)
  }

  useEffect(() => {
    const controller = new AbortController()
    const load = () => refresh(query, controller.signal).then(items => {
      if (!controller.signal.aborted) setChats(items)
    }).catch(err => { if (!controller.signal.aborted) setError(describe(err)) })
    void load()
    const timer = window.setInterval(load, 4000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [query])

  useEffect(() => {
    if (!selected) return
    const controller = new AbortController()
    const path = '/chats/' + selected
    let socket: WebSocket | undefined
    let timer: number | undefined
    let cursor = 0
    let reconnectDelay = 1000
    function connect() {
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      socket = new WebSocket(protocol + '//' + location.host + '/v1' + path + '/live?after=' + cursor)
      liveSocket.current = { chat: selected, socket }
      socket.onopen = () => { reconnectDelay = 1000; setConnected(true) }
      socket.onmessage = event => {
        if (controller.signal.aborted) return
        const frame = JSON.parse(event.data) as Message | Receipt
        if ('type' in frame) {
          if (frame.request_key) receipts.current.get(frame.request_key)?.(frame)
          return
        }
        const message = frame
        if (!Number.isSafeInteger(message.seq)) return
        cursor = Math.max(cursor, message.seq)
        setMessages(items => items.some(item => item.seq === message.seq) ? items
          : [...items, message].sort((a, b) => a.seq - b.seq))
      }
      socket.onclose = () => {
        if (controller.signal.aborted) return
        setConnected(false)
        timer = window.setTimeout(connect, reconnectDelay)
        reconnectDelay = Math.min(15000, reconnectDelay * 2)
      }
    }
    api<Page>(path + '/messages', 'GET', undefined, controller.signal).then(page => {
      if (controller.signal.aborted) return
      setMessages(page.messages)
      setBefore(page.before)
      cursor = page.messages.at(-1)?.seq ?? 0
      connect()
    }).catch(err => { if (!controller.signal.aborted) setError(describe(err)) })
    return () => {
      controller.abort(); socket?.close(); window.clearTimeout(timer)
      if (liveSocket.current?.socket === socket) liveSocket.current = undefined
    }
  }, [selected])

  useEffect(() => { bottom.current?.scrollIntoView({ block: 'end' }) }, [messages.at(-1)?.seq, searchingMessages])

  function select(id: string) {
    if (view.current === id) return
    view.current = id
    setSearchingMessages(false)
    setMessages([])
    setBefore(null)
    setConnected(false)
    setDraft('')
    setError('')
    setSelected(id)
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const emails = String(form.get('contacts')).split(/[\s,]+/).filter(Boolean)
    setBusy(true)
    setError('')
    try {
      const chat = await api<{ id: string }>('/chats', 'POST', { emails, title: form.get('title') })
      setQuery('')
      setChats(await refresh(''))
      setCreating(false)
      select(chat.id)
    } catch (err) { setError(describe(err)) } finally { setBusy(false) }
  }

  function sendLive(body: OutgoingMessage): Promise<Message> {
    const socket = liveSocket.current?.chat === selected ? liveSocket.current.socket : undefined
    if (socket?.readyState !== WebSocket.OPEN) return Promise.reject(new SocketUnavailable())
    return new Promise((resolve, reject) => {
      function clear() {
        window.clearTimeout(timer)
        receipts.current.delete(body.request_key)
      }
      const timer = window.setTimeout(() => { clear(); reject(new SocketUnavailable()) }, 1500)
      receipts.current.set(body.request_key, frame => {
        clear()
        if (frame.type === 'ack') resolve(frame.message)
        else reject(new ApiError(400, frame.code))
      })
      try { socket.send(JSON.stringify(body)) } catch {
        clear()
        reject(new SocketUnavailable())
      }
    })
  }

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const content = draft.trim()
    if (!content || !selected || busy) return
    const prior = pending.current
    const request = prior?.chat === selected && prior.content === content
      ? prior : { chat: selected, content, request_key: crypto.randomUUID() }
    pending.current = request
    setBusy(true)
    setError('')
    try {
      const body = { content, request_key: request.request_key }
      const message = await sendLive(body).catch(err => {
        if (!(err instanceof SocketUnavailable)) throw err
        return api<Message>('/chats/' + selected + '/messages', 'POST', body)
      })
      pending.current = null
      if (view.current === selected) {
        setDraft(value => value.trim() === content ? '' : value)
        setMessages(items => items.some(item => item.seq === message.seq) ? items
          : [...items, message].sort((a, b) => a.seq - b.seq))
      }
    } catch (err) { if (view.current === selected) setError(describe(err)) }
    finally { setBusy(false) }
  }

  async function loadOlder() {
    if (!before || busy) return
    setBusy(true)
    try {
      const page = await api<Page>('/chats/' + selected + '/messages?before=' + before)
      if (view.current === selected) {
        setMessages(items => [...page.messages, ...items])
        setBefore(page.before)
      }
    } catch (err) { setError(describe(err)) } finally { setBusy(false) }
  }

  return <main className={'messenger' + (selected && !creating ? ' chat-open' : '')}>
    <aside>
      <div className="rail-header"><div className="brand">ChatFlow Messenger</div>
        <button onClick={() => { setCreating(!creating); setError('') }}>{creating ? 'Cancel' : 'New chat'}</button></div>
      <label className="search">Search chats<input type="search" placeholder="Name or contact" value={query}
        onChange={event => setQuery(event.target.value)} /></label>
      <nav aria-label="Chats">
        {chats.map(chat => <button key={chat.id} aria-current={chat.id === selected} onClick={() => {
          setCreating(false); select(chat.id)
        }}><span className="avatar" aria-hidden="true">{chat.title.slice(0, 1).toUpperCase()}</span>
          <span><strong>{chat.title}</strong><small>{chat.group_chat ? 'Group' : 'Direct message'}</small></span>
        </button>)}
        {!chats.length && <p className="muted">No chats found.</p>}
      </nav>
      <footer><small>{account.email}</small><button onClick={() => {
        api('/auth/logout', 'POST', {}).then(onLogout).catch(err => setError(describe(err)))
      }}>Sign out</button></footer>
    </aside>
    <section className="conversation">
      {creating ? <form className="new-chat" onSubmit={create}>
        <h1>New chat</h1>
        <label>Contact emails<input name="contacts" placeholder="alex@example.com, sam@example.com" required /></label>
        <label>Group name<input name="title" placeholder="Required for multiple contacts" maxLength={100} /></label>
        <button className="primary" disabled={busy}>Start chat</button>
      </form> : selected ? <>
        <header><button className="back" onClick={() => select('')}>Chats</button>
          <div><h1>{current?.title ?? 'Chat'}</h1>
            <small>{current?.contacts.filter(email => email !== account.email).join(', ')}</small></div>
          <button type="button" aria-expanded={searchingMessages} onClick={() => setSearchingMessages(value => !value)}>
            Find messages
          </button>
          <span className="presence" role="status">{connected ? 'Live' : 'Connecting…'}</span></header>
        {searchingMessages ? <MessageSearch key={selected} chat={selected} close={() => setSearchingMessages(false)} /> : <>
        <div className="thread" aria-label="Messages">
          {before && <button onClick={loadOlder} disabled={busy}>Load earlier messages</button>}
          {!messages.length && <p className="muted">Start the conversation with a message.</p>}
          {messages.map(message => <article key={message.seq} className={message.sender_id === account.id ? 'mine' : ''}>
            <small>{message.sender_id === account.id ? 'You' : message.sender} · {
              new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            }</small><p>{message.content}</p>
          </article>)}
          <div ref={bottom} />
        </div>
        <form className="compose" onSubmit={send}><input aria-label="Message" value={draft}
          maxLength={4000} placeholder="Write a message" onChange={event => setDraft(event.target.value)} />
          <button className="primary" disabled={!draft.trim() || busy}>Send</button></form>
        </>}
      </> : <div className="empty"><h1>Your messages</h1><p>Choose a chat or start one with a contact.</p></div>}
      {error && <p className="notice" role="alert">{error}</p>}
    </section>
  </main>
}

function App() {
  const [account, setAccount] = useState<Account | null>()
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    api<Account>('/me').then(setAccount).catch(err => {
      if (err instanceof ApiError && err.status === 401) setAccount(null)
      else setFailed(true)
    })
  }, [])
  if (failed) return <main className="sign-in"><p role="alert">Messenger could not connect. <button onClick={() => location.reload()}>Retry</button></p></main>
  if (account === undefined) return <main className="sign-in" role="status">Loading Messenger…</main>
  return account ? <Workspace account={account} onLogout={() => setAccount(null)} /> : <SignIn onAccount={setAccount} />
}

function DemoNotice() {
  const [enabled, setEnabled] = useState(false)
  useEffect(() => {
    api<{ enabled: boolean }>('/demo').then(result => setEnabled(result.enabled)).catch(() => undefined)
  }, [])
  return enabled ? <div className="demo-notice">Demo / Synthetic Data. Register with a unique @example.test address and use sample messages only.</div> : null
}

createRoot(document.getElementById('root')!).render(<><DemoNotice /><App /></>)
