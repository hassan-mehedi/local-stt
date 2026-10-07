import { FormEvent, useEffect, useState } from "react";
import { Icon } from "../components/Icon";
import { useApp } from "../lib/app";
import { api } from "../lib/engine";

type Entry = { id: number; kind: Kind; phrase: string; value: string };
type Kind = "words" | "replacements" | "snippets";
type Entries = Record<Kind, Entry[]>;

const TABS: [Kind, string][] = [["words", "Words"], ["replacements", "Replacements"], ["snippets", "Snippets"]];
const HELP: Record<Kind, string> = {
  words: "Names and terms spelled your way. Saying \"local stt\" types local-stt once it is here.",
  replacements: "Swap what the model hears for what you want typed. Use \\n for a new line.",
  snippets: "Say a short trigger, get the whole text. Handy for addresses and templates.",
};

export default function Dictionary() {
  const { toast } = useApp();
  const [entries, setEntries] = useState<Entries>({ words: [], replacements: [], snippets: [] });
  const [tab, setTab] = useState<Kind>("words");
  const [phrase, setPhrase] = useState("");
  const [value, setValue] = useState("");

  const load = () => api<Entries>("/api/dictionary").then(setEntries).catch((e) => toast(e.message, true));
  useEffect(() => { load(); }, []);

  async function add(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/dictionary/add", { kind: tab, phrase, value });
      setPhrase("");
      setValue("");
      await load();
    } catch (err) {
      toast((err as Error).message, true);
    }
  }

  async function remove(entry: Entry) {
    await api("/api/dictionary/delete", { id: entry.id });
    await load();
  }

  const list = entries[tab];
  return (
    <main className="page" style={{ gap: 24 }}>
      <header className="page-head">
        <div>
          <h1>Dictionary</h1>
          <p>Names and terms the model should spell your way, and phrases that expand as you speak.</p>
        </div>
      </header>

      <div className="tabs" role="tablist" aria-label="Dictionary">
        {TABS.map(([kind, label]) => (
          <button key={kind} role="tab" className="tab" aria-selected={tab === kind}
            onClick={() => { setTab(kind); setPhrase(""); setValue(""); }}>
            {label}<span className="count">{entries[kind].length}</span>
          </button>
        ))}
      </div>

      <section className="card card-pad stack gap-16" aria-label={tab}>
        <p className="muted" style={{ margin: 0 }}>{HELP[tab]}</p>
        <form className={tab === "snippets" ? "stack gap-8" : "row gap-8"} onSubmit={add}>
          <label className="field soft" style={{ flexGrow: 1 }}>
            <input type="text" value={phrase} onChange={(e) => setPhrase(e.target.value)}
              aria-label={tab === "words" ? "New word" : tab === "replacements" ? "When I say" : "Trigger phrase"}
              placeholder={tab === "words" ? "Add a word, like a name or product" : tab === "replacements" ? "When I say" : "Trigger, like \"my address\""} />
          </label>
          {tab === "replacements" && (
            <label className="field soft" style={{ flexGrow: 1 }}>
              <input type="text" value={value} onChange={(e) => setValue(e.target.value)} aria-label="Type" placeholder="Type" />
            </label>
          )}
          {tab === "snippets" && (
            <textarea className="input" value={value} onChange={(e) => setValue(e.target.value)} aria-label="Snippet text" placeholder="The text to type" />
          )}
          <button className="btn primary" style={{ height: 40, alignSelf: tab === "snippets" ? "flex-end" : undefined }}
            disabled={!phrase.trim() || (tab !== "words" && !value.trim())}>Add</button>
        </form>

        {list.length === 0 && <p className="muted" style={{ margin: 0 }}>Nothing here yet.</p>}

        {tab === "words" && list.length > 0 && (
          <div className="row gap-8" style={{ flexWrap: "wrap" }}>
            {list.map((w) => (
              <span key={w.id} className="chip">{w.phrase}
                <button aria-label={`Remove ${w.phrase}`} onClick={() => remove(w)}><Icon name="close" size={10} stroke={2.5} /></button>
              </span>
            ))}
          </div>
        )}

        {tab === "replacements" && list.length > 0 && (
          <div className="stack">
            <div className="row muted" style={{ fontSize: 12, paddingBottom: 6, borderBottom: "1px solid var(--line-soft)" }}>
              <span style={{ flex: 1 }}>When I say</span><span style={{ flex: 1 }}>Type</span><span style={{ width: 30 }} />
            </div>
            {list.map((r) => (
              <div key={r.id} className="row" style={{ padding: "8px 0", borderBottom: "1px solid var(--line-soft)" }}>
                <span style={{ flex: 1 }}>{r.phrase}</span>
                <span className="mono" style={{ flex: 1, fontSize: 13 }}>{r.value}</span>
                <button className="icon-btn" aria-label={`Remove ${r.phrase}`} onClick={() => remove(r)}><Icon name="trash" size={14} /></button>
              </div>
            ))}
          </div>
        )}

        {tab === "snippets" && list.length > 0 && (
          <div className="two">
            {list.map((s) => (
              <div key={s.id} className="stack gap-8" style={{ padding: 12, border: "1px solid var(--line-soft)", borderRadius: 10 }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <span className="muted" style={{ fontSize: 13 }}>Say <strong style={{ color: "var(--ink)" }}>"{s.phrase}"</strong></span>
                  <button className="icon-btn" aria-label={`Remove ${s.phrase}`} onClick={() => remove(s)}><Icon name="trash" size={14} /></button>
                </div>
                <div className="selectable" style={{ lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{s.value}</div>
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
