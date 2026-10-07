import { save } from "@tauri-apps/plugin-dialog";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { useApp, useEngineEvent } from "../lib/app";
import { api, inTauri, mediaUrl } from "../lib/engine";
import { clock, dayLabel, duration, languageName, mmss } from "../lib/format";

type Summary = {
  id: string;
  title: string;
  started_at: string;
  duration_s: number;
  language: string;
  model: string;
  status: "recording" | "transcribing" | "ready" | "untranscribed";
};
type Segment = { start: number; end: number; speaker: string; text: string };
type Detail = Summary & { segments: Segment[]; path: string };

function when(iso: string) {
  const d = new Date(iso);
  return `${dayLabel(d)}, ${clock(d)}`;
}

function StatusBadge({ status }: { status: Summary["status"] }) {
  if (status === "recording") return <span className="badge live">REC</span>;
  if (status === "transcribing") return <span className="badge warn">…</span>;
  if (status === "untranscribed") return <span className="badge">NEW</span>;
  return null;
}

function Highlight({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>;
  const parts = text.split(new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "ig"));
  return <>{parts.map((p, i) => (i % 2 ? <mark key={i}>{p}</mark> : p))}</>;
}

type Seek = { at: number; n: number } | null;

function Player({ id, total, onTime, seekTo }: { id: string; total: number; onTime: (t: number) => void; seekTo: Seek }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [peaks, setPeaks] = useState<number[]>([]);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [length, setLength] = useState(total);

  useEffect(() => {
    setPeaks([]);
    setTime(0);
    setPlaying(false);
    api<{ peaks: number[] }>(`/api/meetings/${encodeURIComponent(id)}/waveform`).then((r) => setPeaks(r.peaks)).catch(() => {});
  }, [id]);

  useEffect(() => {
    if (seekTo === null || !audio.current) return;
    audio.current.currentTime = seekTo.at;
    audio.current.play().catch(() => {});
  }, [seekTo]);

  const played = length ? Math.floor((time / length) * peaks.length) : 0;
  function seek(e: React.MouseEvent<HTMLDivElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    if (audio.current && length) audio.current.currentTime = ((e.clientX - box.left) / box.width) * length;
  }
  return (
    <div className="card player">
      <audio ref={audio} src={mediaUrl(`/api/meetings/${encodeURIComponent(id)}/audio`)} preload="metadata"
        onTimeUpdate={(e) => { setTime(e.currentTarget.currentTime); onTime(e.currentTarget.currentTime); }}
        onLoadedMetadata={(e) => Number.isFinite(e.currentTarget.duration) && setLength(e.currentTarget.duration)}
        onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} />
      <button className="play" aria-label={playing ? "Pause" : "Play"}
        onClick={() => (playing ? audio.current?.pause() : audio.current?.play())}>
        <Icon name={playing ? "pause" : "play"} size={14} />
      </button>
      <div className="wave" onClick={seek} role="presentation">
        {(peaks.length ? peaks : Array(120).fill(0.08)).map((p, i) => (
          <span key={i} className={i < played ? "played" : ""} style={{ height: `${Math.round(4 + p * 30)}px` }} />
        ))}
      </div>
      <span className="mono muted" style={{ fontSize: 12, flexShrink: 0 }}>{mmss(time)} / {mmss(length)}</span>
    </div>
  );
}

