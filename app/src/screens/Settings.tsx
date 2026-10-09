import { disable, enable, isEnabled } from "@tauri-apps/plugin-autostart";
import { ReactNode, useEffect, useState } from "react";
import { PermissionRows } from "../components/Permissions";
import { ShortcutField } from "../components/Shortcut";
import { ModelInfo, useApp } from "../lib/app";
import { api, inTauri } from "../lib/engine";
import { LANGUAGES, languageName, modelLabel } from "../lib/format";
import { readPillIdle, writePillIdle } from "../pill/prefs";

function Row({ title, hint, children }: { title: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="set-row">
      <div className="set-label"><strong>{title}</strong>{hint && <span>{hint}</span>}</div>
      <div className="row gap-8" style={{ flexShrink: 0 }}>{children}</div>
    </div>
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="toggle">
      <input type="checkbox" role="switch" aria-label={label} checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span />
    </label>
  );
}

function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: [T, string][]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map(([v, text]) => (
        <button key={v} aria-pressed={value === v} onClick={() => value !== v && onChange(v)}>{text}</button>
      ))}
    </div>
  );
}

function languagesFor(model: ModelInfo | undefined): string[] {
  if (!model) return [""];
  if (model.name === "parakeet-tdt-0.6b-v2") return ["en"];
  if (model.name === "bengali-whisper-medium") return ["bn"];
  if (model.languages === "English") return ["en"];
  if (model.family === "parakeet") return ["", ...Object.keys(LANGUAGES).filter((c) => ["en", "de", "es", "fr", "it", "nl", "pt", "ru", "uk", "pl"].includes(c))];
  return Object.keys(LANGUAGES);
}

function size(mb: number) {
  return mb < 1000 ? `${mb} MB` : `${(mb / 1000).toFixed(1)} GB`;
}

function Models() {
  const { state, saveConfig, refresh, toast } = useApp();
  if (!state) return null;
  const current = state.config.model.name;
  // in use first, then downloaded, then the rest in the engine's order
  const rank = (m: ModelInfo) => (m.name === current ? 0 : m.downloaded ? 1 : 2);
  const sorted = state.models.filter((m) => !m.unavailable).sort((a, b) => rank(a) - rank(b));

  async function run(path: string, name: string) {
    try {
      await api(path, { name });
      await refresh();
    } catch (e) {
      toast((e as Error).message, true);
    }
  }

  function use(model: ModelInfo) {
    const langs = languagesFor(model);
    const language = langs.includes(state!.config.model.language) ? state!.config.model.language : langs[0];
    saveConfig({ model: { name: model.name, language } });
  }

  return (
    <div className="stack">
      {sorted.map((m) => {
        const status = state.downloading[m.name];
        const progress = state.progress[m.name];
        return (
          <div key={m.name} className="model">
            <div className="stack gap-4" style={{ flexGrow: 1, minWidth: 0 }}>
              <div className="row gap-8">
                <span className="model-name">{modelLabel(m.name)}</span>
                {m.name === current && <span className="badge ok">In use</span>}
              </div>
              <span className="muted" style={{ fontSize: 12.5 }}>{m.languages} · {size(m.size_mb)}</span>
              {status === "running" && (
                <div className="progress" style={{ marginTop: 4 }}><span style={{ width: `${Math.round((progress ?? 0) * 100)}%` }} /></div>
              )}
              {status?.startsWith("error") && <span className="error-text">{status.slice(7)}</span>}
            </div>
            {status === "running" ? <span className="muted mono" style={{ fontSize: 12 }}>{Math.round((progress ?? 0) * 100)}%</span>
              : !m.downloaded ? <button className="btn small" onClick={() => run("/api/models/download", m.name)}>Download</button>
              : m.name !== current ? <>
                  <button className="btn small" onClick={() => use(m)}>Use</button>
                  <button className="btn small danger" onClick={() => run("/api/models/remove", m.name)}>Remove</button>
                </>
              : null}
          </div>
        );
      })}
    </div>
  );
}

const PRESETS: [string, string, string][] = [
  ["DeepSeek", "https://api.deepseek.com", "deepseek-flash"],
  ["OpenAI", "https://api.openai.com/v1", "gpt-6-luna"],
  ["Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.8-flash"],
  ["Groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"],
  ["Mistral", "https://api.mistral.ai/v1", "mistral-small-latest"],
  ["Together", "https://api.together.ai/v1", "meta-llama/Llama-3.3-70B-Instruct-Turbo"],
  ["OpenRouter", "https://openrouter.ai/api/v1", "deepseek/deepseek-v4.1-flash"],
  ["Ollama", "http://localhost:11434/v1", ""],
];

