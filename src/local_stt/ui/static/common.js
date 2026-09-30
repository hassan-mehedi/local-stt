// Shared by settings.html and onboarding.html.

const TOKEN = new URLSearchParams(location.search).get("token") || "";
const IS_MAC = /Mac/.test(navigator.platform);

const api = (path, opts = {}) => fetch(path, {
  ...opts, headers: { "X-Token": TOKEN, "Content-Type": "application/json" }
});
const post = (path, body = {}) => api(path, { method: "POST", body: JSON.stringify(body) });

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
}

const MAC_MODIFIERS = { ctrl: "⌃", alt: "⌥", shift: "⇧", super: "⌘", cmd: "⌘" };

function fmtHotkey(raw) {
  const parts = raw.replace(/[<>]/g, "").split("+");
  if (IS_MAC) {
    return parts.map(p => MAC_MODIFIERS[p] ?? (p.length === 1 ? p.toUpperCase() : p)).join("");
  }
  return parts.map(p => p.length === 1 ? p.toUpperCase() : p[0].toUpperCase() + p.slice(1)).join("+");
}

function setSeg(id, value) {
  document.querySelectorAll(`#${id} button`).forEach(b =>
    b.classList.toggle("active", b.dataset.v === value));
}

function bindSeg(id, onPick) {
  document.querySelectorAll(`#${id} button`).forEach(b => b.onclick = () => {
    setSeg(id, b.dataset.v);
    onPick(b.dataset.v);
  });
}

// Hotkey capture reads the physical key (e.code), not the typed character,
// so Shift+1 stays "1" and macOS Option+T stays "t" instead of "†".
const NAMED_KEYS = {
  Space: "space", Enter: "enter", Tab: "tab", Backspace: "backspace",
  Delete: "delete", Insert: "insert", Home: "home", End: "end",
  PageUp: "page_up", PageDown: "page_down", Pause: "pause",
  ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right",
  Minus: "-", Equal: "=", BracketLeft: "[", BracketRight: "]",
  Backslash: "\\", Semicolon: ";", Quote: "'", Comma: ",", Period: ".",
  Slash: "/", Backquote: "`",
};
const MODIFIER_CODE = /^(Control|Alt|Shift|Meta|OS)(Left|Right)?$/;

function triggerFromCode(code) {
  let m;
  if ((m = code.match(/^Key([A-Z])$/))) return m[1].toLowerCase();
  if ((m = code.match(/^Digit(\d)$/))) return m[1];
  if ((m = code.match(/^F(\d{1,2})$/)) && +m[1] >= 1 && +m[1] <= 20) return "f" + m[1];
  return NAMED_KEYS[code] ?? null;
}

// Makes a readonly input record a shortcut when clicked. Returns set(raw).
function hotkeyCapture(input, hint, onChange) {
  const idleHint = hint.textContent;
  const end = () => {
    input.classList.remove("capturing");
    input.value = fmtHotkey(input.dataset.raw || "");
    hint.textContent = idleHint;
    hint.classList.remove("err");
  };
  input.onclick = () => {
    input.classList.add("capturing");
    input.value = "press keys…";
    hint.textContent = "Press the shortcut. Esc cancels.";
  };
  input.onblur = () => { if (input.classList.contains("capturing")) end(); };
  input.onkeydown = (e) => {
    if (!input.classList.contains("capturing")) return;
    e.preventDefault();
    if (MODIFIER_CODE.test(e.code)) return; // wait for the trigger key
    if (e.code === "Escape") return end();
    const trigger = triggerFromCode(e.code);
    if (!trigger) {
      hint.textContent = `That key (${e.code}) can't be a hotkey. Try a letter, digit or F-key.`;
      hint.classList.add("err");
      return;
    }
    const mods = [];
    if (e.ctrlKey) mods.push("ctrl");
    if (e.altKey) mods.push("alt");
    if (e.shiftKey) mods.push("shift");
    if (e.metaKey) mods.push("super");
    input.dataset.raw = [...mods.map(m => `<${m}>`), trigger].join("+");
    end();
    onChange(input.dataset.raw);
  };
  return (raw) => { input.dataset.raw = raw; end(); };
}

function fmtSize(mb) {
  if (!mb) return "";
  return mb >= 1000 ? (mb / 1000).toFixed(1) + " GB" : mb + " MB";
}

// Model rows with download/remove buttons and a progress bar.
// opts: chosen (name), onChoose(model), onChanged() after a click,
// filter(model) to hide rows, note(model) for extra meta text,
// noRemove to hide the remove button, flash(text, isErr) for errors.
function renderModels(el, state, opts) {
  el.innerHTML = "";
  for (const m of state.models) {
    if (opts.filter && !opts.filter(m)) continue;
    const row = document.createElement("div");
    row.className = "model" + (m.name === opts.chosen ? " sel" : "") + (m.unavailable ? " off" : "");
    const dl = state.downloading[m.name];
    let right;
    if (m.unavailable) right = `<span class="tag have">unavailable</span>`;
    else if (m.loaded) right = `<span class="tag loaded">loaded</span>`;
    else if (dl === "running") right = `<span class="tag have">downloading…</span>`;
    else if (dl && dl.startsWith("error")) right =
      `<span class="tag failed" title="${escapeHtml(dl)}">failed</span>` +
      `<button class="btn dl" data-dl="${m.name}">retry</button>`;
    else if (m.downloaded) right = opts.noRemove ? `<span class="tag have">ready</span>`
      : `<button class="btn rm" data-rm="${m.name}">remove</button>`;
    else right = `<button class="btn dl" data-dl="${m.name}">download</button>`;
    const meta = m.unavailable || [m.family, m.languages, opts.note?.(m)].filter(Boolean).join(" · ");
    let bar = "";
    if (dl === "running") {
      const p = state.progress[m.name];
      bar = p == null ? `<div class="bar busy"><span></span></div>`
        : `<div class="bar"><span style="width:${Math.round(p * 100)}%"></span></div>`;
    }
    row.innerHTML = `<span class="radio"></span>` +
      `<span class="mname">${m.name}<span class="meta">${escapeHtml(meta)}</span></span>` +
      `<span class="size">${fmtSize(m.size_mb)}</span>${right}${bar}`;
    row.querySelector(".radio").onclick = row.querySelector(".mname").onclick = () => {
      if (m.unavailable) return opts.flash(m.unavailable + ".", true);
      if (!m.downloaded) return opts.flash("Download this model first.", true);
      opts.onChoose(m);
    };
    el.appendChild(row);
  }
  el.querySelectorAll("[data-dl]").forEach(b => b.onclick = async () => {
    await post("/api/models/download", { name: b.dataset.dl });
    opts.onChanged();
  });
  el.querySelectorAll("[data-rm]").forEach(b => b.onclick = async () => {
    await post("/api/models/remove", { name: b.dataset.rm });
    opts.onChanged();
  });
}
