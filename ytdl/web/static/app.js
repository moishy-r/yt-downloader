// UI for both the browser version and the desktop app window.
// All real work happens in the Python server (ytdl.core); this file only talks to /api.
"use strict";

const $ = (id) => document.getElementById(id);
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

let config = null;
let fetched = null;          // result of /api/fetch
let fmt = store.get("fmt") || "mp3";
let quality = null;
let jobId = null;
let source = null;           // EventSource for the running job

// ── helpers ──────────────────────────────────────────────────────────────────
async function api(path, data) {
  const opts = data === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  };
  const res = await fetch(path, opts);
  let json = {};
  try { json = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw new Error(json.error || `Something went wrong (${res.status}).`);
  return json;
}

function fmtDuration(s) {
  if (!s) return "";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = h ? String(m).padStart(2, "0") : m;
  return (h ? h + ":" : "") + mm + ":" + String(sec).padStart(2, "0");
}

function plural(n, word) { return `${n} ${word}${n === 1 ? "" : "s"}`; }

function isDesktop() { return config && config.mode === "desktop"; }

// ── legal notice ─────────────────────────────────────────────────────────────
function setupLegal() {
  $("legal-text").textContent = config.legal.text;
  $("legal-title").textContent = config.legal.title;
  $("legal-short").textContent = config.legal.short;
  if (store.get("legal-ack-v1") === "yes") return;
  $("legal-modal").hidden = false;
  $("legal-check").addEventListener("change", (e) => { $("legal-accept").disabled = !e.target.checked; });
  $("legal-accept").addEventListener("click", () => {
    store.set("legal-ack-v1", "yes");
    $("legal-modal").hidden = true;
    $("url").focus();
  });
}

// ── step 1: fetch ────────────────────────────────────────────────────────────
async function doFetch(e) {
  e.preventDefault();
  const url = $("url").value.trim();
  $("fetch-error").hidden = true;
  if (!url) { showFetchError("Paste a YouTube link first."); return; }
  const btn = $("fetch-btn");
  btn.disabled = true;
  btn.textContent = "Looking up…";
  try {
    fetched = await api("/api/fetch", { url });
    resetResult();
    renderVideos();
    $("videos-card").hidden = $("options-card").hidden = $("go-card").hidden = false;
  } catch (err) {
    showFetchError(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Find videos";
  }
}

function showFetchError(msg) {
  $("fetch-error").textContent = msg;
  $("fetch-error").hidden = false;
}

// ── step 2: video list ───────────────────────────────────────────────────────
function renderVideos() {
  const list = $("video-list");
  list.innerHTML = "";
  const { entries, is_playlist, focus_index } = fetched;

  $("videos-heading").textContent = is_playlist
    ? `${fetched.title} · ${plural(entries.length, "video")}`
    : "Video";
  $("list-tools").hidden = !is_playlist;
  $("filter").value = "";

  if (is_playlist && focus_index) {
    $("focus-note").hidden = false;
    $("focus-note").textContent =
      `Your link points to video ${focus_index} in this playlist, so only that one is selected. ` +
      `Use "Select all" to get the whole playlist.`;
  } else {
    $("focus-note").hidden = true;
  }

  for (const e of entries) {
    const li = document.createElement("li");
    li.dataset.index = e.index;
    li.dataset.title = e.title.toLowerCase();
    if (!e.available) li.classList.add("unavailable");
    if (!is_playlist) li.classList.add("single");

    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = e.available && (!focus_index || e.index === focus_index);
    cb.disabled = !e.available || !is_playlist;
    cb.addEventListener("change", updateCount);
    if (!is_playlist) cb.hidden = true;

    const idx = document.createElement("span");
    idx.className = "idx";
    idx.textContent = is_playlist ? e.index : "";
    const title = document.createElement("span");
    title.className = "title";
    title.textContent = e.title + (e.available ? "" : " (unavailable)");
    title.title = e.title;
    const dur = document.createElement("span");
    dur.className = "dur";
    dur.textContent = fmtDuration(e.duration);
    const state = document.createElement("span");
    state.className = "state";

    label.append(cb, idx, title, dur, state);
    li.append(label);
    list.append(li);
  }
  updateCount();
}

function checkboxes() {
  return [...$("video-list").querySelectorAll("input[type=checkbox]")];
}

function selectedEntries() {
  const chosen = new Set(checkboxes().filter((c) => c.checked)
    .map((c) => Number(c.closest("li").dataset.index)));
  return fetched.entries.filter((e) => chosen.has(e.index));
}

function updateCount() {
  updateFolderHint();
  const n = selectedEntries().length;
  $("sel-count").textContent = `${n} of ${fetched.entries.length} selected`;
  const btn = $("download-btn");
  btn.disabled = n === 0;
  btn.textContent = n === 0 ? "Select at least one video"
    : `Download ${fetched.is_playlist ? plural(n, "video") : ""} as ${fmt.toUpperCase()}`.replace("  ", " ");
}

function setAll(checked) {
  for (const cb of checkboxes()) {
    if (!cb.disabled && !cb.closest("li").hidden) cb.checked = checked;
  }
  updateCount();
}

function applyFilter() {
  const q = $("filter").value.trim().toLowerCase();
  for (const li of $("video-list").children) {
    li.hidden = q !== "" && !li.dataset.title.includes(q);
  }
}

// ── step 3: format / quality / folder ────────────────────────────────────────
function segButtons(container, options, current, onPick) {
  container.innerHTML = "";
  for (const [value, label] of options) {
    const b = document.createElement("button");
    b.type = "button";
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(value === current));
    b.textContent = label;
    b.addEventListener("click", () => onPick(value));
    container.append(b);
  }
}

