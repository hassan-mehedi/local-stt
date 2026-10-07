import { listen } from "@tauri-apps/api/event";
import { useEffect } from "react";
import { Sidebar } from "./components/Sidebar";
import { useApp, useRoute } from "./lib/app";
import { inTauri, tauri } from "./lib/engine";
import Dictionary from "./screens/Dictionary";
import Home from "./screens/Home";
import Insights from "./screens/Insights";
import Meetings from "./screens/Meetings";
import Onboarding from "./screens/Onboarding";
import Settings from "./screens/Settings";

function Starting() {
  const { info } = useApp();
  if (info?.error) {
    return (
      <div className="ob">
        <div className="ob-card">
          <h1>The engine stopped</h1>
          <p className="lead selectable">{info.error}</p>
          <p className="muted">Its log is in ~/Library/Logs/io.github.hassan-mehedi.local-stt/engine.log.</p>
          <div className="ob-actions">
            <button className="btn primary big" onClick={() => tauri("restart_engine")}>Start it again</button>
          </div>
        </div>
      </div>
    );
  }
  return <div className="empty" style={{ height: "100%", justifyContent: "center" }}><span className="serif">Starting local-stt…</span></div>;
}

export default function App() {
  const { info, state } = useApp();
  const [route, go] = useRoute();

  useEffect(() => {
    if (!inTauri) return;
    const off = listen<string>("navigate", (e) => go(e.payload));
    return () => void off.then((f) => f());
  }, []);

  const onboarding = state && state.platform === "darwin" && !state.onboarding.done;
  useEffect(() => {
    if (onboarding) tauri("open_main");
  }, [onboarding]);

  if (!info?.port || !state) return <><div className="drag" data-tauri-drag-region /><Starting /></>;
  if (onboarding) return <><div className="drag" data-tauri-drag-region /><Onboarding /></>;

  const screen = route.startsWith("/meetings") ? <Meetings route={route} go={go} />
    : route === "/insights" ? <Insights />
    : route === "/dictionary" ? <Dictionary />
    : route === "/settings" ? <Settings />
    : <Home />;
  return (
    <div className="shell">
      <div className="drag" data-tauri-drag-region />
      <Sidebar route={route} go={go} />
      {screen}
    </div>
  );
}
