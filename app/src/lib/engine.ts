// Talks to the Python engine: its port and token come from the Tauri side
// (or from ?port=&token= when the page runs in a plain browser for testing).

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export const inTauri = "__TAURI_INTERNALS__" in window;

export type EngineInfo = { port: number | null; token: string | null; error: string | null };

export type Dictation = "off" | "loading" | "idle" | "recording" | "transcribing";

export type EngineState = {
  dictation: Dictation;
  error: string | null;
  model: string;
  hotkey: string;
  mode: "toggle" | "hold";
  meeting: { recording: string | null; started_at: string | null; transcribing: string[] };
};

export type HistoryItem = {
  id: number;
  created_at: number;
  text: string;
  words: number;
  audio_ms: number;
  elapsed_ms: number;
  app_id: string | null;
  app_name: string | null;
  has_audio: number;
  raw_text: string | null;
};

export type Notice = { title: string; body: string; level: "error" | "info"; action: string | null };

type Events = {
  state: EngineState;
  level: { level: number };
  dictation: { item: HistoryItem; error: string | null };
  notice: Notice;
  meetings: { id?: string };
};

let info: EngineInfo | null = null;
const infoListeners = new Set<(info: EngineInfo | null) => void>();
const eventListeners = new Map<string, Set<(data: unknown) => void>>();
let source: EventSource | null = null;

function setInfo(next: EngineInfo | null) {
  info = next;
  connectEvents();
  infoListeners.forEach((fn) => fn(info));
}

export function engineInfo() {
  return info;
}

export function onEngineInfo(fn: (info: EngineInfo | null) => void) {
  infoListeners.add(fn);
  return () => void infoListeners.delete(fn);
}

export async function initEngine() {
  if (!inTauri) {
    const q = new URLSearchParams(location.search);
    setInfo({ port: Number(q.get("port")) || null, token: q.get("token"), error: null });
    return;
  }
  await listen<EngineInfo>("engine", (e) => setInfo(e.payload));
  setInfo(await invoke<EngineInfo>("engine_info"));
}

export function ready() {
  return !!(info?.port && info.token);
}

export function base() {
  return `http://127.0.0.1:${info?.port}`;
}

export function mediaUrl(path: string) {
  return `${base()}${path}?token=${encodeURIComponent(info?.token ?? "")}`;
}

export async function api<T = any>(path: string, body?: unknown): Promise<T> {
  if (!ready()) throw new Error("The engine is not running");
  const res = await fetch(base() + path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "X-Token": info!.token!, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data as T;
}

function connectEvents() {
  source?.close();
  source = null;
  if (!ready()) return;
  source = new EventSource(`${base()}/api/events?token=${encodeURIComponent(info!.token!)}`);
  for (const kind of ["state", "level", "dictation", "notice", "meetings"]) {
    source.addEventListener(kind, (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      eventListeners.get(kind)?.forEach((fn) => fn(data));
    });
  }
}

export function on<K extends keyof Events>(kind: K, fn: (data: Events[K]) => void) {
  if (!eventListeners.has(kind)) eventListeners.set(kind, new Set());
  const set = eventListeners.get(kind)!;
  set.add(fn as (data: unknown) => void);
  return () => void set.delete(fn as (data: unknown) => void);
}

export async function tauri<T = void>(cmd: string, args?: Record<string, unknown>): Promise<T | undefined> {
  if (!inTauri) return undefined;
  return invoke<T>(cmd, args);
}
