import { useApp } from "../lib/app";
import { hotkeyLabel, modelLabel } from "../lib/format";
import { Icon } from "./Icon";

const NAV = [
  ["/home", "Home", "home"],
  ["/meetings", "Meetings", "meetings"],
  ["/insights", "Insights", "insights"],
  ["/dictionary", "Dictionary", "dictionary"],
] as const;

function StatusCard() {
  const { engine } = useApp();
  if (!engine) return null;
  const key = <span className="kbd">{hotkeyLabel(engine.hotkey)}</span>;
  const verb = engine.mode === "hold" ? "Hold" : "Press";
  const model = modelLabel(engine.model);
  const lines: Record<string, [string, string, React.ReactNode]> = {
    off: ["off", engine.error ? "Dictation stopped" : "Dictation is off", engine.error ?? "Start it from the menu bar icon."],
    loading: ["busy", `Loading ${model}…`, "Takes a few seconds."],
    idle: ["", `${model} ready`, <>{verb} {key} to dictate</>],
    recording: ["rec", "Listening…", <>{verb === "Hold" ? "Let go of" : "Press"} {key} to finish</>],
    transcribing: ["busy", "Transcribing…", <>{verb} {key} to dictate</>],
  };
  const [dot, title, sub] = lines[engine.dictation] ?? lines.off;
  return (
    <div className="status-card" aria-live="polite">
      <div className="status-line"><span className={`dot ${engine.error ? "err" : dot}`} />{title}</div>
      <div className="status-sub">{sub}</div>
    </div>
  );
}

export function Sidebar({ route, go }: { route: string; go: (r: string) => void }) {
  const active = (path: string) => route === path || route.startsWith(path + "/");
  return (
    <nav className="sidebar" aria-label="Main">
      <div className="brand">
        <div className="brand-mark"><Icon name="mic" size={14} stroke={2.2} /></div>
        local-stt
      </div>
      {NAV.map(([path, label, icon]) => (
        <button key={path} className="nav-link" aria-current={active(path) ? "page" : undefined} onClick={() => go(path)}>
          <Icon name={icon} />{label}
        </button>
      ))}
      <div className="spacer" />
      <StatusCard />
      <button className="nav-link" aria-current={active("/settings") ? "page" : undefined} onClick={() => go("/settings")}>
        <Icon name="settings" />Settings
      </button>
    </nav>
  );
}
