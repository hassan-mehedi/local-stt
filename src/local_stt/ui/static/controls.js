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
const PC_MODIFIERS = { ctrl: "Ctrl", alt: "Alt", shift: "Shift", super: "Super", cmd: "Super" };

function fmtKey(part) {
  const sided = part.match(/^(alt|ctrl|shift|cmd)_([lr])$/);
  if (sided) {
    const name = (IS_MAC ? MAC_MODIFIERS : PC_MODIFIERS)[sided[1]];
    return (sided[2] === "l" ? "Left " : "Right ") + name;
  }
  if (IS_MAC && MAC_MODIFIERS[part]) return MAC_MODIFIERS[part];
  return part.length === 1 ? part.toUpperCase() : part[0].toUpperCase() + part.slice(1);
}

function fmtHotkey(raw) {
  const parts = raw.replace(/[<>]/g, "").split("+").map(fmtKey);
  return parts.join(IS_MAC && !parts.some(p => p.includes(" ")) ? "" : "+");
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
const SIDED_MODIFIERS = {
  AltLeft: "alt_l", AltRight: "alt_r", ControlLeft: "ctrl_l", ControlRight: "ctrl_r",
  ShiftLeft: "shift_l", ShiftRight: "shift_r", MetaLeft: "cmd_l", MetaRight: "cmd_r",
};

function triggerFromCode(code) {
  let m;
  if ((m = code.match(/^Key([A-Z])$/))) return m[1].toLowerCase();
  if ((m = code.match(/^Digit(\d)$/))) return m[1];
  if ((m = code.match(/^F(\d{1,2})$/)) && +m[1] >= 1 && +m[1] <= 20) return "f" + m[1];
  return NAMED_KEYS[code] ?? null;
}

// Makes a readonly input record a shortcut when clicked: a combo like
// Option+Shift+T, or one modifier tapped on its own (Right Option).
// Returns set(raw).
function hotkeyCapture(input, hint, onChange) {
  const idleHint = hint.textContent;
  let lone = null; // the only key held so far, if it is a modifier
  const record = (raw) => {
    input.dataset.raw = raw;
    end();
    onChange(raw);
  };
  const end = () => {
    input.classList.remove("capturing");
    input.value = fmtHotkey(input.dataset.raw || "");
    hint.textContent = idleHint;
    hint.classList.remove("err");
  };
  input.onclick = () => {
    input.classList.add("capturing");
    input.value = "press keys…";
    hint.textContent = "Press the shortcut, or tap one modifier key. Esc cancels.";
    lone = null;
  };
  input.onblur = () => { if (input.classList.contains("capturing")) end(); };
  input.onkeydown = (e) => {
    if (!input.classList.contains("capturing")) return;
    e.preventDefault();
    if (MODIFIER_CODE.test(e.code)) {
      const held = e.ctrlKey + e.altKey + e.shiftKey + e.metaKey;
      lone = held === 1 && SIDED_MODIFIERS[e.code] ? e.code : null;
      return; // wait for the trigger key, or for this modifier's release
    }
    lone = null;
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
    record([...mods.map(m => `<${m}>`), trigger].join("+"));
  };
  input.onkeyup = (e) => {
    if (!input.classList.contains("capturing") || e.code !== lone) return;
    e.preventDefault();
    record(SIDED_MODIFIERS[e.code]);
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
