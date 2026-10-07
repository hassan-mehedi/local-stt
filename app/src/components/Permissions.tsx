import { useEffect, useState } from "react";
import { useApp } from "../lib/app";
import { api, tauri } from "../lib/engine";
import { Icon } from "./Icon";

export const PERMISSIONS = {
  microphone: {
    icon: "mic",
    title: "Microphone",
    why: "Hears you while you dictate, and your side of a meeting.",
  },
  input_monitoring: {
    icon: "keyboard",
    title: "Input Monitoring",
    why: "Notices your shortcut from any app.",
  },
  accessibility: {
    icon: "cursor",
    title: "Accessibility",
    why: "Types the text into the app you are in. Newer macOS calls this pane Device Control and Data Access.",
  },
  system_audio: {
    icon: "speaker",
    title: "System audio",
    why: "Records the other side of a meeting. Only needed for meetings.",
  },
} as const;

export type PermissionName = keyof typeof PERMISSIONS;

function StatusBadge({ status }: { status: string }) {
  if (status === "granted") return <span className="badge ok">Allowed</span>;
  if (status === "denied") return <span className="badge err">Off</span>;
  if (status === "unknown") return <span className="badge">Not tested</span>;
  return <span className="badge warn">Not asked</span>;
}

/** One row per permission with the button that gets it granted. Polls while
 * shown, since the user flips switches in System Settings. */
export function PermissionRows({ names }: { names: PermissionName[] }) {
  const { perms, refreshPerms, toast } = useApp();
  const [opened, setOpened] = useState(false);

  useEffect(() => {
    const t = window.setInterval(() => refreshPerms().catch(() => {}), 1500);
    return () => window.clearInterval(t);
  }, [refreshPerms]);

  async function ask(name: PermissionName) {
    // the microphone asks in a dialog; the rest end up in System Settings
    const inDialog = name === "microphone" && perms?.status[name] === "not_asked";
    try {
      if (name === "system_audio") toast("Playing a short sound to test system audio…");
      await api("/api/permissions/request", { name });
      if (!inDialog && name !== "system_audio") setOpened(true);
      await refreshPerms();
    } catch (e) {
      toast((e as Error).message, true);
    }
  }

  return (
    <div className="stack gap-12">
      <div className="card">
        {names.map((name) => {
          const info = PERMISSIONS[name];
          const status = perms?.status[name] ?? "unknown";
          const label = name === "system_audio" ? "Test" : status === "not_asked" && name === "microphone" ? "Allow" : "Open System Settings";
          return (
            <div key={name} className="perm">
              <div className="perm-icon"><Icon name={info.icon} size={18} /></div>
              <div className="set-label" style={{ flexGrow: 1 }}>
                <strong>{info.title}</strong>
                <span>{info.why}</span>
              </div>
              {status === "granted" ? <StatusBadge status={status} /> : (
                <div className="row gap-8"><StatusBadge status={status} /><button className="btn small" onClick={() => ask(name)}>{label}</button></div>
              )}
            </div>
          );
        })}
      </div>
      {opened && (
        <div className="hint">
          In System Settings, switch local-stt on. If it is not in the list, click <strong>+</strong>, open
          Applications and pick local-stt. macOS applies the change after local-stt restarts.
          <div style={{ marginTop: 10 }}>
            <button className="btn small primary" onClick={() => tauri("restart_app")}>Restart local-stt</button>
          </div>
        </div>
      )}
    </div>
  );
}
