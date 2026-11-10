"use client";
import { useEffect, useState, useRef, FormEvent } from "react";
import AnswerContent from "./components/answer-content";
import { resultPageDisplay } from "./lib/result-pages";
import AnswerMetrics, { type ResponseMetrics } from "./components/answer-metrics";
type DataPage = { title?: string; rows: Record<string, unknown>[]; truncated?: boolean };
type Source = { id: string; title: string; document?: string; content?: string };
type Reply = {
    role?: string;
    text: string;
    kind?: string;
    rows?: Record<string, unknown>[];
    data_pages?: DataPage[];
    sources?: Source[];
    choices?: string[];
    demo?: boolean;
    metrics?: ResponseMetrics;
};
type Session = {
    id: string;
    title: string;
};
async function api(path: string, data?: unknown) {
    const csrf = document.cookie.split("; ").find(c => c.startsWith("relay_csrftoken=") || c.startsWith("csrftoken="))?.split("=")[1] || "";
    const readOnly = data === undefined;
    for (let attempt = 0; ; attempt++) {
        let response: Response;
        try {
            response = await fetch(`/api/${path}/`, { cache: "no-store", method: readOnly ? "GET" : "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": decodeURIComponent(csrf) }, ...(readOnly ? {} : { body: JSON.stringify(data) }) });
        } catch {
            if (readOnly && attempt < 2) {
                await new Promise(resolve => setTimeout(resolve, attempt === 0 ? 500 : 1500));
                continue;
            }
            throw new Error("The support server connection was interrupted. Check that the backend is running, then try again.");
        }
        if (readOnly && [500, 502, 503, 504].includes(response.status) && attempt < 2) {
            await response.body?.cancel();
            await new Promise(resolve => setTimeout(resolve, attempt === 0 ? 500 : 1500));
            continue;
        }
        const result = await response.json().catch(() => null);
        if (!response.ok) {
            throw new Error(result?.error || (response.status === 404 ? "API route not found. Restart the Apptimate Assist frontend and backend to load the updated connection settings." : response.status >= 500 ? "The support server could not complete this request. Check that the backend is running, then try again." : `Request failed (${response.status})`));
        }
        if (result === null) throw new Error("The support server returned an invalid response. Please try again.");
        return result;
    }
}
function ResultTable({page}: {page: DataPage}) {
    const columns = [...new Set(page.rows.flatMap(row => Object.keys(row)))];
    const display = (value: unknown) => value == null ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);
    const formatCol = (col: string) => col.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    return <section className="result-page">{page.title && <h3>{page.title}</h3>}{page.rows.length ? <div className="table-wrap"><table><thead><tr>{columns.map(key => <th key={key}>{formatCol(key)}</th>)}</tr></thead><tbody>{page.rows.map((row, index) => <tr key={index}>{columns.map(key => <td key={key}>{display(row[key])}</td>)}</tr>)}</tbody></table></div> : <p className="muted">No records in this result.</p>}{page.truncated && <small>More records are available. Ask for the next page.</small>}</section>;
}
function getConversationTurns(msgs: Reply[], count?: number): Reply[] {
    if (!msgs.length) return [];
    const turns: Reply[][] = [];
    let currentTurn: Reply[] = [];
    for (const m of msgs) {
        if (m.role === "user" && currentTurn.length > 0) {
            turns.push(currentTurn);
            currentTurn = [];
        }
        currentTurn.push(m);
    }
    if (currentTurn.length > 0) {
        turns.push(currentTurn);
    }
    const selectedTurns = count ? turns.slice(-count) : turns;
    return selectedTurns.flat();
}
function formatConversation(msgs: Reply[]): string {
    return msgs.map(m => {
        const roleLabel = m.role === "user" ? "User" : "Apptimate Assist";
        let text = `### ${roleLabel}:\n${m.text?.trim() || ""}`;
        if (m.rows && m.rows.length > 0 && resultPageDisplay(m.text, { rows: m.rows }) === "table") {
            const cols = [...new Set(m.rows.flatMap(r => Object.keys(r)))];
            const header = `| ${cols.join(" | ")} |`;
            const divider = `| ${cols.map(() => "---").join(" | ")} |`;
            const body = m.rows.map(r => `| ${cols.map(c => {
                const v = r[c];
                return v == null ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v).replace(/\n/g, " ");
            }).join(" | ")} |`).join("\n");
            text += `\n\n${header}\n${divider}\n${body}`;
        }
        if (m.sources && m.sources.length > 0) {
            const srcList = m.sources.map(s => s.title || s.document || s.id).filter(Boolean).join(", ");
            if (srcList) {
                text += `\n\n_Sources: ${srcList}_`;
            }
        }
        return text;
    }).join("\n\n---\n\n");
}
async function copyToClipboard(text: string): Promise<boolean> {
    if (typeof navigator !== "undefined" && navigator.clipboard && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch {
            // fallback to execCommand
        }
    }
    if (typeof document !== "undefined") {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        ta.style.top = "-9999px";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        try {
            const ok = document.execCommand("copy");
            document.body.removeChild(ta);
            return ok;
        } catch {
            document.body.removeChild(ta);
            return false;
        }
    }
    return false;
}
export default function Home() {
    const [ready, setReady] = useState(true), [signed, setSigned] = useState(true), [demo, setDemo] = useState(false);
    const [erp, setErp] = useState(true), [tenant, setTenant] = useState(process.env.NEXT_PUBLIC_ERP_TENANT || "apptimate_infinity"), [workspace, setWorkspace] = useState("Apptimate One");
    const [sessions, setSessions] = useState<Session[]>([]), [id, setId] = useState<string | null>(null), [messages, setMessages] = useState<Reply[]>([]);
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const [retention, setRetention] = useState({ hold_days: 1, max_chats: 10 });
    const [deletingChat, setDeletingChat] = useState<string | null>(null);
    const [input, setInput] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState(""), [tab, setTab] = useState("Assistant");
    const [docs, setDocs] = useState<{
        id: string;
        title: string;
        content: string;
    }[]>([]);
    const [selectedSource, setSelectedSource] = useState<Source | null>(null);
    const [copiedMode, setCopiedMode] = useState<string | null>(null);
    const sourceDialog = useRef<HTMLDialogElement>(null);
    const composerInput = useRef<HTMLTextAreaElement>(null);
    useEffect(() => { setSidebarOpen(window.innerWidth > 540); }, []);
    useEffect(() => { if (selectedSource && sourceDialog.current && !sourceDialog.current.open) sourceDialog.current.showModal(); }, [selectedSource]);
    const refresh = async () => setSessions((await api("sessions")).sessions);
    useEffect(() => { api("bootstrap").then(async (b) => { setSigned(true); if (b.retention) setRetention(b.retention); setDemo(Boolean(b.demo)); setErp(b.auth_mode === "erp"); setTenant(b.tenant || "apptimate_infinity"); setWorkspace(b.workspace || "Apptimate One"); await refresh(); }).catch(() => {}).finally(() => setReady(true)); }, []);
    async function signIn(e: FormEvent<HTMLFormElement>) { e.preventDefault(); setSigned(true); await refresh().catch(() => {}); }
    async function handleCopy(mode: "last" | "last5" | "all") {
        if (!messages.length) return;
        const targetMsgs = mode === "last" ? getConversationTurns(messages, 1) : mode === "last5" ? getConversationTurns(messages, 5) : messages;
        const text = formatConversation(targetMsgs);
        const ok = await copyToClipboard(text);
        if (ok) {
            setCopiedMode(mode);
            setTimeout(() => setCopiedMode(null), 2500);
        }
    }
    async function send(text = input) { if (!text.trim() || busy)
        return; setBusy(true); setError(""); setInput(""); setMessages(m => [...m, { role: "user", text }]); let answered = false; try {
        const result = await api("chat", { message: text, session_id: id });
        setId(result.session_id);
        setMessages(m => [...m, { ...result, text: result.text || result.response || "", role: "assistant" }]);
        answered = true;
        await refresh();
    }
    catch (e) {
        if (!answered) setInput(current => current || text);
        setError(answered ? `Your answer was received, but the chat list could not refresh. ${(e as Error).message}` : (e as Error).message);
    }
    finally {
        setBusy(false);
    } }
    function resetChat() {
        setId(null);
        setMessages([]);
        setInput("");
        setError("");
        setSelectedSource(null);
        sourceDialog.current?.close();
        setTab("Assistant");
        if (window.innerWidth <= 540) setSidebarOpen(false);
        window.scrollTo({ top: 0 });
        requestAnimationFrame(() => composerInput.current?.focus({ preventScroll: true }));
    }
    function newChat() {
        if (!busy) resetChat();
    }
    async function deleteChat(session: Session) {
        if (busy || !window.confirm(`Delete “${session.title}”?\nThis permanently deletes this chat and its saved answers.`)) return;
        setBusy(true);
        setDeletingChat(session.id);
        setError("");
        try {
            await api(`sessions/${encodeURIComponent(session.id)}/delete`, {});
            setSessions(current => current.filter(chat => chat.id !== session.id));
            if (id === session.id) resetChat();
        } catch (e) {
            setError((e as Error).message);
        } finally {
            setDeletingChat(null);
            setBusy(false);
        }
    }
    async function openSession(session: Session) { setBusy(true); setError(""); try {
        const result = await api(`sessions/${session.id}`);
        setId(session.id);
        setMessages(result.messages);
        setTab("Assistant");
        if (window.innerWidth <= 540) setSidebarOpen(false);
    }
    catch (e) {
        setError((e as Error).message);
    }
    finally {
        setBusy(false);
    } }
    async function knowledge() { setTab("Knowledge"); try {
        setDocs((await api("documents")).documents);
    }
    catch (e) {
        setError((e as Error).message);
    } }
    if (!ready)
        return <div className="loading">Connecting to your workspace…</div>;
    if (!signed)
        return <main className="login"><form onSubmit={signIn}><span className="logo">A</span><h1>Welcome to Apptimate Assist</h1><p>{erp ? "Sign in with your Apptimate ERP account." : "Your ERP support workspace."}</p>{erp && <p className="tenant-note">Tenant: {tenant}</p>}<label>{erp ? "ERP email" : "Username"}<input name="username" required autoComplete="username" type={erp ? "email" : "text"}/></label><label>Password<input name="password" type="password" required autoComplete="current-password"/></label>{error && <p role="alert" className="error">{error}</p>}<button disabled={busy}>Sign in →</button><small>{erp ? "Uses the same account and database as Apptimate One support services." : "Create your account using the Django setup command in the README."}</small></form></main>;
    return <div className={`shell${sidebarOpen ? " sidebar-open" : ""}`}><dialog className="source-dialog" ref={sourceDialog} onClose={() => setSelectedSource(null)} aria-labelledby="source-title"><div className="source-dialog-header"><div><span className="eyebrow">CITED DOCUMENTATION</span><h2 id="source-title">{selectedSource?.title}</h2><small>{selectedSource?.document}</small></div><button aria-label="Close source" onClick={() => sourceDialog.current?.close()}>×</button></div><div className="source-dialog-content"><AnswerContent text={selectedSource?.content || "No excerpt was included with this source."}/></div></dialog>{sidebarOpen && <button className="sidebar-backdrop" aria-label="Close recent chats" onClick={() => setSidebarOpen(false)} />}<aside><div className="sidebar-heading"><a className="brand" href="/"><span className="logo">A</span> <span className="brand-name">Apptimate Assist</span></a><button className="sidebar-toggle" onClick={() => setSidebarOpen(open => !open)} aria-expanded={sidebarOpen} aria-controls="recent-chats" aria-label={sidebarOpen ? "Hide recent chats" : "Show recent chats"} title={sidebarOpen ? "Hide recent chats" : "Show recent chats"}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></svg></button></div><div className="workspace"><span className="workspace-icon">A</span><div>{workspace}<small>{tenant || "ERP support assistant"}</small></div><span>⌄</span></div><nav aria-label="Workspace navigation"><button className="new-chat" disabled={busy} onClick={newChat} aria-label="New chat" title="New chat"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg><span>New chat</span></button><button className={tab === "Assistant" ? "active" : ""} onClick={() => setTab("Assistant")}>◈ <span>Assistant</span></button><button className={tab === "Knowledge" ? "active" : ""} onClick={knowledge}>▤ <span>Knowledge base</span></button></nav><div className="recent">RECENT CHATS</div><div className="session-list" id="recent-chats" aria-label="Recent chats">{sessions.length === 0 ? <p className="muted">Your conversations will appear here.</p> : sessions.map(s => <div className={`session-row${id === s.id ? " selected" : ""}`} key={s.id}><button className="session-open" disabled={busy} title={s.title} aria-current={id === s.id ? "page" : undefined} onClick={() => openSession(s)}>◷ <span>{s.title}</span></button><button className="delete-chat" disabled={busy} title="Delete chat" aria-label={`Delete chat: ${s.title}`} aria-busy={deletingChat === s.id} onClick={() => deleteChat(s)}>{deletingChat === s.id ? "…" : <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 6h18M9 6V4h6v2M5 6l1 14h12l1-14M10 10v6M14 10v6" /></svg>}</button></div>)}</div><div className="connection"><i /> {demo ? "Demo workspace" : "ERP connected"}<small>{demo ? "Sample sales data enabled" : "Admin · Unrestricted access"}</small></div><button className="account" onClick={() => resetChat()}><span className="avatar">A</span><div>ERP Administrator<small>Admin · All modules</small></div><span>↗</span></button></aside><main className="main"><header><div>Workspace <span>/</span> <strong>{tab}</strong></div><div className="header-right">{messages.length > 0 && tab === "Assistant" && <div className="header-copy-actions" role="toolbar" aria-label="Quick copy conversation"><button type="button" className={`header-copy-btn${copiedMode === "last" ? " copied" : ""}`} onClick={() => handleCopy("last")} title="Copy last conversation turn">{copiedMode === "last" ? "✓ Copied" : "Copy Last"}</button><button type="button" className={`header-copy-btn${copiedMode === "last5" ? " copied" : ""}`} onClick={() => handleCopy("last5")} title="Copy last 5 conversation turns">{copiedMode === "last5" ? "✓ Copied" : "Copy Last 5"}</button><button type="button" className={`header-copy-btn${copiedMode === "all" ? " copied" : ""}`} onClick={() => handleCopy("all")} title="Copy entire conversation">{copiedMode === "all" ? "✓ Copied" : "Copy Entire Chat"}</button></div>}<span className="status">● {demo ? "Demo mode" : "Admin · Read-only"}</span><span className="avatar">A</span></div></header><div className="content">{tab === "Knowledge" ? <section className="knowledge"><div className="eyebrow">WORKSPACE RESOURCES</div><h1>Knowledge base</h1><p className="subtitle">Documentation used to ground your assistant’s answers.</p>{docs.map(d => <article key={d.id}><span className="badge">MARKDOWN</span><h2>{d.title}</h2><AnswerContent text={d.content}/></article>)}</section> : <><div className={messages.length ? "conversation" : "welcome"}>{messages.length === 0 ? <><div className="hero-icon">✳</div><div className="eyebrow">YOUR WORKDAY, A LITTLE SIMPLER</div><h1>What can I help you<br />with today?</h1><p className="subtitle">Find your way around your ERP, get step-by-step guidance,<br className="desktop"/> or explore your business data. Just ask.</p><div className="suggestions">{[{ icon: "↗", title: "Find a screen", desc: "Where can we create sales?", q: "Where can we create sales?" }, { icon: "▥", title: "Explore sales", desc: "List POS sales under 500", q: "List POS sales under 500" }, { icon: "≡", title: "Get guidance", desc: "How do I create a POS sale?", q: "How do I create a POS sale?" }].map(s => <button key={s.title} disabled={busy} onClick={() => send(s.q)}><span className="card-icon">{s.icon}</span><strong>{s.title}</strong><span>{s.desc}</span><b>↗</b></button>)}</div><div className="trust">♧ Documentation-backed guidance <span>·</span> Read-only data access</div></> : <><div className="chat-actions-bar" role="toolbar" aria-label="Conversation actions"><span className="actions-label">CONVERSATION ACTIONS</span><button type="button" className={`chat-action-btn${copiedMode === "last" ? " copied" : ""}`} onClick={() => handleCopy("last")} title="Copy the most recent question and answer"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg><span>{copiedMode === "last" ? "✓ Copied Last Turn" : "Copy Last Turn"}</span></button><button type="button" className={`chat-action-btn${copiedMode === "last5" ? " copied" : ""}`} onClick={() => handleCopy("last5")} title="Copy the last 5 conversation turns"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg><span>{copiedMode === "last5" ? "✓ Copied Last 5" : "Copy Last 5"}</span></button><button type="button" className={`chat-action-btn${copiedMode === "all" ? " copied" : ""}`} onClick={() => handleCopy("all")} title="Copy the full conversation history"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg><span>{copiedMode === "all" ? "✓ Copied Entire Chat" : "Copy Entire Chat"}</span></button></div>{messages.map((m, index) => <div className={`message ${m.role}`} key={index}><span className="message-avatar">{m.role === "user" ? "U" : "✳"}</span><div className="message-body"><div className="message-label">{m.role === "user" ? "You" : "Apptimate Assist"}{m.demo && <span className="badge">SAMPLE DATA</span>}</div>{m.role === "user" ? <p className="answer-text">{m.text}</p> : <AnswerContent text={m.text} dataPages={m.data_pages} rows={m.rows}/> }{m.data_pages?.map((page, i) => { const display = resultPageDisplay(m.text, page); return display === "notice" ? <small className="result-pagination" key={i}>More records are available. Ask for the next page.</small> : null; })}{m.sources?.map(s => <button className="source" key={s.id} onClick={() => setSelectedSource(s)}>▤ {s.title} ↗</button>)}{m.choices?.map(c => <button className="source" disabled={busy} key={c} onClick={() => send(c)}>{c} →</button>)}{m.role !== "user" && <AnswerMetrics metrics={m.metrics}/>}</div></div>)}</>}{busy && !deletingChat && <div role="status" className="thinking">✳ Finding an answer…</div>}</div><div className="composer-area">{error && <p role="alert" className="error">{error}</p>}<form className="composer" onSubmit={e => { e.preventDefault(); send(); }}><textarea ref={composerInput} aria-label="Message" placeholder="Ask about your ERP…" value={input} maxLength={2000} disabled={busy} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        send();
    } }}/><div className="composer-bottom"><span>✳ Apptimate Assist <span className="slash">/</span> <span className="muted">{demo ? "Demo data" : "ERP data"}</span></span><button aria-label="Send message" disabled={busy || !input.trim()}>↑</button></div></form><p className="footnote">{demo ? "Demo environment · Answers use sample documentation and sales records." : `Verify important answers against your ERP. Keeps ${retention.max_chats} chats for up to ${retention.hold_days} day${retention.hold_days === 1 ? "" : "s"} after their last activity.`}</p></div></>}</div></main></div>;
}