function renderOptions() {
  segButtons($("fmt-group"), config.formats, fmt, (v) => {
    fmt = v;
    store.set("fmt", v);
    quality = null;
    renderOptions();
    if (fetched) updateCount();
  });
  const valid = config.qualities[fmt].map(([v]) => v);
  if (!valid.includes(quality)) {
    const saved = store.get("quality-" + fmt);
    quality = valid.includes(saved) ? saved : config.default_quality[fmt];
  }
  segButtons($("quality-group"), config.qualities[fmt], quality, (v) => {
    quality = v;
    store.set("quality-" + fmt, v);
    renderOptions();
  });
}

let outDir = "";

function setOutDir(path) {
  outDir = path;
  const parts = path.split(/[\\/]/).filter(Boolean);
  $("out-name").textContent = parts[parts.length - 1] || path;
  $("out-path").textContent = "\u200E" + path;   // LRM keeps the path readable in the rtl box
  $("out-path").title = path;
}

function updateFolderHint() {
  const many = fetched && fetched.is_playlist && selectedEntries().length > 1;
  $("out-hint").textContent = many
    ? `The playlist will be saved in its own folder inside this one: "${fetched.title}"`
    : "";
}

async function browse() {
  $("pick-error").hidden = true;
  const btn = $("browse-btn");
  btn.disabled = true;
  try {
    let picked;
    if (window.pywebview && window.pywebview.api) {
      picked = await window.pywebview.api.pick_folder(outDir);   // desktop app window
    } else {
      picked = (await api("/api/pick-folder", { start: outDir })).path;   // native picker via the local server
    }
    if (picked) {
      setOutDir(picked);
      store.set("out-dir", picked);
    }
  } catch (err) {
    $("pick-error").textContent = err.message;
    $("pick-error").hidden = false;
  } finally {
    btn.disabled = false;
  }
}

// ── step 4: download ─────────────────────────────────────────────────────────
function setLocked(locked) {
  for (const el of document.querySelectorAll("#fetch-form input, #fetch-form button, " +
    "#list-tools input, #list-tools button, #options-card button, #options-card input")) {
    el.disabled = locked;
  }
  for (const cb of checkboxes()) {
    const e = fetched.entries.find((x) => x.index === Number(cb.closest("li").dataset.index));
    cb.disabled = locked || !e.available || !fetched.is_playlist;
  }
}

function rowState(index, symbol, cls) {
  const li = $("video-list").querySelector(`li[data-index="${index}"]`);
  if (!li) return;
  const s = li.querySelector(".state");
  s.textContent = symbol;
  s.className = "state " + (cls || "");
}

async function startDownload() {
  const entries = selectedEntries();
  if (!entries.length) return;

  resetResult();
  for (const e of entries) rowState(e.index, "·", "");
  $("download-btn").hidden = true;
  $("progress").hidden = false;
  $("progress-title").textContent = "Starting…";
  $("progress-stats").textContent = "";
  $("bar-fill").style.width = "0%";
  setLocked(true);

  try {
    const job = await api("/api/jobs", {
      entries, fmt, quality, out_dir: outDir,
      is_playlist: fetched.is_playlist, playlist_title: fetched.title,
    });
    jobId = job.job_id;
    listen(entries);
  } catch (err) {
    setLocked(false);
    $("progress").hidden = true;
    $("download-btn").hidden = false;
    alert(err.message);
  }
}

