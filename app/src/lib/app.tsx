import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, EngineInfo, engineInfo, EngineState, initEngine, on, onEngineInfo, ready } from "./engine";

export type ModelInfo = {
  name: string;
  family: string;
  languages: string;
  downloaded: boolean;
  loaded: boolean;
  size_mb: number;
  unavailable: string | null;
};

export type Config = {
  model: { name: string; compute_type: string; device: string; language: string };
  dictation: {
    hotkey: string; mode: "toggle" | "hold"; output: "type" | "clipboard"; listener: string;
    min_duration_ms: number; max_duration_ms: number; append_space: boolean; notify: boolean;
  };
  meeting: { output_dir: string; model: string; language: string };
  cleanup: { enabled: boolean; api_url: string; api_model: string };
  diarize: { hf_token: string };
};

export type AppState = {
  config: Config;
  platform: string;
  default_model: string;
  onboarding: { done: boolean; step: number };
  models: ModelInfo[];
  downloading: Record<string, string>;
  progress: Record<string, number | null>;
  cleanup: { key_saved: boolean };
  engine: EngineState;
};

export type Permissions = {
  supported: boolean;
  status: Record<string, "granted" | "denied" | "not_asked" | "unknown">;
};

type Ctx = {
  info: EngineInfo | null;
  state: AppState | null;
  engine: EngineState | null;
  perms: Permissions | null;
  refresh: () => Promise<void>;
  refreshPerms: () => Promise<void>;
  saveConfig: (section: Partial<Record<keyof Config, object>>) => Promise<boolean>;
  toast: (text: string, error?: boolean) => void;
};

const AppContext = createContext<Ctx | null>(null);

export function useApp() {
  return useContext(AppContext)!;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [info, setInfo] = useState<EngineInfo | null>(engineInfo());
  const [state, setState] = useState<AppState | null>(null);
  const [engine, setEngine] = useState<EngineState | null>(null);
  const [perms, setPerms] = useState<Permissions | null>(null);
  const [toastMsg, setToast] = useState<{ text: string; error: boolean } | null>(null);
  const toastTimer = useRef<number>(undefined);

  const toast = useCallback((text: string, error = false) => {
    setToast({ text, error });
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), error ? 6000 : 2200);
  }, []);

  const refresh = useCallback(async () => {
    if (!ready()) return;
    const s = await api<AppState>("/api/state");
    setState(s);
    setEngine(s.engine);
  }, []);

  const refreshPerms = useCallback(async () => {
    if (!ready()) return;
    setPerms(await api<Permissions>("/api/permissions"));
  }, []);

  const saveConfig = useCallback(async (section: Partial<Record<keyof Config, object>>) => {
    try {
      const r = await api<{ reload_error: string | null }>("/api/config", section);
      await refresh();
      if (r.reload_error) toast(r.reload_error, true);
      else toast("Saved");
      return true;
    } catch (e) {
      toast((e as Error).message, true);
      return false;
    }
  }, [refresh, toast]);

  useEffect(() => {
    const off = onEngineInfo(setInfo);
    initEngine().catch((e) => setInfo({ port: null, token: null, error: String(e) }));
    return off;
  }, []);

  useEffect(() => {
    if (!info?.port) return;
    refresh().catch(() => {});
    refreshPerms().catch(() => {});
  }, [info, refresh, refreshPerms]);

  useEffect(() => on("state", (s) => {
    setEngine(s);
    // the model list changes once a model loads
    refresh().catch(() => {});
  }), [refresh]);

  useEffect(() => {
    if (!state || !Object.values(state.downloading).includes("running")) return;
    const t = window.setInterval(() => refresh().catch(() => {}), 1000);
    return () => window.clearInterval(t);
  }, [state, refresh]);

  const value = useMemo(
    () => ({ info, state, engine, perms, refresh, refreshPerms, saveConfig, toast }),
    [info, state, engine, perms, refresh, refreshPerms, saveConfig, toast],
  );
  return (
    <AppContext.Provider value={value}>
      {children}
      {toastMsg && <div className={`toast${toastMsg.error ? " err" : ""}`} role="status">{toastMsg.text}</div>}
    </AppContext.Provider>
  );
}

export function useRoute(): [string, (route: string) => void] {
  const read = () => location.hash.replace(/^#/, "") || "/home";
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onHash = () => setRoute(read());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return [route, (next: string) => { location.hash = next; }];
}

/** Re-runs fn whenever one of the engine events fires. */
export function useEngineEvent<K extends Parameters<typeof on>[0]>(kind: K, fn: Parameters<typeof on<K>>[1]) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => on(kind, (d) => ref.current(d)), [kind]);
}
