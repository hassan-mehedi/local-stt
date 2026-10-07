// Pill preferences live in localStorage, which the main window and the pill
// share; the pill hears changes through the storage event.

const IDLE_KEY = "pill.showIdle";

export function readPillIdle() {
  try {
    return localStorage.getItem(IDLE_KEY) !== "0";
  } catch {
    return true;
  }
}

export function writePillIdle(show: boolean) {
  try {
    localStorage.setItem(IDLE_KEY, show ? "1" : "0");
  } catch {
    // private storage: the default (shown) stays
  }
}

export function onPillIdleChange(fn: (show: boolean) => void) {
  const handler = (e: StorageEvent) => e.key === IDLE_KEY && fn(readPillIdle());
  window.addEventListener("storage", handler);
  return () => window.removeEventListener("storage", handler);
}
