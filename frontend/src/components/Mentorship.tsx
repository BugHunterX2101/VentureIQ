import { useCallback, useEffect, useState } from "react";
import { m } from "motion/react";
import { api, type MentorOffer } from "../lib/api";
import { relativeTime } from "../lib/format";
import { Badge, Card, Empty, SectionHeader } from "./primitives";
import { useToast } from "./ui/Toast";
import { useAuth } from "../lib/auth";

/** Mentorship: an investor offers time, the founder decides, and the founder
 *  alone decides whether anyone else gets to see it.
 *
 *  Two views of the same records:
 *  - `MentorsPanel` on a company profile — the public list, plus the offer
 *    button for a signed-in visitor who does not own the company.
 *  - `MentorInbox` on My companies — the founder's queue.
 */

const FALLBACK_AREAS = [
  "Go-to-market", "Hiring", "Fundraising", "Product", "Engineering",
  "Pricing", "Compliance", "Operations", "Marketing", "Sales",
];

function Avatar({ name }: { name: string }) {
  const initials = name.split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  return (
    <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-brand-tint text-[12px] font-bold text-brand-text">
      {initials}
    </div>
  );
}

function AreaChips({ areas }: { areas: string[] }) {
  if (!areas.length) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {areas.map((a) => (
        <span key={a} className="rounded-full border border-line bg-plane px-2 py-0.5 text-[11.5px] font-semibold text-ink-secondary">
          {a}
        </span>
      ))}
    </div>
  );
}

