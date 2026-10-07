import { useEffect, useState } from "react";
import { hotkeyKeys, specFromEvent } from "../lib/format";

export function Keycaps({ spec, listening = false }: { spec: string; listening?: boolean }) {
  return (
    <span className="keycaps">
      {hotkeyKeys(spec).map((k, i) => <span key={i} className={`keycap${listening ? " listening" : ""}`}>{k}</span>)}
    </span>
  );
}

/** Shows the shortcut; click, then press the new keys. A lone modifier such
 * as Right Option counts when it is let go with nothing else pressed. */
export function ShortcutField({ value, onChange }: { value: string; onChange: (spec: string) => void }) {
  const [listening, setListening] = useState(false);

  useEffect(() => {
    if (!listening) return;
    let other = false;
    const down = (e: KeyboardEvent) => {
      e.preventDefault();
      if (e.code === "Escape") return setListening(false);
      const spec = specFromEvent(e);
      if (spec) {
        setListening(false);
        if (spec !== value) onChange(spec);
      } else if (!/^(Alt|Shift|Control|Meta)(Left|Right)$/.test(e.code)) {
        other = true;
      }
    };
    const up = (e: KeyboardEvent) => {
      const spec = specFromEvent(e, true);
      if (spec && !other && !e.altKey && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
        setListening(false);
        if (spec !== value) onChange(spec);
      }
    };
    window.addEventListener("keydown", down, true);
    window.addEventListener("keyup", up, true);
    return () => {
      window.removeEventListener("keydown", down, true);
      window.removeEventListener("keyup", up, true);
    };
  }, [listening, value, onChange]);

  return (
    <button className="btn" style={{ height: 40, padding: "0 8px" }} onClick={() => setListening(!listening)}
      aria-label={listening ? "Press the new shortcut, or Esc to cancel" : "Change shortcut"}>
      {listening ? <span className="muted" style={{ padding: "0 6px" }}>Press the keys…</span> : <Keycaps spec={value} />}
    </button>
  );
}
