// The recording pill window. It also keeps the menu bar icon in step with
// the engine and runs the menu's Start/Stop rows, since it is always loaded.

import { listen } from "@tauri-apps/api/event";
import { useEffect, useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { api, EngineState, initEngine, inTauri, Notice, on, onEngineInfo, ready, tauri } from "../lib/engine";
import { hotkeyLabel } from "../lib/format";
import { onPillIdleChange, readPillIdle } from "./prefs";

const BARS = 22;
const DONE_MS = 1400;
const NOTICE_MS = 9000;
// panel sizes per look, in points; the panel sits at the bottom center
const SIZES = {
  idle: [80, 26],
  hint: [280, 46],
  recording: [300, 60],
  transcribing: [190, 60],
  done: [300, 60],
  notice: [420, 60],
} as const;
type Look = keyof typeof SIZES | "hidden";

const PANES: Record<string, string> = {
  accessibility: "Allow Accessibility to type",
  input_monitoring: "Allow Input Monitoring for the shortcut",
  microphone: "Allow the microphone",
};

function useEngineState() {
  const [state, setState] = useState<EngineState | null>(null);
  useEffect(() => {
    const offState = on("state", setState);
    // the event stream sends the state as soon as it connects
    const offInfo = onEngineInfo(() => !ready() && setState(null));
    initEngine().catch(() => {});
    return () => { offState(); offInfo(); };
  }, []);
  return state;
}

export default function Pill() {
  const state = useEngineState();
  const [levels, setLevels] = useState<number[]>(Array(BARS).fill(0));
  const [since, setSince] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [done, setDone] = useState<{ app: string | null; words: number } | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [hover, setHover] = useState(false);
  const [showIdle, setShowIdle] = useState(readPillIdle());
  const doneTimer = useRef<number>(undefined);
  const noticeTimer = useRef<number>(undefined);

  const dictation = state?.dictation ?? "off";

  useEffect(() => onPillIdleChange(setShowIdle), []);

  // on macOS the page sees no mouse moves in the pill, so the panel reports hover
  useEffect(() => {
    if (!inTauri) return;
    const off = listen<boolean>("pill-hover", (e) => setHover(e.payload));
    return () => void off.then((f) => f());
  }, []);

  useEffect(() => on("level", ({ level }) => {
    setLevels((old) => [...old.slice(1), level]);
  }), []);

  useEffect(() => on("dictation", ({ item, error }) => {
    if (error) return;
    setDone({ app: item.app_name, words: item.words });
    window.clearTimeout(doneTimer.current);
    doneTimer.current = window.setTimeout(() => setDone(null), DONE_MS);
  }), []);

  useEffect(() => on("notice", (n) => {
    if (n.level !== "error") return;
    setNotice(n);
    window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(null), NOTICE_MS);
  }), []);

  useEffect(() => {
    if (dictation !== "recording") return;
    setSince(Date.now());
    setLevels(Array(BARS).fill(0));
    setDone(null);
    const t = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(t);
  }, [dictation]);

  useEffect(() => {
    if (state) tauri("set_tray_state", { dictation: state.dictation, meeting: !!state.meeting.recording });
  }, [state?.dictation, state?.meeting.recording]);

  const stateRef = useRef(state);
  stateRef.current = state;
  useEffect(() => {
    if (!inTauri) return;
    const off = listen<string>("menu", async (e) => {
      const s = stateRef.current;
      try {
        if (e.payload === "dictation") {
          await api(s?.dictation === "off" ? "/api/dictation/start" : "/api/dictation/stop", {});
        } else if (e.payload === "meeting") {
          const r = await api<{ ok: boolean; error: string | null }>("/api/meeting/toggle", {});
          if (!r.ok && r.error) setNotice({ title: "Meeting failed", body: r.error, level: "error", action: null });
        }
      } catch (err) {
        setNotice({ title: "Failed", body: (err as Error).message, level: "error", action: null });
      }
    });
    return () => void off.then((f) => f());
  }, []);

  const look: Look = notice ? "notice"
    : dictation === "recording" ? "recording"
    : dictation === "transcribing" ? "transcribing"
    : done ? "done"
    : dictation === "idle" && (showIdle || hover) ? (hover ? "hint" : "idle")
    : "hidden";

  useEffect(() => {
    if (look === "hidden") tauri("pill_hide");
    else tauri("pill_show", { width: SIZES[look][0], height: SIZES[look][1] });
  }, [look]);

  const seconds = Math.max(0, Math.floor((now - since) / 1000));
  const toggle = () => api("/api/dictation/toggle", {}).catch(() => {});

  return (
    <div className="pill-wrap" onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      {look === "idle" && <button className="pill-idle" aria-label="Start dictating" onClick={toggle} />}
      {look === "hint" && (
        <button className="pill-hint" onClick={toggle} style={{ border: 0 }}>
          <Icon name="mic" size={13} />Click or press <span className="k">{hotkeyLabel(state?.hotkey ?? "")}</span> to dictate
        </button>
      )}
      {look === "recording" && (
        <div className="pill with-button" role="status" aria-label="Recording">
          <span className="rec-dot" />
          <div className="levels" aria-hidden="true">
            {levels.map((l, i) => <span key={i} style={{ height: `${Math.round(4 + 22 * Math.min(1, Math.sqrt(l) * 2.6))}px` }} />)}
          </div>
          <span className="pill-time">{Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}</span>
          <button className="pill-x" aria-label="Cancel recording" title="Cancel (Esc)" onClick={() => api("/api/dictation/cancel", {})}>
            <Icon name="close" size={12} stroke={2.5} />
          </button>
        </div>
      )}
      {look === "transcribing" && (
        <div className="pill" role="status"><div className="thinking"><span /><span /><span /></div>Transcribing</div>
      )}
      {look === "done" && done && (
        <div className="pill" role="status">
          <span style={{ color: "#5FD68A", display: "flex" }}><Icon name="check" size={16} stroke={2.4} /></span>
          {done.app ? `Typed into ${done.app}` : "Typed"}
          <span className="mono" style={{ fontSize: 12, color: "#9A9A94" }}>{done.words} w</span>
        </div>
      )}
      {look === "notice" && notice && (
        <div className="pill with-button" role="alert">
          <span style={{ color: "#F2B35B", display: "flex" }}><Icon name="warn" size={16} stroke={2.2} /></span>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", maxWidth: 250 }} title={notice.body}>
            {notice.action ? PANES[notice.action] : notice.body || notice.title}
          </span>
          {notice.action ? (
            <button className="pill-btn" onClick={() => { api("/api/permissions/open", { name: notice.action }); setNotice(null); }}>Open Settings</button>
          ) : (
            <button className="pill-x" aria-label="Dismiss" onClick={() => setNotice(null)}><Icon name="close" size={12} stroke={2.5} /></button>
          )}
        </div>
      )}
    </div>
  );
}
