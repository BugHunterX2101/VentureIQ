import { useEffect, useRef, useState } from "react";
import { AnimatePresence, m } from "motion/react";
import { api, type DocCheck, type DocResult, type StoredDoc } from "../lib/api";
import { Badge, Card } from "../components/primitives";

const LABEL: Record<string, string> = {
  cin: "CIN",
  gstin: "GSTIN",
  pan: "PAN",
  company_name: "Registered name",
  incorporation_date: "Incorporated",
  revenue: "Revenue",
  closing_balance: "Closing balance",
};

function CheckRow({ c }: { c: DocCheck }) {
  const good = c.status === "verified";
  return (
    <li className="flex items-start gap-2 text-[12.5px]">
      <span className={`mt-0.5 font-bold ${good ? "text-good-text" : "text-serious"}`}>{good ? "✓" : "✕"}</span>
      <span className="min-w-0">
        <span className="font-semibold">{c.detail}</span>
        <span className="block text-[11.5px] text-ink-muted">{c.source}</span>
      </span>
    </li>
  );
}

function Result({ r }: { r: DocResult }) {
  const conflicts = r.checks.filter((c) => c.status === "conflict").length;
  return (
    <m.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="rounded-xl border border-line bg-raised p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13.5px] font-bold">{r.doc_type_label}</span>
        <span className="truncate text-[12px] text-ink-muted">{r.filename}</span>
        <span className="ml-auto flex items-center gap-1.5">
          {conflicts > 0 ? <Badge tone="serious">{conflicts} conflict{conflicts > 1 ? "s" : ""}</Badge> : <Badge tone="good">Checks passed</Badge>}
        </span>
      </div>
      <div className="mt-1 text-[11.5px] text-ink-muted">
        {r.engine} · {r.pages} page{r.pages > 1 ? "s" : ""}
        {r.ocr_confidence !== null ? ` · OCR confidence ${(r.ocr_confidence * 100).toFixed(0)}%` : ""}
      </div>
      {r.fields.length > 0 && (
        <dl className="mt-2 grid gap-1.5 sm:grid-cols-2">
          {r.fields.map((f) => (
            <div key={f.key} className="min-w-0">
              <dt className="text-[11.5px] text-ink-muted">{LABEL[f.key] ?? f.key}</dt>
              <dd className="truncate text-[13px] font-semibold">{String(f.value)}</dd>
              {f.note && <dd className="text-[11px] leading-snug text-ink-muted">{f.note}</dd>}
            </div>
          ))}
        </dl>
      )}
      {r.checks.length > 0 && <ul className="mt-2 space-y-1.5 border-t border-line pt-2">{r.checks.map((c, i) => <CheckRow key={i} c={c} />)}</ul>}
      {r.warnings.map((w) => (
        <p key={w} className="mt-1.5 text-[12px] text-warning-text">{w}</p>
      ))}
    </m.div>
  );
}

/** Upload a certificate or statement; we read it and check what it claims. */
export default function DocumentUpload({
  sessionId,
  startupId,
  onDone,
  compact = false,
}: {
  sessionId?: string;
  startupId?: string;
  onDone?: (r: DocResult) => void;
  compact?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [caps, setCaps] = useState<{ ocr_available: boolean; detail: string; max_file_mb: number; accepted: string[]; checks: string[] } | null>(null);
  const [results, setResults] = useState<DocResult[]>([]);
  const [stored, setStored] = useState<StoredDoc[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);

  useEffect(() => {
    api.docCapabilities().then(setCaps).catch(() => {});
    if (startupId) api.startupDocuments(startupId).then(setStored).catch(() => {});
  }, [startupId]);

  async function send(file: File) {
    setBusy(true);
    setError(null);
    try {
      const r = await api.uploadDocument({ sessionId, startupId }, file);
      setResults((prev) => [r, ...prev]);
      onDone?.(r);
      if (startupId) api.startupDocuments(startupId).then(setStored).catch(() => {});
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  const disabled = busy || caps?.ocr_available === false;

  return (
    <Card className={compact ? "p-4" : "p-5"}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-[16px] font-bold">Documents</h2>
          <p className="text-[12.5px] text-ink-muted">
            Upload a certificate of incorporation, GST certificate or financials. We read it and check what it claims.
          </p>
        </div>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          const file = e.dataTransfer.files?.[0];
          if (file) void send(file);
        }}
        className={`mt-3 rounded-xl border-2 border-dashed px-4 py-6 text-center transition-colors ${
          drag ? "border-brand bg-brand-tint" : "border-line-strong"
        }`}
      >
        <input
          ref={input}
          type="file"
          className="sr-only"
          accept={caps?.accepted.join(",") ?? ".pdf,.png,.jpg"}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void send(file);
          }}
        />
        <button className="btn btn-primary h-10" disabled={disabled} onClick={() => input.current?.click()}>
          {busy ? "Reading…" : "Choose a file"}
        </button>
        <p className="mt-2 text-[12px] text-ink-muted">
          {caps?.ocr_available === false
            ? caps.detail
            : `or drop it here — PDF or image, up to ${caps?.max_file_mb ?? 12} MB`}
        </p>
      </div>

      {error && (
        <div role="alert" className="mt-3 rounded-xl border border-critical-line bg-critical-tint px-3 py-2 text-[13px] text-critical-text">
          {error}
        </div>
      )}

      <AnimatePresence initial={false}>
        {results.length > 0 && <div className="mt-3 space-y-2">{results.map((r, i) => <Result key={i} r={r} />)}</div>}
      </AnimatePresence>

      {stored.length > 0 && results.length === 0 && (
        <ul className="mt-3 space-y-2">
          {stored.map((d) => {
            const conflicts = d.checks.filter((c) => c.status === "conflict").length;
            return (
              <li key={d.document_id} className="flex flex-wrap items-center gap-2 rounded-lg bg-raised px-3 py-2 text-[13px]">
                <span className="font-semibold">{d.doc_type_label}</span>
                <span className="truncate text-[12px] text-ink-muted">{d.filename}</span>
                <span className="ml-auto">
                  {conflicts > 0 ? <Badge tone="serious">{conflicts} conflict{conflicts > 1 ? "s" : ""}</Badge> : <Badge tone="good">{d.checks.length} check{d.checks.length === 1 ? "" : "s"} passed</Badge>}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {caps && !compact && (
        <ul className="mt-3 space-y-0.5 border-t border-line pt-3 text-[12px] text-ink-muted">
          {caps.checks.map((c) => <li key={c}>· {c}</li>)}
        </ul>
      )}
    </Card>
  );
}