type TestResult = { ok: boolean; text?: string; error?: string };

function Cleanup() {
  const { state, saveConfig, refresh, toast } = useApp();
  const [url, setUrl] = useState("");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [test, setTest] = useState<TestResult | "running" | null>(null);
  const saved = state?.config.cleanup;
  useEffect(() => {
    if (!saved) return;
    setUrl(saved.api_url);
    setModel(saved.api_model);
  }, [saved?.api_url, saved?.api_model]);

  if (!state || !saved) return null;
  const c = saved;
  const ready = !!(c.api_url && c.api_model);

  async function call(path: string, body: object, done?: string) {
    try {
      await api(path, body);
      await refresh();
      if (done) toast(done);
    } catch (e) {
      toast((e as Error).message, true);
    }
  }

  async function saveApi(e: React.FormEvent) {
    e.preventDefault();
    const api_url = url.trim();
    const api_model = model.trim();
    // the first provider saved turns cleanup on; later edits leave the switch alone
    const firstSetup = !ready && !!(api_url && api_model);
    if (!(await saveConfig({ cleanup: { api_url, api_model, ...(firstSetup && { enabled: true }) } }))) return;
    if (key.trim()) {
      await call("/api/cleanup/key", { url: api_url, key }, "Key saved in the Keychain");
      setKey("");
    }
    setTest(null);
  }

  async function runTest() {
    setTest("running");
    try {
      setTest(await api<TestResult>("/api/cleanup/test", { url: c.api_url, model: c.api_model }));
    } catch (e) {
      setTest({ ok: false, error: (e as Error).message });
    }
  }

  const changed = url.trim() !== c.api_url || model.trim() !== c.api_model || key.trim() !== "";

  return (
    <>
      <Row title="Clean up each dictation" hint={ready
        ? "An AI model removes um, like and false starts, fixes punctuation and writes lists. Your text, not your audio, goes to the API below. History keeps what you said."
        : "Pick a provider below and save its API key first."}>
        <Toggle label="Clean up each dictation" checked={c.enabled} onChange={(enabled) => (ready || !enabled) && saveConfig({ cleanup: { enabled } })} />
      </Row>
      <form className="stack gap-12" style={{ paddingTop: 12 }} onSubmit={saveApi}>
        <div className="row gap-8" style={{ flexWrap: "wrap" }}>
          <span className="muted" style={{ fontSize: 12.5 }}>Fill in for</span>
          {PRESETS.map(([name, presetUrl, presetModel]) => (
            <button key={name} type="button" className="btn small" onClick={() => { setUrl(presetUrl); setModel(presetModel); }}>{name}</button>
          ))}
        </div>
        <label className="field" style={{ height: 36 }}>
          <input aria-label="API URL" placeholder="API URL, e.g. https://api.deepseek.com" value={url} onChange={(e) => setUrl(e.target.value)} />
        </label>
        <label className="field" style={{ height: 36 }}>
          <input aria-label="API model" placeholder="Model, e.g. deepseek-flash" value={model} onChange={(e) => setModel(e.target.value)} />
        </label>
        <label className="field" style={{ height: 36 }}>
          <input aria-label="API key" type="password" autoComplete="off"
            placeholder={state.cleanup.key_saved ? "Key saved in the Keychain. Type to replace it." : "API key (none needed for Ollama)"}
            value={key} onChange={(e) => setKey(e.target.value)} />
        </label>
        <div className="row gap-8">
          <button className="btn small primary" disabled={!changed}>Save</button>
          <button type="button" className="btn small" disabled={!ready || changed || test === "running"} onClick={runTest}>
            {test === "running" ? "Testing..." : "Test"}
          </button>
          {state.cleanup.key_saved && (
            <button type="button" className="btn small danger" onClick={() => call("/api/cleanup/key/delete", { url: c.api_url }, "Key removed")}>Remove key</button>
          )}
        </div>
        {test && test !== "running" && (test.ok
          ? <span style={{ fontSize: 13 }}>Works. "um so this is uh a test of the the cleanup" became "{test.text}"</span>
          : <span className="error-text">{test.error}</span>)}
      </form>
    </>
  );
}

