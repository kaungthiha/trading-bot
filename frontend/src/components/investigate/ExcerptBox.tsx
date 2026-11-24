import { useId, useState } from "react";

import type { InvestigationHypothesis, InvestigationResult, InvestigationSource } from "../../api/types";
import { investigation } from "./store";

/** Phase 4, stream 3: text you paste from something you read. It stays on this computer,
 * the app never opens the link, and it's marked unverified until another source agrees. */

const MAX = 5;
const MAX_TEXT = 4000;

export function ExcerptBox({ r, h }: { r: InvestigationResult; h: InvestigationHypothesis }) {
  const [text, setText] = useState("");
  const [source, setSource] = useState("");
  const [url, setUrl] = useState("");
  const [date, setDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const id = useId();
  const count = r.sources.filter((s) => s.access === "user_provided").length;
  const full = count >= MAX;
  const ready = text.trim().length >= 20 && source.trim().length > 0 && !busy && !full;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const add = investigation.source().addExcerpt;
    if (!ready || !add) return;
    setBusy(true);
    setMsg(null);
    try {
      const next = await add(r.investigation_id, {
        text: text.trim(), source: source.trim(), url: url.trim() || null, published_on: date || null,
      });
      investigation.update(h, next);
      setText(""); setSource(""); setUrl(""); setDate("");
      setMsg({ tone: "ok", text: "Excerpt added. It's marked unverified until another source agrees." });
    } catch (err) {
      setMsg({ tone: "err", text: err instanceof Error ? err.message : "Couldn't add the excerpt" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <details className="inv-excerpt">
      <summary>Add an excerpt you've read{count > 0 && ` (${count} added)`}</summary>
      <p className="small muted">
        Paste a short passage from an article you read. It stays on this computer, the app never
        opens the link, and it's shown as unverified until another source agrees. No search is used.
      </p>
      <form onSubmit={submit} className="inv-excerpt-form">
        <label htmlFor={`${id}-text`}>Excerpt</label>
        <textarea id={`${id}-text`} value={text} maxLength={MAX_TEXT} rows={5} required
          onChange={(e) => setText(e.target.value)} disabled={full} />
        <span className="fine muted">{text.length} / {MAX_TEXT} characters{text.trim().length > 0 && text.trim().length < 20 ? " · at least 20" : ""}</span>
        <label htmlFor={`${id}-src`}>Source</label>
        <input id={`${id}-src`} value={source} maxLength={120} required placeholder="e.g. The Athletic"
          onChange={(e) => setSource(e.target.value)} disabled={full} />
        <label htmlFor={`${id}-url`}>Link (optional, never opened by the app)</label>
        <input id={`${id}-url`} type="url" value={url} maxLength={500} placeholder="https://"
          onChange={(e) => setUrl(e.target.value)} disabled={full} />
        <label htmlFor={`${id}-date`}>Published (optional)</label>
        <input id={`${id}-date`} type="date" value={date} onChange={(e) => setDate(e.target.value)} disabled={full} />
        <button type="submit" className="ghost-button" disabled={!ready}>
          {busy ? "Adding…" : "Add excerpt"}
        </button>
        {full && <p className="small" role="note">At most {MAX} excerpts per investigation: remove one to add another.</p>}
        {msg && <p className={`small ${msg.tone === "err" ? "inv-note" : "muted"}`} role={msg.tone === "err" ? "alert" : "status"}>{msg.text}</p>}
      </form>
    </details>
  );
}

/** In the sources list: your pasted text (collapsed) and a remove button. */
export function ExcerptText({ r, h, s }: { r: InvestigationResult; h: InvestigationHypothesis; s: InvestigationSource }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const remove = async () => {
    const rm = investigation.source().removeExcerpt;
    if (!rm) return;
    setBusy(true);
    setErr(null);
    try {
      investigation.update(h, await rm(r.investigation_id, s.id));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't remove the excerpt");
      setBusy(false);
    }
  };
  return (
    <div className="inv-excerpt-item">
      {s.excerpt && (
        <details>
          <summary className="small">Show your excerpt</summary>
          <blockquote className="small">{s.excerpt}</blockquote>
        </details>
      )}
      <button type="button" className="link-button small" onClick={remove} disabled={busy}
        aria-label={`Remove your excerpt from ${s.publisher}`}>{busy ? "Removing…" : "Remove"}</button>
      {err && <span className="small inv-note" role="alert"> {err}</span>}
    </div>
  );
}
