import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { useApp, useEngineEvent } from "../lib/app";
import { api, HistoryItem, mediaUrl, tauri } from "../lib/engine";
import { clock, dayLabel, greeting, hotkeyLabel, number, plural } from "../lib/format";

type Stats = { week_words: number; week_wpm: number; streak_days: number; week_saved_min: number };
type Page = { items: HistoryItem[]; has_more: boolean };

function groupByDay(items: HistoryItem[]) {
  const groups: { day: string; words: number; items: HistoryItem[] }[] = [];
  for (const item of items) {
    const day = dayLabel(new Date(item.created_at * 1000));
    let group = groups[groups.length - 1];
    if (!group || group.day !== day) {
      group = { day, words: 0, items: [] };
      groups.push(group);
    }
    group.items.push(item);
    group.words += item.words;
  }
  return groups;
}

export default function Home() {
  const { engine, toast } = useApp();
  const [stats, setStats] = useState<Stats | null>(null);
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [playing, setPlaying] = useState<number | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const search = useRef<HTMLInputElement>(null);

  const loadStats = useCallback(() => api<Stats>("/api/stats").then(setStats).catch(() => {}), []);
  const load = useCallback(async (q: string, before?: number) => {
    const params = new URLSearchParams({ q });
    if (before) params.set("before", String(before));
    const page = await api<Page>(`/api/history?${params}`);
    setItems((old) => (before ? [...old, ...page.items] : page.items));
    setHasMore(page.has_more);
  }, []);

  useEffect(() => { loadStats(); }, [loadStats]);
  useEffect(() => {
    const t = window.setTimeout(() => load(query).catch((e) => toast(e.message, true)), query ? 180 : 0);
    return () => window.clearTimeout(t);
  }, [query, load, toast]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        search.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEngineEvent("dictation", ({ item }) => {
    if (!query) setItems((old) => [item, ...old.filter((i) => i.id !== item.id)]);
    loadStats();
  });

  useEffect(() => () => audio.current?.pause(), []);

  const groups = useMemo(() => groupByDay(items), [items]);

  async function remove(item: HistoryItem) {
    await api("/api/history/delete", { id: item.id });
    setItems((old) => old.filter((i) => i.id !== item.id));
    setSelected(null);
    loadStats();
    toast("Deleted");
  }

  async function copy(text: string) {
    await navigator.clipboard.writeText(text);
    toast("Copied");
  }

  async function pasteAgain(item: HistoryItem) {
    await tauri("hide_app");
    const r = await api<{ ok: boolean; error: string | null }>("/api/history/paste", { id: item.id });
    if (!r.ok && r.error) toast(r.error, true);
  }

  function play(item: HistoryItem) {
    audio.current?.pause();
    if (playing === item.id) {
      setPlaying(null);
      return;
    }
    const a = new Audio(mediaUrl(`/api/history/${item.id}/audio`));
    a.onended = () => setPlaying(null);
    a.play().catch((e) => toast(e.message, true));
    audio.current = a;
    setPlaying(item.id);
  }

  const verb = engine?.mode === "hold" ? "Hold" : "Press";
  const cards = stats ? [
    [number(stats.week_words), "words this week"],
    [number(stats.week_wpm), "words per minute"],
    [`${stats.streak_days} ${stats.streak_days === 1 ? "day" : "days"}`, "current streak"],
    [`${stats.week_saved_min} min`, "saved vs typing"],
  ] : [];

  return (
    <main className="page">
      <header className="page-head">
        <div>
          <h1>{greeting()}</h1>
          <p>Everything you dictated, kept on this Mac.</p>
        </div>
        <label className="field" style={{ width: 280 }}>
          <Icon name="search" size={15} />
          <input ref={search} type="search" placeholder="Search history" aria-label="Search history"
            value={query} onChange={(e) => setQuery(e.target.value)} />
          <span className="mono" style={{ fontSize: 11 }}>⌘K</span>
        </label>
      </header>

      <section className="stats" aria-label="This week">
        {cards.map(([value, label]) => (
          <div key={label} className="card stat">
            <div className="stat-value">{value}</div>
            <div className="stat-label">{label}</div>
          </div>
        ))}
      </section>

      <section aria-label="History" className="stack gap-20">
        {groups.length === 0 && (
          <div className="card empty">
            {query ? (
              <span>Nothing matches "{query}".</span>
            ) : (
              <>
                <span className="serif">Nothing dictated yet</span>
                <span>{verb} <span className="kbd">{hotkeyLabel(engine?.hotkey ?? "")}</span> in any app and start talking. The text lands here too.</span>
              </>
            )}
          </div>
        )}
        {groups.map((group) => (
          <div key={group.day} className="stack gap-4">
            <div className="day-head"><span>{group.day}</span><span className="mono">{plural(group.words, "word")}</span></div>
            <div className="card history">
              {group.items.map((item) => {
                const isSelected = selected === item.id;
                return (
                  <div key={item.id} className={`h-row${isSelected ? " selected" : ""}`} tabIndex={0}
                    onClick={() => setSelected(isSelected ? null : item.id)}
                    onKeyDown={(e) => e.key === "Enter" && e.target === e.currentTarget && setSelected(isSelected ? null : item.id)}>
                    <span className="h-time">{clock(new Date(item.created_at * 1000))}</span>
                    <span className="h-app" title={item.app_name ?? ""}>{item.app_name ?? "-"}</span>
                    <div className="h-text stack gap-4">
                      <span className="selectable">{item.text}</span>
                      {isSelected && item.raw_text && (
                        <span className="h-raw selectable">
                          You said: {item.raw_text}{" "}
                          <button onClick={(e) => { e.stopPropagation(); copy(item.raw_text!); }}>Copy</button>
                        </span>
                      )}
                    </div>
                    {isSelected ? (
                      <div className="h-actions" onClick={(e) => e.stopPropagation()}>
                        <button className="icon-btn" aria-label="Copy" title="Copy" onClick={() => copy(item.text)}><Icon name="copy" size={14} /></button>
                        {item.has_audio ? (
                          <button className="icon-btn" aria-label={playing === item.id ? "Stop" : "Play recording"} title="Play recording" onClick={() => play(item)}>
                            <Icon name={playing === item.id ? "pause" : "play"} size={12} />
                          </button>
                        ) : null}
                        <button className="icon-btn" aria-label="Delete" title="Delete" onClick={() => remove(item)}><Icon name="trash" size={14} /></button>
                        <button className="btn primary small" onClick={() => pasteAgain(item)}>Paste again</button>
                      </div>
                    ) : (
                      <span className="h-words">{item.words} w</span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
        {hasMore && (
          <button className="btn" style={{ alignSelf: "center" }} onClick={() => load(query, items[items.length - 1]?.id)}>
            Show older
          </button>
        )}
      </section>
    </main>
  );
}
