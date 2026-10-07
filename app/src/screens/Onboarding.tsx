import { useEffect, useState } from "react";
import { Icon } from "../components/Icon";
import { PermissionRows } from "../components/Permissions";
import { Keycaps } from "../components/Shortcut";
import { useApp, useEngineEvent } from "../lib/app";
import { api, tauri } from "../lib/engine";
import { modelLabel } from "../lib/format";

const STEPS = ["welcome", "model", "microphone", "keyboard", "try", "done"] as const;
type Step = (typeof STEPS)[number];

function Welcome({ next }: { next: () => void }) {
  return (
    <>
      <h1>Talk, and it types.</h1>
      <p className="lead">
        local-stt turns your voice into text in any app, and transcribes your meetings.
        The speech model runs on this Mac, so nothing you say leaves it.
      </p>
      <p className="lead">Setup takes about three minutes: one download and three permissions.</p>
      <div className="ob-actions"><button className="btn primary big" onClick={next}>Get started</button></div>
    </>
  );
}

function Model({ next }: { next: () => void }) {
  const { state, refresh, toast } = useApp();
  const name = state!.config.model.name || state!.default_model;
  const model = state!.models.find((m) => m.name === name);
  const status = state!.downloading[name];
  const progress = state!.progress[name] ?? 0;

  async function download() {
    try {
      await api("/api/models/download", { name });
      await refresh();
    } catch (e) {
      toast((e as Error).message, true);
    }
  }

  return (
    <>
      <h1>Download the speech model</h1>
      <p className="lead">
        {modelLabel(name)} understands {model?.languages ?? "speech"} and runs on your Mac's graphics chip.
        It is {((model?.size_mb ?? 0) / 1000).toFixed(1)} GB, downloaded once.
      </p>
      <div className="card card-pad stack gap-12">
        <div className="row gap-12">
          <div className="perm-icon"><Icon name="download" size={18} /></div>
          <div className="stack gap-4" style={{ flexGrow: 1 }}>
            <strong style={{ fontWeight: 500 }}>{modelLabel(name)}</strong>
            <span className="muted" style={{ fontSize: 12.5 }}>
              {model?.downloaded ? "On this Mac" : status === "running" ? `Downloading… ${Math.round(progress * 100)}%` : "Not downloaded yet"}
            </span>
          </div>
          {model?.downloaded ? <span className="check"><Icon name="check" size={13} stroke={3} /></span>
            : status !== "running" && <button className="btn primary" onClick={download}>Download</button>}
        </div>
        {status === "running" && <div className="progress"><span style={{ width: `${Math.round(progress * 100)}%` }} /></div>}
        {status?.startsWith("error") && <span className="error-text">{status.slice(7)}</span>}
      </div>
      <div className="ob-actions">
        <button className="btn primary big" disabled={!model?.downloaded} onClick={next}>Continue</button>
        {!model?.downloaded && <span className="muted">You can keep going once it finishes.</span>}
      </div>
    </>
  );
}

function Microphone({ next }: { next: () => void }) {
  const { perms } = useApp();
  const granted = perms?.status.microphone === "granted";
  return (
    <>
      <h1>Allow the microphone</h1>
      <p className="lead">local-stt listens only while you hold or press your shortcut, or while a meeting records.</p>
      <PermissionRows names={["microphone"]} />
      <div className="ob-actions">
        <button className="btn primary big" disabled={!granted} onClick={next}>Continue</button>
      </div>
    </>
  );
}

function Keyboard({ next }: { next: () => void }) {
  const { perms } = useApp();
  const granted = perms?.status.input_monitoring === "granted" && perms?.status.accessibility === "granted";
  return (
    <>
      <h1>Let it use the keyboard</h1>
      <p className="lead">
        Two switches in System Settings: one so your shortcut works in every app, one so local-stt can type the text for you.
      </p>
      <PermissionRows names={["input_monitoring", "accessibility"]} />
      {!granted && (
        <div className="hint">
          Switched both on and still not allowed here? macOS applies them when local-stt starts again. Setup continues where you left it.
          <div style={{ marginTop: 10 }}>
            <button className="btn small primary" onClick={() => tauri("restart_app")}>Restart local-stt</button>
          </div>
        </div>
      )}
      <div className="ob-actions">
        <button className="btn primary big" disabled={!granted} onClick={next}>Continue</button>
        {!granted && <button className="btn big" onClick={next}>Skip for now</button>}
      </div>
    </>
  );
}