export default function Meetings({ route, go }: { route: string; go: (r: string) => void }) {
  const { state, toast } = useApp();
  const [items, setItems] = useState<Summary[] | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [query, setQuery] = useState("");
  const [now, setNow] = useState(0);
  const [seekTo, setSeekTo] = useState<Seek>(null);
  const [language, setLanguage] = useState("");
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(Date.now());

  const selectedId = decodeURIComponent(route.split("/")[2] ?? "") || items?.[0]?.id || null;
  const recording = items?.find((m) => m.status === "recording");

  const loadList = useCallback(() => api<{ items: Summary[] }>("/api/meetings").then((r) => setItems(r.items)), []);
  useEffect(() => { loadList().catch((e) => toast(e.message, true)); }, [loadList, toast]);
  useEngineEvent("meetings", () => { loadList().catch(() => {}); if (selectedId) loadDetail(selectedId); });

  const loadDetail = useCallback((id: string) => {
    api<Detail>(`/api/meetings/${encodeURIComponent(id)}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    setQuery("");
    setNow(0);
    if (selectedId) loadDetail(selectedId);
    else setDetail(null);
  }, [selectedId, loadDetail]);

  useEffect(() => {
    if (!recording) return;
    const t = window.setInterval(() => setTick(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [recording]);

  // languages a downloaded single-language model adds, e.g. Bengali
  const extraLanguages = useMemo(() => {
    const codes = new Set<string>();
    for (const m of state?.models ?? []) {
      if (m.downloaded && m.name === "bengali-whisper-medium") codes.add("bn");
    }
    return [...codes];
  }, [state]);

  async function toggleRecording() {
    setBusy(true);
    try {
      const r = await api<{ ok: boolean; error: string | null }>("/api/meeting/toggle", { language: recording ? undefined : language || undefined });
      if (!r.ok && r.error) toast(r.error, true);
      await loadList();
      if (!recording) go("/meetings");
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  }

  async function exportAs(format: "md" | "srt") {
    if (!detail) return;
    if (!inTauri) return toast("Export needs the app", true);
    const dest = await save({ defaultPath: `${detail.title}.${format}`, filters: [{ name: format.toUpperCase(), extensions: [format] }] });
    if (!dest) return;
    try {
      await api("/api/meetings/export", { id: detail.id, format, dest });
      toast(`Saved ${format.toUpperCase()}`);
    } catch (e) {
      toast((e as Error).message, true);
    }
  }

  const lines = useMemo(() => {
    const segs = detail?.segments ?? [];
    return query ? segs.filter((s) => s.text.toLowerCase().includes(query.toLowerCase())) : segs;
  }, [detail, query]);
  const speakers = useMemo(() => [...new Set(detail?.segments.map((s) => s.speaker).filter(Boolean))], [detail]);
  const current = detail?.segments.findIndex((s) => now >= s.start && now < s.end) ?? -1;

  const liveSeconds = recording && state?.engine.meeting.started_at
    ? (tick - new Date(state.engine.meeting.started_at).getTime()) / 1000 : 0;

  return (
    <>
      <section className="m-list" aria-label="Meetings list">
        <div className="row" style={{ justifyContent: "space-between", padding: "0 6px" }}>
          <h1>Meetings</h1>
          <button className="btn primary" onClick={toggleRecording} disabled={busy}>
            <span className="dot rec" />{recording ? "Stop" : "Record"}
          </button>
        </div>
        {!recording && extraLanguages.length > 0 && (
          <label className="row gap-8 muted" style={{ fontSize: 12, padding: "0 6px" }}>
            Language
            <select className="select" value={language} onChange={(e) => setLanguage(e.target.value)} aria-label="Meeting language">
              <option value="">{languageName(state?.config.meeting.language || state?.config.model.language || "")}</option>
              {extraLanguages.map((code) => <option key={code} value={code}>{languageName(code)}</option>)}
            </select>
          </label>
        )}
        <div className="stack gap-4">
          {items?.length === 0 && <p className="muted" style={{ padding: "0 6px", lineHeight: 1.5 }}>Record captures your mic as Me and what the Mac plays as Them, then writes a transcript.</p>}
          {items?.map((m) => (
            <button key={m.id} className="m-item" aria-current={m.id === selectedId} onClick={() => go(`/meetings/${encodeURIComponent(m.id)}`)}>
              <div className="row gap-8" style={{ justifyContent: "space-between", width: "100%" }}>
                <span style={{ fontWeight: 500 }}>{m.title}</span>
                <span className="row gap-4">
                  <StatusBadge status={m.status} />
                  {m.language && <span className="badge">{m.language.toUpperCase()}</span>}
                </span>
              </div>
              <span className="muted" style={{ fontSize: 12 }}>
                {when(m.started_at)} · {m.status === "recording" ? mmss(liveSeconds) : duration(m.duration_s)}
              </span>
            </button>
          ))}
        </div>
      </section>

      <main className="m-detail">
        {!detail ? (
          <div className="empty" style={{ marginTop: 80 }}>
            <span className="serif">No meeting selected</span>
            <span>Press Record when a call starts.</span>
          </div>
        ) : (
          <>
            <header className="row gap-16" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
              <div className="stack gap-8">
                <h2>{detail.title}</h2>
                <div className="muted" style={{ fontSize: 13 }}>
                  {[
                    new Date(detail.started_at).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }),
                    detail.status === "recording" ? "recording" : duration(detail.duration_s),
                    detail.language && languageName(detail.language),
                    speakers.length ? speakers.join(" and ") : null,
                  ].filter(Boolean).join(" · ")}
                </div>
              </div>
              <div className="row gap-8">
                <button className="btn" onClick={() => api("/api/meetings/reveal", { id: detail.id })}>Show in Finder</button>
                {detail.status === "ready" && <>
                  <button className="btn" onClick={() => exportAs("md")}>Export .md</button>
                  <button className="btn" onClick={() => exportAs("srt")}>Export .srt</button>
                </>}
              </div>
            </header>

            {detail.status === "recording" && (
              <div className="card card-pad row gap-12">
                <span className="dot rec" />
                <span style={{ flexGrow: 1 }}>Recording · <span className="mono">{mmss(liveSeconds)}</span></span>
                <button className="btn primary" onClick={toggleRecording} disabled={busy}>Stop and transcribe</button>
              </div>
            )}
            {detail.status === "transcribing" && (
              <div className="card card-pad row gap-12"><span className="dot busy" />Writing the transcript. This takes about a tenth of the meeting's length.</div>
            )}
            {detail.status === "untranscribed" && (
              <div className="card card-pad row gap-12">
                <span style={{ flexGrow: 1 }}>This meeting has no transcript yet.</span>
                <button className="btn primary" onClick={() => api("/api/meetings/transcribe", { id: detail.id }).then(loadList).catch((e) => toast(e.message, true))}>Transcribe</button>
              </div>
            )}

            {detail.status !== "recording" && (
              <Player id={detail.id} total={detail.duration_s} onTime={setNow} seekTo={seekTo} />
            )}

            {detail.segments.length > 0 && <>
              <label className="field">
                <Icon name="search" size={15} />
                <input type="search" placeholder="Search this transcript" aria-label="Search this transcript"
                  value={query} onChange={(e) => setQuery(e.target.value)} />
              </label>
              <div className="card" style={{ padding: "8px 0" }}>
                {lines.length === 0 && <div className="empty">Nothing matches "{query}".</div>}
                {lines.map((s) => {
                  const index = detail.segments.indexOf(s);
                  return (
                    <button key={index} className={`t-line${index === current ? " now" : ""}`}
                      onClick={() => setSeekTo((old) => ({ at: s.start, n: (old?.n ?? 0) + 1 }))}>
                      <span className="t-time">{mmss(s.start)}</span>
                      <span className={`t-who${s.speaker === "Me" ? "" : " them"}`}>{s.speaker}</span>
                      <span className="t-text selectable"><Highlight text={s.text} query={query} /></span>
                    </button>
                  );
                })}
              </div>
            </>}
          </>
        )}
      </main>
    </>
  );
}