function listen(entries) {
  const byItem = (ev) => entries[ev.item - 1];
  source = new EventSource(`/api/jobs/${jobId}/events`);
  source.onmessage = (msg) => {
    const ev = JSON.parse(msg.data);
    const count = (ev) => `${ev.item} of ${ev.total}`;
    switch (ev.type) {
      case "item_start":
        rowState(byItem(ev).index, "⟳", "busy");
        $("progress-title").textContent = ev.title;
        $("progress-count").textContent = ev.total > 1 ? `Video ${count(ev)}` : "";
        $("progress-stats").textContent = "";
        break;
      case "progress":
        $("bar-fill").style.width = ev.overall + "%";
        $("progress-stats").textContent =
          [`${Math.floor(ev.percent)}%`, ev.speed, ev.eta && `${ev.eta} left`].filter(Boolean).join(" · ");
        break;
      case "processing":
        $("progress-stats").textContent = "Converting…";
        break;
      case "item_done":
      case "item_skipped":
        rowState(byItem(ev).index, "✓", "ok");
        $("bar-fill").style.width = (ev.item / ev.total * 100) + "%";
        break;
      case "item_failed":
        rowState(byItem(ev).index, "✕", "fail");
        break;
      case "finished":
        source.close();
        showDone(ev);
        break;
    }
  };
  source.onerror = () => {
    // The browser reconnects automatically; nothing to do unless the server is gone.
  };
}

async function cancel() {
  if (!jobId) return;
  $("cancel-btn").disabled = true;
  $("progress-stats").textContent = "Stopping…";
  try { await api(`/api/jobs/${jobId}/cancel`, {}); } catch { /* finished anyway */ }
}

function showDone(ev) {
  setLocked(false);
  // Rows that never finished (stopped) lose their spinner / pending dot
  for (const st of $("video-list").querySelectorAll(".state.busy, .state:not(.ok):not(.fail)")) {
    if (st.textContent) { st.textContent = "–"; st.className = "state"; }
  }
  $("progress").hidden = true;
  $("cancel-btn").disabled = false;
  $("done").hidden = false;

  const saved = ev.files.length, failed = ev.failed.length;
  const msg = $("done-msg");
  msg.className = "done-msg";
  if (ev.cancelled) {
    msg.textContent = `Stopped. ${plural(saved, "file")} saved.`;
  } else if (failed) {
    msg.textContent = `Finished: ${saved} saved, ${failed} couldn't be downloaded.`;
  } else {
    msg.textContent = `✓ Done! ${plural(saved, "file")} saved.`;
    msg.classList.add("ok");
  }

  $("done-path").textContent = saved ? `Saved in ${ev.out_dir}` : "";

  const fl = $("fail-list");
  fl.innerHTML = "";
  for (const f of ev.failed) {
    const li = document.createElement("li");
    li.textContent = `${f.title}: ${f.error}`;
    fl.append(li);
  }

  $("open-folder").hidden = saved === 0;
  const links = $("file-list");
  links.innerHTML = "";
  ev.files.forEach((path, i) => {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = `/api/jobs/${jobId}/files/${i}`;
    a.textContent = path.split(/[\\/]/).pop();
    li.append(a);
    links.append(li);
  });
  // In the desktop app files are already in the folder; browser links are for the web version.
  $("file-links").hidden = isDesktop() || saved === 0;
}

function resetResult() {
  $("done").hidden = true;
  $("progress").hidden = true;
  $("download-btn").hidden = false;
  if (source) source.close();
}

function startOver() {
  resetResult();
  fetched = null;
  jobId = null;
  $("videos-card").hidden = $("options-card").hidden = $("go-card").hidden = true;
  $("url").value = "";
  $("url").focus();
}

// ── boot ─────────────────────────────────────────────────────────────────────
async function init() {
  config = await api("/api/config");
  setupLegal();
  $("version").textContent = `v${config.version}`;
  $("ffmpeg-warning").hidden = config.ffmpeg;

  if (!config.formats.some(([v]) => v === fmt)) fmt = "mp3";
  renderOptions();
  setOutDir(store.get("out-dir") || config.default_out_dir);

  $("fetch-form").addEventListener("submit", doFetch);
  $("sel-all").addEventListener("click", () => setAll(true));
  $("sel-none").addEventListener("click", () => setAll(false));
  $("filter").addEventListener("input", applyFilter);
  $("browse-btn").addEventListener("click", browse);
  $("download-btn").addEventListener("click", startDownload);
  $("cancel-btn").addEventListener("click", cancel);
  $("open-folder").addEventListener("click", () => api(`/api/jobs/${jobId}/open-folder`, {}));
  $("again").addEventListener("click", startOver);
  if (store.get("legal-ack-v1") === "yes") $("url").focus();
}

init().catch((err) => {
  document.body.innerHTML = `<p style="padding:24px">Couldn't start: ${err.message}</p>`;
});