export default function Settings() {
  const { state, saveConfig } = useApp();
  const [autostart, setAutostart] = useState(false);
  const [pillIdle, setPillIdle] = useState(readPillIdle());
  const [folder, setFolder] = useState("");

  useEffect(() => {
    if (inTauri) isEnabled().then(setAutostart).catch(() => {});
  }, []);
  useEffect(() => { if (state) setFolder(state.config.meeting.output_dir); }, [state?.config.meeting.output_dir]);

  if (!state) return null;
  const { dictation, model, meeting } = state.config;
  const modelInfo = state.models.find((m) => m.name === model.name);
  const langs = languagesFor(modelInfo);
  const downloaded = state.models.filter((m) => m.downloaded);

  async function setStartAtLogin(on: boolean) {
    await (on ? enable() : disable());
    setAutostart(await isEnabled());
  }

  return (
    <main className="page" style={{ gap: 20, maxWidth: 860 }}>
      <header className="page-head"><h1>Settings</h1></header>

      <section className="card card-pad stack" aria-label="Dictation">
        <h2 style={{ marginBottom: 14 }}>Dictation</h2>
        <Row title="Shortcut" hint="Works in every app. Click the keys to record a new one.">
          <ShortcutField value={dictation.hotkey} onChange={(hotkey) => saveConfig({ dictation: { hotkey } })} />
        </Row>
        <Row title="How the shortcut works" hint={dictation.mode === "hold" ? "Talk while you hold it, like a walkie-talkie." : "Press once to start, again to stop. Esc throws the clip away."}>
          <Segmented label="Shortcut mode" value={dictation.mode} onChange={(mode) => saveConfig({ dictation: { mode } })}
            options={[["hold", "Hold to talk"], ["toggle", "Press to start and stop"]]} />
        </Row>
        <Row title="Put the text in" hint={dictation.output === "type" ? "Types it key by key. Your clipboard stays as it was." : "Pastes it. Faster for long text; replaces your clipboard."}>
          <Segmented label="Output" value={dictation.output} onChange={(output) => saveConfig({ dictation: { output } })}
            options={[["type", "Type it"], ["clipboard", "Paste it"]]} />
        </Row>
        <Row title="Add a space after each dictation" hint="So the next one doesn't run into it.">
          <Toggle label="Add a space after each dictation" checked={dictation.append_space} onChange={(append_space) => saveConfig({ dictation: { append_space } })} />
        </Row>
        <Row title="Language">
          <select className="select" aria-label="Dictation language" value={model.language} disabled={langs.length < 2}
            onChange={(e) => saveConfig({ model: { language: e.target.value } })}>
            {langs.map((code) => <option key={code} value={code}>{languageName(code)}</option>)}
          </select>
        </Row>
      </section>

      <section className="card card-pad stack" aria-label="Cleanup">
        <h2 style={{ marginBottom: 14 }}>Cleanup</h2>
        <Cleanup />
      </section>

      <section className="card card-pad stack" aria-label="Models">
        <h2>Speech models</h2>
        <p className="muted" style={{ margin: "6px 0 4px" }}>Models run on this Mac. Parakeet v2 is the fastest for English.</p>
        <Models />
      </section>

      <section className="card card-pad stack" aria-label="Meetings">
        <h2 style={{ marginBottom: 14 }}>Meetings</h2>
        <Row title="Save meetings in">
          <form className="row gap-8" onSubmit={(e) => { e.preventDefault(); saveConfig({ meeting: { output_dir: folder } }); }}>
            <label className="field" style={{ width: 260, height: 36 }}>
              <input aria-label="Meetings folder" value={folder} onChange={(e) => setFolder(e.target.value)} />
            </label>
            {folder !== meeting.output_dir && <button className="btn small">Save</button>}
            <button type="button" className="btn small" onClick={() => api("/api/meetings/open-folder", {})}>Show</button>
          </form>
        </Row>
        <Row title="Model for meetings" hint="Bigger models are slower but often better on calls.">
          <select className="select" aria-label="Meeting model" value={meeting.model}
            onChange={(e) => saveConfig({ meeting: { model: e.target.value, language: e.target.value === "bengali-whisper-medium" ? "bn" : "" } })}>
            <option value="">Same as dictation</option>
            {downloaded.map((m) => <option key={m.name} value={m.name}>{modelLabel(m.name)}</option>)}
          </select>
        </Row>
      </section>

      <section className="card card-pad stack gap-12" aria-label="Permissions">
        <h2>Permissions</h2>
        <PermissionRows names={["microphone", "input_monitoring", "accessibility", "system_audio"]} />
      </section>

      <section className="card card-pad stack" aria-label="General">
        <h2 style={{ marginBottom: 14 }}>General</h2>
        <Row title="Open at login">
          <Toggle label="Open at login" checked={autostart} onChange={setStartAtLogin} />
        </Row>
        <Row title="Show the pill while waiting" hint="A small bar at the bottom of the screen. Click it to start a recording.">
          <Toggle label="Show the pill while waiting" checked={pillIdle} onChange={(v) => { writePillIdle(v); setPillIdle(v); }} />
        </Row>
      </section>
    </main>
  );
}
