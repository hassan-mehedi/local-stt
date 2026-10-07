const MOD_SYMBOLS: Record<string, string> = {
  alt: "⌥", option: "⌥", shift: "⇧", ctrl: "⌃", control: "⌃",
  cmd: "⌘", super: "⌘", win: "⌘", meta: "⌘",
};
const SIDES: Record<string, string> = { l: "Left", r: "Right" };
const NAMED: Record<string, string> = {
  space: "Space", enter: "Return", tab: "Tab", esc: "Esc", backspace: "Delete",
  up: "↑", down: "↓", left: "←", right: "→", caps_lock: "Caps Lock",
};

/** "<alt>+<shift>+t" -> ["⌥", "⇧", "T"]; "alt_r" -> ["Right ⌥"] */
export function hotkeyKeys(spec: string): string[] {
  return spec
    .toLowerCase()
    .split("+")
    .map((p) => p.trim().replace(/^<(.+)>$/, "$1"))
    .filter(Boolean)
    .map((name) => {
      if (MOD_SYMBOLS[name]) return MOD_SYMBOLS[name];
      const sided = name.match(/^(alt|ctrl|shift|cmd)_([lr])$/);
      if (sided) return `${SIDES[sided[2]]} ${MOD_SYMBOLS[sided[1]]}`;
      if (NAMED[name]) return NAMED[name];
      if (/^f\d+$/.test(name)) return name.toUpperCase();
      return name.length === 1 ? name.toUpperCase() : name;
    });
}

export function hotkeyLabel(spec: string) {
  return hotkeyKeys(spec).join("");
}

const MODIFIER_CODES: Record<string, string> = {
  AltLeft: "alt_l", AltRight: "alt_r", ShiftLeft: "shift_l", ShiftRight: "shift_r",
  ControlLeft: "ctrl_l", ControlRight: "ctrl_r", MetaLeft: "cmd_l", MetaRight: "cmd_r",
};

/** The config spec for a key press in the shortcut recorder, or null while
 * only modifiers are down. A lone modifier counts once it is released. */
export function specFromEvent(e: KeyboardEvent, released = false): string | null {
  const code = e.code;
  if (MODIFIER_CODES[code]) {
    return released ? MODIFIER_CODES[code] : null;
  }
  let key: string | null = null;
  if (/^Key[A-Z]$/.test(code)) key = code.slice(3).toLowerCase();
  else if (/^Digit\d$/.test(code)) key = code.slice(5);
  else if (/^F\d+$/.test(code)) key = code.toLowerCase();
  else if (code === "Space") key = "space";
  else if (code === "Tab") key = "tab";
  else if (code === "Enter") key = "enter";
  else if (code.startsWith("Arrow")) key = code.slice(5).toLowerCase();
  if (!key) return null;
  const mods = [
    e.ctrlKey && "<ctrl>", e.altKey && "<alt>", e.shiftKey && "<shift>", e.metaKey && "<cmd>",
  ].filter(Boolean);
  return [...mods, key].join("+");
}

export function modelLabel(name: string) {
  const known: Record<string, string> = {
    "parakeet-tdt-0.6b-v2": "Parakeet v2",
    "parakeet-tdt-0.6b-v3": "Parakeet v3",
    "bengali-whisper-medium": "Bengali Whisper",
    "large-v3-turbo": "Whisper large v3 turbo",
    "large-v3": "Whisper large v3",
    "distil-large-v3": "Whisper distil large v3",
  };
  return known[name] ?? `Whisper ${name}`;
}

export const LANGUAGES: Record<string, string> = {
  "": "Auto-detect", en: "English", bn: "Bengali", de: "German", es: "Spanish",
  fr: "French", it: "Italian", nl: "Dutch", pt: "Portuguese", ru: "Russian", uk: "Ukrainian",
  pl: "Polish", hi: "Hindi", ar: "Arabic", ja: "Japanese", zh: "Chinese",
};

export function languageName(code: string) {
  return LANGUAGES[code] ?? code.toUpperCase();
}

export function clock(date: Date) {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function dayLabel(date: Date, now = new Date()) {
  const start = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((start(now) - start(date)) / 86400000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return date.toLocaleDateString([], { weekday: "long" });
  return date.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short", year: date.getFullYear() === now.getFullYear() ? undefined : "numeric" });
}

export function duration(seconds: number) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

export function mmss(seconds: number) {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const mm = String(Math.floor((s % 3600) / 60)).padStart(h ? 2 : 1, "0");
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function number(n: number) {
  return n.toLocaleString("en-US");
}

export function plural(n: number, one: string, many = `${one}s`) {
  return `${number(n)} ${n === 1 ? one : many}`;
}

export function greeting(now = new Date()) {
  const h = now.getHours();
  return h < 5 ? "Good evening" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}
