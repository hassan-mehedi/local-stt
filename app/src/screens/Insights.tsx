import { useEffect, useState } from "react";
import { useApp, useEngineEvent } from "../lib/app";
import { api } from "../lib/engine";
import { number } from "../lib/format";

type Range = "week" | "month" | "all";
type Data = {
  words: number;
  wpm: number;
  streak_days: number;
  longest_streak_days: number;
  heatmap: { date: string; words: number; future: boolean }[];
  wpm_days: { date: string; wpm: number }[];
  apps: { name: string; words: number; share: number }[];
};

const SHADES = ["#EFEFEA", "#C9D5FA", "#8AA5F3", "#4A74EA", "#1F3FB8"];
const STEPS = [1, 150, 350, 750];

function shade(words: number) {
  return SHADES[STEPS.filter((s) => words >= s).length];
}

const days = (n: number) => `${n} ${n === 1 ? "day" : "days"}`;

export default function Insights() {
  const { toast } = useApp();
  const [range, setRange] = useState<Range>("month");
  const [data, setData] = useState<Data | null>(null);

  const load = () => api<Data>(`/api/insights?range=${range}`).then(setData).catch((e) => toast(e.message, true));
  useEffect(() => { load(); }, [range]);
  useEngineEvent("dictation", () => load());

  const topWpm = Math.max(1, ...(data?.wpm_days.map((d) => d.wpm) ?? [1]));
  const stats = data ? [
    [number(data.words), "words dictated"],
    [number(data.wpm), "avg words per minute"],
    [days(data.streak_days), "current streak"],
    [days(data.longest_streak_days), "longest streak"],
  ] : [];

  return (
    <main className="page" style={{ gap: 22 }}>
      <header className="page-head">
        <h1>Insights</h1>
        <div className="segmented" role="group" aria-label="Range">
          {(["week", "month", "all"] as Range[]).map((r) => (
            <button key={r} aria-pressed={range === r} onClick={() => setRange(r)}>
              {r === "all" ? "All time" : r[0].toUpperCase() + r.slice(1)}
            </button>
          ))}
        </div>
      </header>

      <section className="stats" aria-label="Totals">
        {stats.map(([value, label]) => (
          <div key={label} className="card stat">
            <div className="stat-value">{value}</div>
            <div className="stat-label">{label}</div>
          </div>
        ))}
      </section>

      <section className="card card-pad stack gap-12" aria-label="Daily activity">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
          <h2>Words per day</h2><span className="muted" style={{ fontSize: 12 }}>last 26 weeks</span>
        </div>
        <div className="heat">
          {data?.heatmap.map((c) => (
            <span key={c.date} title={c.future ? "" : `${c.date}: ${number(c.words)} words`}
              style={{ background: c.future ? "transparent" : shade(c.words) }} />
          ))}
        </div>
        <div className="legend">0{SHADES.map((s) => <span key={s} style={{ background: s }} />)}750+ words</div>
      </section>

      <div className="two">
        <section className="card card-pad stack gap-12" aria-label="Words by app">
          <h2>Where you dictate</h2>
          {data?.apps.length === 0 && <p className="muted" style={{ margin: 0 }}>Shows up after your first dictation.</p>}
          {data?.apps.map((a) => (
            <div key={a.name} className="app-bar">
              <span className="name" title={a.name}>{a.name}</span>
              <span className="track"><span className="fill" style={{ width: `${a.share * 100}%` }} /></span>
              <span className="n">{Math.round(a.share * 100)}%</span>
            </div>
          ))}
        </section>
        <section className="card card-pad stack gap-12" aria-label="Speed">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
            <h2>Words per minute</h2><span className="muted" style={{ fontSize: 12 }}>last 30 days</span>
          </div>
          <div className="bars">
            {data?.wpm_days.map((d, i) => (
              <span key={d.date} className={i === data.wpm_days.length - 1 ? "today" : ""}
                title={`${d.date}: ${d.wpm} wpm`} style={{ height: `${(d.wpm / topWpm) * 100}%` }} />
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