function Try({ next, back }: { next: () => void; back: (step: Step) => void }) {
  const { engine, state, saveConfig, toast } = useApp();
  const [heard, setHeard] = useState<string | null>(null);
  const dictation = state!.config.dictation;

  useEffect(() => {
    if (engine?.dictation === "off" && !engine.error) {
      api<{ ok: boolean; error: string | null }>("/api/dictation/start", {})
        .then((r) => !r.ok && r.error && toast(r.error, true))
        .catch((e) => toast(e.message, true));
    }
  }, []);

  useEngineEvent("dictation", ({ item }) => setHeard(item.text));

  const ready = engine?.dictation && engine.dictation !== "off" && engine.dictation !== "loading";
  return (
    <>
      <h1>Try it</h1>
      <p className="lead">
        Click in the box, {dictation.mode === "hold" ? "hold" : "press"} <Keycaps spec={dictation.hotkey} />,
        say a sentence, then {dictation.mode === "hold" ? "let go" : "press it again"}.
      </p>
      <div className="row gap-12">
        <div className="segmented" role="group" aria-label="Shortcut mode">
          {([["toggle", "Press to start and stop"], ["hold", "Hold to talk"]] as const).map(([mode, text]) => (
            <button key={mode} aria-pressed={dictation.mode === mode} onClick={() => dictation.mode !== mode && saveConfig({ dictation: { mode } })}>{text}</button>
          ))}
        </div>
        <span className="muted" style={{ fontSize: 13 }}>Change the keys later in Settings.</span>
      </div>
      <textarea className="input try" placeholder={ready ? "Your words appear here" : "Loading the model…"} aria-label="Try dictating here" />
      {engine?.error && (
        <div className="hint">
          <span className="error-text">{engine.error}</span>
          <div style={{ marginTop: 10 }}>
            {/not downloaded/.test(engine.error)
              ? <button className="btn small" onClick={() => back("model")}>Back to the download</button>
              : <button className="btn small" onClick={() => back("keyboard")}>Back to permissions</button>}
          </div>
        </div>
      )}
      {heard && (
        <div className="row gap-8"><span className="check"><Icon name="check" size={13} stroke={3} /></span>It heard: <em className="selectable">{heard.trim()}</em></div>
      )}
      <div className="ob-actions">
        <button className="btn primary big" onClick={next}>{heard ? "Continue" : "Skip"}</button>
      </div>
    </>
  );
}

function Done() {
  const { refresh, state } = useApp();
  const hotkey = state!.config.dictation.hotkey;
  async function finish() {
    await api("/api/onboarding/done", {});
    await refresh();
  }
  return (
    <>
      <h1>You're set</h1>
      <p className="lead">
        Use <Keycaps spec={hotkey} /> in any app. A small bar at the bottom of the screen shows when local-stt is listening.
      </p>
      <p className="lead">
        The microphone icon in the menu bar starts meetings and opens this window. Everything you dictate is kept in Home.
      </p>
      <div className="ob-actions"><button className="btn primary big" onClick={finish}>Open local-stt</button></div>
    </>
  );
}

export default function Onboarding() {
  const { state } = useApp();
  const [step, setStep] = useState<Step>(STEPS[Math.min(state?.onboarding.step ?? 0, STEPS.length - 1)]);
  const index = STEPS.indexOf(step);

  function go(to: number) {
    const target = Math.max(0, Math.min(to, STEPS.length - 1));
    setStep(STEPS[target]);
    api("/api/onboarding/step", { step: target }).catch(() => {});
  }
  const next = () => go(index + 1);

  return (
    <div className="ob">
      <div className="ob-card">
        <div className="row gap-12" style={{ justifyContent: "space-between" }}>
          <div className="brand" style={{ padding: 0 }}>
            <div className="brand-mark"><Icon name="mic" size={14} stroke={2.2} /></div>local-stt
          </div>
          {index > 0 && step !== "done" && <button className="btn small" onClick={() => go(index - 1)}>Back</button>}
        </div>
        <div className="ob-steps" aria-label={`Step ${index + 1} of ${STEPS.length}`}>
          {STEPS.map((s, i) => <span key={s} className={i <= index ? "done" : ""} />)}
        </div>
        {step === "welcome" && <Welcome next={next} />}
        {step === "model" && <Model next={next} />}
        {step === "microphone" && <Microphone next={next} />}
        {step === "keyboard" && <Keyboard next={next} />}
        {step === "try" && <Try next={next} back={(to) => go(STEPS.indexOf(to))} />}
        {step === "done" && <Done />}
      </div>
    </div>
  );
}