export function MentorsPanel({ startupId, ownerIsMe }: { startupId: string; ownerIsMe: boolean }) {
  const { user } = useAuth();
  const toast = useToast();
  const [mentors, setMentors] = useState<MentorOffer[] | null>(null);
  const [mine, setMine] = useState<MentorOffer | null>(null);
  const [areas, setAreas] = useState<string[]>(FALLBACK_AREAS);
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [hours, setHours] = useState("4");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.mentorsOf(startupId);
      setMentors(r.mentors);
      setMine(r.my_offer);
    } catch {
      setMentors([]);
    }
  }, [startupId]);

  useEffect(() => {
    void load();
    api.mentorFocusAreas().then((r) => setAreas(r.focus_areas)).catch(() => {});
  }, [load]);

  async function send() {
    setBusy(true);
    try {
      await api.offerMentorship({
        startup_id: startupId,
        message: message.trim() || null,
        focus_areas: picked,
        hours_per_month: Number(hours) || null,
      });
      toast({
        title: "Offer sent",
        body: "The founder decides whether to accept, and whether to show it publicly.",
        tone: "good",
      });
      setOpen(false);
      setMessage("");
      setPicked([]);
      await load();
    } catch (e) {
      toast({ title: "Couldn't send that", body: (e as Error).message.slice(0, 160), tone: "warning" });
    } finally {
      setBusy(false);
    }
  }

  async function withdraw() {
    if (!mine) return;
    setBusy(true);
    try {
      await api.withdrawMentorship(mine.offer_id);
      toast({ title: "Offer withdrawn" });
      await load();
    } finally {
      setBusy(false);
    }
  }

  const canOffer = user && !ownerIsMe;

  return (
    <Card id="mentors" className="scroll-mt-24 p-5 sm:p-6">
      <SectionHeader
        title="Mentors"
        description="People offering time rather than money. Shown here only when the founder accepted and chose to publish it."
      />

      {mentors === null ? (
        <div className="skeleton h-16 rounded-xl" />
      ) : mentors.length === 0 ? (
        <Empty title="No public mentors yet" hint="A founder can accept an offer privately and still keep it off this page." />
      ) : (
        <ul className="space-y-3">
          {mentors.map((mn) => (
            <li key={mn.offer_id} className="flex gap-3 border-b border-grid pb-3 last:border-0 last:pb-0">
              <Avatar name={mn.mentor_name} />
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[14px] font-bold">{mn.mentor_name}</span>
                  {mn.mentor_firm && <span className="text-[12.5px] text-ink-muted">{mn.mentor_firm}</span>}
                  <Badge tone="good">Mentor</Badge>
                </div>
                <AreaChips areas={mn.focus_areas} />
                {mn.decided_at && (
                  <div className="mt-1 text-[11.5px] text-ink-muted">since {relativeTime(mn.decided_at)}</div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {canOffer && (
        <div className="mt-5 border-t border-line pt-4">
          {mine && mine.status === "offered" ? (
            <div className="flex flex-wrap items-center gap-3">
              <Badge tone="warning">Your offer is pending</Badge>
              <button className="btn h-9" onClick={withdraw} disabled={busy}>Withdraw</button>
            </div>
          ) : mine && mine.status === "accepted" ? (
            <Badge tone="good">You are mentoring this company{mine.public ? "" : " (not shown publicly)"}</Badge>
          ) : !open ? (
            <button className="btn btn-primary h-10" onClick={() => setOpen(true)}>
              Offer to mentor
            </button>
          ) : (
            <m.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-3">
              <div>
                <div className="eyebrow mb-1.5">Where you can help</div>
                <div className="flex flex-wrap gap-1.5">
                  {areas.map((a) => {
                    const on = picked.includes(a);
                    return (
                      <button
                        key={a}
                        type="button"
                        onClick={() => setPicked(on ? picked.filter((x) => x !== a) : [...picked, a].slice(0, 6))}
                        className={`rounded-full border px-3 py-1 text-[12.5px] font-semibold transition-colors ${
                          on ? "border-brand bg-brand-tint text-brand-text" : "border-line text-ink-secondary hover:bg-raised"
                        }`}
                      >
                        {a}
                      </button>
                    );
                  })}
                </div>
              </div>
              <textarea
                className="field w-full py-2"
                rows={3}
                maxLength={1200}
                placeholder="What you'd help with, and why you're a good fit."
                value={message}
                onChange={(e) => setMessage(e.target.value)}
              />
              <div className="flex flex-wrap items-center gap-2">
                <label className="text-[12.5px] text-ink-muted" htmlFor="mentor-hours">Hours a month</label>
                <input
                  id="mentor-hours"
                  className="field h-9 w-20"
                  type="number"
                  min={1}
                  max={80}
                  value={hours}
                  onChange={(e) => setHours(e.target.value)}
                />
                <button className="btn btn-primary h-9" onClick={send} disabled={busy || !picked.length}>
                  {busy ? "Sending…" : "Send offer"}
                </button>
                <button className="btn h-9" onClick={() => setOpen(false)} disabled={busy}>Cancel</button>
              </div>
              {!picked.length && (
                <p className="text-[12px] text-ink-muted">Pick at least one area so the founder can triage.</p>
              )}
            </m.div>
          )}
        </div>
      )}
    </Card>
  );
}

export function MentorInbox({ startupId, startupName }: { startupId: string; startupName: string }) {
  const toast = useToast();
  const [offers, setOffers] = useState<MentorOffer[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setOffers(await api.mentorshipInbox(startupId));
    } catch {
      setOffers([]);
    }
  }, [startupId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function decide(offer: MentorOffer, accept: boolean, isPublic: boolean) {
    setBusy(offer.offer_id);
    try {
      await api.decideMentorship(offer.offer_id, { accept, public: isPublic });
      toast({
        title: accept ? "Mentor accepted" : "Offer declined",
        body: accept
          ? isPublic
            ? "They'll show on your public profile."
            : "Kept private — only you and they can see it."
          : undefined,
        tone: accept ? "good" : undefined,
      });
      await load();
    } catch (e) {
      toast({ title: "Couldn't save that", body: (e as Error).message.slice(0, 160), tone: "warning" });
    } finally {
      setBusy(null);
    }
  }

  async function toggleVisibility(offer: MentorOffer) {
    setBusy(offer.offer_id);
    try {
      await api.setMentorVisibility(offer.offer_id, !offer.public);
      await load();
    } finally {
      setBusy(null);
    }
  }

  const pending = (offers ?? []).filter((o) => o.status === "offered");
  const accepted = (offers ?? []).filter((o) => o.status === "accepted");
  if (offers !== null && !pending.length && !accepted.length) return null;

  return (
    <div className="mt-4 rounded-xl border border-line bg-plane p-4">
      <div className="eyebrow mb-2">
        Mentorship for {startupName}
        {pending.length > 0 && <span className="ml-2 text-brand-text">{pending.length} waiting</span>}
      </div>

      {pending.map((o) => (
        <div key={o.offer_id} className="border-b border-grid py-3 last:border-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[13.5px] font-bold">{o.mentor_name}</span>
            {o.mentor_firm && <span className="text-[12.5px] text-ink-muted">{o.mentor_firm}</span>}
            {o.hours_per_month && <span className="text-[12px] text-ink-muted">· {o.hours_per_month}h/month</span>}
          </div>
          <AreaChips areas={o.focus_areas} />
          {o.message && <p className="mt-2 text-[13px] leading-relaxed text-ink-secondary">{o.message}</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="btn btn-primary h-9" disabled={busy === o.offer_id}
                    onClick={() => decide(o, true, true)}>
              Accept &amp; show publicly
            </button>
            <button className="btn h-9" disabled={busy === o.offer_id}
                    onClick={() => decide(o, true, false)}>
              Accept privately
            </button>
            <button className="btn h-9" disabled={busy === o.offer_id}
                    onClick={() => decide(o, false, false)}>
              Decline
            </button>
          </div>
        </div>
      ))}

      {accepted.map((o) => (
        <div key={o.offer_id} className="flex flex-wrap items-center gap-2 border-b border-grid py-2.5 last:border-0">
          <span className="text-[13.5px] font-bold">{o.mentor_name}</span>
          <Badge tone={o.public ? "good" : "neutral"}>{o.public ? "Public" : "Private"}</Badge>
          {o.mentor_email && <span className="text-[12px] text-ink-muted">{o.mentor_email}</span>}
          <button className="btn ml-auto h-8 px-3 text-[12px]" disabled={busy === o.offer_id}
                  onClick={() => toggleVisibility(o)}>
            {o.public ? "Hide from profile" : "Show on profile"}
          </button>
        </div>
      ))}
    </div>
  );
}
