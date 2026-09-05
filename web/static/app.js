/* Nuvia dashboard.
   Charts are hand-rolled SVG: no CDN, works offline, and the mark geometry
   is under our control (thin marks, rounded data-ends, hairline chrome). */

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const NS = "http://www.w3.org/2000/svg";

const state = {
  settings: {}, patterns: {}, analytics: null,
  wave: [], todayCount: 0, exercise: null,
};

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}
const post = (p, body) => api(p, {
  method: "POST", headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});
const put = (p, body) => api(p, {
  method: "PUT", headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

const fmtTime = ts => new Date(ts * 1000).toLocaleTimeString([],
  { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const fmtDay = ts => new Date(ts * 1000).toLocaleDateString([],
  { month: "short", day: "numeric" });

/* ==========================================================
   CHART PRIMITIVES
   ========================================================== */

function el(tag, attrs = {}) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function clear(svg) { while (svg.firstChild) svg.removeChild(svg.firstChild); }

// Bars sit on the baseline with only their data-end rounded, so the corner
// radius never implies the value starts above zero.
function barPath(x, y, w, h, r) {
  const rad = Math.min(r, w / 2, h);
  if (h <= 0.5) return `M${x} ${y + h}h${w}`;
  return `M${x} ${y + h}V${y + rad}a${rad} ${rad} 0 0 1 ${rad} ${-rad}`
       + `h${w - 2 * rad}a${rad} ${rad} 0 0 1 ${rad} ${rad}V${y + h}Z`;
}

const tip = () => $("#tip");
function showTip(evt, html) {
  const t = tip();
  t.innerHTML = html;
  t.classList.add("on");
  const pad = 14;
  let x = evt.clientX + pad, y = evt.clientY - 10;
  const box = t.getBoundingClientRect();
  if (x + box.width > innerWidth - 8) x = evt.clientX - box.width - pad;
  if (y + box.height > innerHeight - 8) y = innerHeight - box.height - 8;
  t.style.left = x + "px";
  t.style.top = y + "px";
}
const hideTip = () => tip().classList.remove("on");

function niceMax(v) {
  if (v <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  return Math.ceil(v / mag * 2) / 2 * mag;
}

/** Vertical bars with hairline grid, y-axis ticks and per-bar tooltips. */
function barChart(svg, opts) {
  const { values, labels, tipFor, bands = [], rule = null, dim = () => false } = opts;
  clear(svg);
  const W = svg.clientWidth || 600, H = +svg.getAttribute("height");
  const m = { t: 16, r: 8, b: 24, l: 38 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const max = niceMax(Math.max(...values, 1));

  for (const [from, to] of bands) {
    const x0 = m.l + (from / values.length) * iw;
    const x1 = m.l + (to / values.length) * iw;
    svg.appendChild(el("rect", { class: "band", x: x0, y: m.t, width: x1 - x0, height: ih }));
  }

  for (let i = 0; i <= 4; i++) {
    const y = m.t + ih - (i / 4) * ih;
    svg.appendChild(el("line", { class: i ? "grid-line" : "axis-line",
      x1: m.l, x2: W - m.r, y1: y, y2: y }));
    const t = el("text", { x: m.l - 8, y: y + 4, "text-anchor": "end" });
    t.textContent = Math.round((i / 4) * max);
    svg.appendChild(t);
  }

  const slot = iw / values.length;
  const bw = Math.max(2, slot - 3);          // 2px+ surface gap between bars
  values.forEach((v, i) => {
    const h = (v / max) * ih;
    const x = m.l + i * slot + (slot - bw) / 2;
    const y = m.t + ih - h;
    const p = el("path", { class: "bar" + (dim(i) ? " dim" : ""), d: barPath(x, y, bw, h, 4) });
    svg.appendChild(p);

    const hit = el("rect", { class: "hit", x: m.l + i * slot, y: m.t, width: slot, height: ih });
    hit.addEventListener("mousemove", e => showTip(e, tipFor(i, v)));
    hit.addEventListener("mouseleave", hideTip);
    svg.appendChild(hit);
  });

  labels.forEach((label, i) => {
    if (!label) return;
    const t = el("text", { x: m.l + i * slot + slot / 2, y: H - 7, "text-anchor": "middle" });
    t.textContent = label;
    svg.appendChild(t);
  });

  if (rule !== null && rule.at >= 0 && rule.at <= values.length) {
    const x = m.l + (rule.at / values.length) * iw;
    svg.appendChild(el("line", { class: "rule", x1: x, x2: x, y1: m.t, y2: m.t + ih }));
    // Anchor away from the right edge so the text never overflows the frame.
    const flip = x > W - m.r - 60;
    const t = el("text", { x: x + (flip ? -6 : 6), y: m.t - 1,
      "text-anchor": flip ? "end" : "start", fill: "var(--ink-2)" });
    t.textContent = rule.label;
    svg.appendChild(t);
  }
}

/** Single-series line with markers and a crosshair tooltip. */
function lineChart(svg, opts) {
  const { points, tipFor, xLabel = i => "" } = opts;
  clear(svg);
  const W = svg.clientWidth || 600, H = +svg.getAttribute("height");
  const m = { t: 12, r: 12, b: 24, l: 42 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  if (!points.length) return;

  const max = niceMax(Math.max(...points, 1));
  const min = 0;
  const xAt = i => m.l + (points.length === 1 ? iw / 2 : (i / (points.length - 1)) * iw);
  const yAt = v => m.t + ih - ((v - min) / (max - min)) * ih;

  for (let i = 0; i <= 4; i++) {
    const y = m.t + ih - (i / 4) * ih;
    svg.appendChild(el("line", { class: i ? "grid-line" : "axis-line",
      x1: m.l, x2: W - m.r, y1: y, y2: y }));
    const t = el("text", { x: m.l - 8, y: y + 4, "text-anchor": "end" });
    t.textContent = Math.round((i / 4) * max);
    svg.appendChild(t);
  }

  const d = points.map((v, i) => `${i ? "L" : "M"}${xAt(i)} ${yAt(v)}`).join("");
  svg.appendChild(el("path", { class: "line", d }));

  points.forEach((v, i) => {
    const c = el("circle", { cx: xAt(i), cy: yAt(v), r: 4,
      fill: "var(--series-1)", stroke: "var(--surface)", "stroke-width": 2 });
    svg.appendChild(c);
    const hit = el("rect", { class: "hit", x: xAt(i) - 12, y: m.t, width: 24, height: ih });
    hit.addEventListener("mousemove", e => showTip(e, tipFor(i, v)));
    hit.addEventListener("mouseleave", hideTip);
    svg.appendChild(hit);
  });

  points.forEach((v, i) => {
    const label = xLabel(i);
    if (!label) return;
    const t = el("text", { x: xAt(i), y: H - 7, "text-anchor": "middle" });
    t.textContent = label;
    svg.appendChild(t);
  });
}

/** Scrolling envelope for the live view. */
function drawWave(svg, series, gate) {
  clear(svg);
  const W = svg.clientWidth || 600, H = +svg.getAttribute("height");
  const m = { t: 10, r: 8, b: 8, l: 38 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const max = Math.max(120, ...series) * 1.15;

  for (let i = 0; i <= 3; i++) {
    const y = m.t + ih - (i / 3) * ih;
    svg.appendChild(el("line", { class: i ? "grid-line" : "axis-line",
      x1: m.l, x2: W - m.r, y1: y, y2: y }));
    const t = el("text", { x: m.l - 8, y: y + 4, "text-anchor": "end" });
    t.textContent = Math.round((i / 3) * max);
    svg.appendChild(t);
  }

  const gy = m.t + ih - (gate / max) * ih;
  if (gy > m.t && gy < m.t + ih) {
    svg.appendChild(el("line", { class: "rule", x1: m.l, x2: W - m.r, y1: gy, y2: gy }));
    const t = el("text", { x: W - m.r, y: gy - 6, "text-anchor": "end" });
    t.textContent = `gate ${gate}`;
    svg.appendChild(t);
  }

  if (series.length > 1) {
    const xAt = i => m.l + (i / (series.length - 1)) * iw;
    const yAt = v => m.t + ih - Math.min(v / max, 1) * ih;
    const d = series.map((v, i) => `${i ? "L" : "M"}${xAt(i)} ${yAt(v)}`).join("");
    svg.appendChild(el("path", { class: "line", d, "stroke-width": 1.5 }));
    svg.appendChild(el("path", {
      d: d + `L${xAt(series.length - 1)} ${m.t + ih}L${xAt(0)} ${m.t + ih}Z`,
      fill: "var(--wash)", stroke: "none" }));
  }
}

/* ==========================================================
   THEME
   ========================================================== */

function applyTheme(theme) {
  if (theme) document.documentElement.setAttribute("data-theme", theme);
  else document.documentElement.removeAttribute("data-theme");
}

const urlTheme = new URLSearchParams(location.search).get("theme");
applyTheme(urlTheme || localStorage.getItem("nuvia-theme") || null);

$("#themeToggle").addEventListener("click", () => {
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const current = document.documentElement.getAttribute("data-theme")
    || (dark ? "dark" : "light");
  const next = current === "dark" ? "light" : "dark";
  localStorage.setItem("nuvia-theme", next);
  applyTheme(next);
  if (!$("[data-page=analytics]").hidden && state.analytics) loadAnalytics();
});

/* ==========================================================
   NAVIGATION
   ========================================================== */

function show(view, push = true) {
  if (push && location.hash.slice(1) !== view) location.hash = view;
  $$("#nav button").forEach(b =>
    b.setAttribute("aria-current", String(b.dataset.view === view)));
  $$("[data-page]").forEach(s => s.hidden = s.dataset.page !== view);
  if (view === "analytics") loadAnalytics();
  if (view === "training") loadTraining();
  if (view === "patterns") loadCalibration();
  if (view === "data") loadData();
}
$("#nav").addEventListener("click", e => {
  const b = e.target.closest("button");
  if (b) show(b.dataset.view);
});
// Deep-linkable views, so a tab can be shared or reloaded in place.
addEventListener("hashchange", () => {
  const view = location.hash.slice(1);
  if (view) show(view, false);
});

/* ==========================================================
   MONITOR
   ========================================================== */

const recentBreaths = [];
const recentWords = [];

function renderSlots(pattern) {
  const wrap = $("#slots");
  wrap.innerHTML = "";
  for (let i = 0; i < 3; i++) {
    const s = document.createElement("div");
    const ch = pattern[i];
    s.className = "slot" + (ch ? "" : " empty");
    if (ch) {
      const g = document.createElement("span");
      g.className = ch === "." ? "g-dot" : "g-dash";
      s.appendChild(g);
    }
    wrap.appendChild(s);
  }
}

function renderRecent() {
  const host = $("#recentBreaths");
  if (!recentBreaths.length) {
    host.innerHTML = `<div class="empty">No breaths yet. Breathe into the
      sensor and they will appear here.</div>`;
    return;
  }
  host.innerHTML = `<table><thead><tr><th>Time</th><th>Type</th>
    <th>Duration</th><th>Peak</th></tr></thead><tbody>${
    recentBreaths.slice(0, 8).map(b => `<tr>
      <td>${fmtTime(b.ts)}</td>
      <td class="n">${b.symbol === "." ? "Short" : "Long"}</td>
      <td class="n">${Math.round(b.duration_ms)} ms</td>
      <td>${b.peak}</td></tr>`).join("")}</tbody></table>`;
}

function renderWords() {
  const host = $("#recentWords");
  if (!recentWords.length) {
    host.innerHTML = `<div class="empty">No completed patterns yet.</div>`;
    return;
  }
  host.innerHTML = `<table><thead><tr><th>Time</th><th>Pattern</th>
    <th>Word</th></tr></thead><tbody>${
    recentWords.slice(0, 8).map(w => `<tr>
      <td>${fmtTime(w.ts)}</td>
      <td class="mono">${w.pattern}</td>
      <td class="n">${w.word || '<span class="muted">unassigned</span>'}</td>
      </tr></tr>`).join("")}</tbody></table>`;
}

/* ==========================================================
   ANALYTICS
   ========================================================== */

async function loadAnalytics() {
  const a = await api("/api/analytics");
  state.analytics = a;

  $("#aTotal").textContent = a.total;
  $("#aMeanDur").innerHTML = `${Math.round(a.duration.mean)}<span class="unit"> ms</span>`;
  $("#aMeanPeak").textContent = Math.round(a.peak.mean);
  $("#aAnom").textContent = a.anomalies.length;

  const night = a.hourly.slice(22).concat(a.hourly.slice(0, 6))
    .reduce((s, v) => s + v, 0);
  $("#coverageNote").innerHTML = night === 0
    ? `<b>No overnight data.</b> Nothing was recorded between 22:00 and 06:00.
       A piezo at a mouthpiece only registers breath directed into it, so
       night coverage needs a worn sensor &mdash; a chest belt, or an
       accelerometer on the sternum.`
    : `${night} breaths recorded overnight (22:00&ndash;06:00) across the
       period.`;

  barChart($("#hourChart"), {
    values: a.hourly,
    labels: a.hourly.map((_, i) => i % 3 === 0 ? String(i).padStart(2, "0") : ""),
    bands: [[22, 24], [0, 6]],
    tipFor: (i, v) => `<b>${String(i).padStart(2, "0")}:00</b><br>${v} breaths`
      + (a.hourly_mean_duration[i] ? `<br>mean ${a.hourly_mean_duration[i]} ms` : ""),
  });

  const thr = state.settings.threshold_ms || 1000;
  barChart($("#durChart"), {
    values: a.duration_bins,
    labels: a.duration_bins.map((_, i) => i % 3 === 0 ? `${(i * 0.2).toFixed(1)}s` : ""),
    rule: { at: thr / 200, label: `${Math.round(thr)} ms` },
    tipFor: (i, v) => `<b>${i * 200}&ndash;${i * 200 + 200} ms</b><br>${v} breaths`,
  });

  const daily = a.daily;
  const trendHost = $("#trendChart");
  if (daily.length === 1) {
    clear(trendHost);
    $("#trendNote").innerHTML = `<div class="empty">One day of data so far
      (mean peak <b>${Math.round(daily[0].mean_peak)}</b>). A trend needs at
      least two days.</div>`;
  } else if (daily.length) {
    $("#trendNote").innerHTML = "";
    lineChart($("#trendChart"), {
      points: daily.map(d => d.mean_peak),
      xLabel: i => (i === 0 || i === daily.length - 1)
        ? daily[i].day.slice(5) : "",
      tipFor: (i, v) => `<b>${daily[i].day}</b><br>mean peak ${v}<br>
        ${daily[i].count} breaths`,
    });
  } else {
    clear(trendHost);
    $("#trendNote").innerHTML = `<div class="empty">No data yet.</div>`;
  }

  const host = $("#anomalyList");
  host.innerHTML = a.anomalies.length
    ? `<table><thead><tr><th>When</th><th>Type</th><th>Detail</th></tr></thead>
       <tbody>${a.anomalies.slice(0, 20).map(x => `<tr>
         <td>${fmtDay(x.ts)} ${fmtTime(x.ts)}</td>
         <td><span class="pill ${x.severity}"><i></i>${x.kind}</span></td>
         <td>${x.detail}</td></tr>`).join("")}</tbody></table>`
    : `<div class="empty">No anomalies flagged. This needs a few dozen
       breaths before the baseline is meaningful.</div>`;
}

/* ==========================================================
   TRAINING
   ========================================================== */

const EXERCISES = {
  sustained: {
    title: "Lift",
    prompt: "Breathe out steadily and hold the float in the blue zone.",
    unit: "s",
    reps: 4,
    targetOf: best => Math.max(8, Math.round(best / 1000) + 1),
    make: (canvas, best) =>
      new RespGames.LiftGame(canvas, EXERCISES.sustained.targetOf(best)),
    // Score is the longest hold, in milliseconds.
    score: g => Math.round(g.best * 1000),
    fmt: v => (v / 1000).toFixed(1) + " s",
    target: best => `${EXERCISES.sustained.targetOf(best)} s hold`,
  },
  peak: {
    title: "Surge",
    prompt: "Five short, forceful breaths. Push past the orange line.",
    unit: "peak",
    reps: 5,
    make: (canvas, best) => new RespGames.SurgeGame(canvas,
      Math.max(200, Math.round((best || 200) * 1.05 / 10) * 10)),
    score: g => Math.round(g.best),
    fmt: v => String(v),
    target: best => String(Math.max(200, Math.round((best || 200) * 1.05 / 10) * 10)),
  },
  rhythm: {
    title: "Cadence",
    prompt: "Match each note as it reaches the line: circle = short, bar = long.",
    unit: "hits",
    reps: 6,
    sequence: [".", "-", ".", "-", "-", "."],
    make: canvas => new RespGames.CadenceGame(canvas, [".", "-", ".", "-", "-", "."]),
    score: g => g.hits,
    fmt: v => `${v}/6`,
    target: () => "6 of 6",
  },
};

let activeGame = null;

async function loadTraining() {
  const { sessions } = await api("/api/training");
  state.trainingHistory = sessions;

  // Each exercise is measured in a different unit, so they get their own
  // charts. Putting seconds and ADC counts on one axis would invent a
  // relationship that is not there.
  const host = $("#trainCharts");
  const keys = Object.keys(EXERCISES);
  host.innerHTML = keys.map(k => `
    <div>
      <div class="k" style="font-size:11px;letter-spacing:.05em;
           text-transform:uppercase;color:var(--ink-muted);margin-bottom:6px">
        ${EXERCISES[k].title} <span style="text-transform:none">
        (${EXERCISES[k].unit})</span></div>
      <svg class="chart" id="tc-${k}" height="120"></svg>
      <div id="tce-${k}"></div>
    </div>`).join("");

  keys.forEach(k => {
    const rows = sessions.filter(x => x.exercise === k).reverse();
    const svg = $(`#tc-${k}`);
    if (rows.length >= 2) {
      $(`#tce-${k}`).innerHTML = "";
      lineChart(svg, {
        points: rows.map(r => r.score),
        xLabel: i => (i === 0 || i === rows.length - 1) ? fmtDay(rows[i].ts) : "",
        tipFor: (i, v) => `<b>${EXERCISES[k].fmt(v)}</b><br>${fmtDay(rows[i].ts)}`,
      });
    } else {
      clear(svg);
      $(`#tce-${k}`).innerHTML = `<div class="empty" style="padding:16px">${
        rows.length ? `Best so far <b>${EXERCISES[k].fmt(rows[0].score)}</b>.
        One more session and a trend appears.` : "Not played yet."}</div>`;
    }
  });

  // best-so-far on each card
  keys.forEach(k => {
    const rows = sessions.filter(x => x.exercise === k);
    const el = $(`[data-best="${k}"]`);
    if (el) el.textContent = rows.length
      ? `Best ${EXERCISES[k].fmt(Math.max(...rows.map(r => r.score)))}` : "";
  });
}

$$("[data-ex]").forEach(b =>
  b.addEventListener("click", () => startExercise(b.dataset.ex)));
$("#exQuit").addEventListener("click", () => endExercise(true));

function startExercise(key) {
  const def = EXERCISES[key];
  const prior = (state.trainingHistory || [])
    .filter(s => s.exercise === key).map(s => s.score);
  const best = prior.length ? Math.max(...prior) : 0;

  state.exercise = { key, def, results: [], best };

  $("#exerciseHome").hidden = true;
  $("#exerciseRun").hidden = false;
  $("#exTitle").textContent = def.title;
  $("#exPrompt").textContent = def.prompt;
  $("#exTarget").textContent = def.target(best);
  $("#exScore").textContent = "0";
  $("#exLast").textContent = "\u2014";
  renderStreak();

  activeGame = def.make($("#gameCanvas"), best);
  activeGame.start();
}

function renderStreak() {
  const ex = state.exercise;
  if (!ex) return;
  const wrap = $("#exStreak");
  wrap.innerHTML = "";
  for (let i = 0; i < ex.def.reps; i++) {
    const bar = document.createElement("i");
    const r = ex.results[i];
    if (r) bar.className = r.hit ? "hit" : "miss";
    wrap.appendChild(bar);
  }
}

function exerciseBreath(breath) {
  const ex = state.exercise;
  if (!ex || !activeGame) return;

  activeGame.feedBreath(breath);
  $("#exLast").textContent = `${Math.round(breath.duration_ms)} ms`;

  let hit;
  if (ex.key === "rhythm") {
    hit = ex.results.length < ex.def.sequence.length
      && breath.symbol === ex.def.sequence[ex.results.length];
  } else if (ex.key === "peak") {
    hit = breath.peak >= activeGame.target;
  } else {
    hit = activeGame.best >= activeGame.target;
  }

  ex.results.push({ hit });
  $("#exScore").textContent = ex.def.fmt(ex.def.score(activeGame));
  renderStreak();

  if (ex.results.length >= ex.def.reps) setTimeout(() => endExercise(false), 900);
}

async function endExercise(aborted) {
  const ex = state.exercise;
  const game = activeGame;
  state.exercise = null;
  activeGame = null;
  if (game) game.stop();

  $("#exerciseRun").hidden = true;
  $("#exerciseHome").hidden = false;

  if (ex && game && !aborted) {
    await post("/api/training", {
      exercise: ex.key,
      score: ex.def.score(game),
      reps: ex.results.length,
      detail: { hits: ex.results.filter(r => r.hit).length },
    });
  }
  loadTraining();
}

/* ==========================================================
   PATTERNS
   ========================================================== */

const ALL_PATTERNS = ["...", "..-", ".-.", ".--", "-..", "-.-", "--.", "---"];

function renderPatternEditor() {
  const host = $("#patternEditor");
  host.innerHTML = `<table><thead><tr><th>Pattern</th><th>Word</th></tr></thead>
    <tbody>${ALL_PATTERNS.map(p => `<tr>
      <td class="mono" style="font-size:16px">${p.replace(/\./g, "&bull;").replace(/-/g, "&mdash;")}</td>
      <td><input type="text" data-pattern="${p}" value="${state.patterns[p] || ""}"
          placeholder="unassigned" maxlength="12"></td>
    </tr>`).join("")}</tbody></table>`;
}

$("#savePatterns").addEventListener("click", async () => {
  const items = {};
  $$("[data-pattern]").forEach(i => {
    const v = i.value.trim().toUpperCase();
    if (v) items[i.dataset.pattern] = v;
  });
  const { patterns } = await put("/api/patterns", items);
  state.patterns = patterns;
  $("#patternMsg").textContent = "Saved.";
  setTimeout(() => $("#patternMsg").textContent = "", 2500);
});

function renderSettings() {
  const fields = [
    ["gate", "Gate", "ADC counts that count as breath"],
    ["hold_ms", "Hold", "ms of silence before a breath closes"],
    ["threshold_ms", "Short / long", "ms; set by calibration"],
    ["min_breath_ms", "Minimum", "ms; anything shorter is a glitch"],
    ["pattern_timeout_ms", "Pattern timeout", "ms between breaths in one word"],
  ];
  $("#settingsForm").innerHTML = fields.map(([k, label, help]) => `
    <div style="margin-bottom:10px">
      <div style="font-size:12px;margin-bottom:4px">${label}
        <span class="muted">&mdash; ${help}</span></div>
      <input type="number" data-setting="${k}" value="${state.settings[k]}">
    </div>`).join("");
}

$("#saveSettings").addEventListener("click", async () => {
  const items = {};
  $$("[data-setting]").forEach(i => items[i.dataset.setting] = Number(i.value));
  const { settings } = await put("/api/settings", items);
  state.settings = settings;
  $("#mThresh").innerHTML =
    `${Math.round(settings.threshold_ms)}<span class="unit"> ms</span>`;
  $("#settingsMsg").textContent = "Saved.";
  setTimeout(() => $("#settingsMsg").textContent = "", 2500);
});

/* --- calibration --- */

$("#openCal").addEventListener("click", () => RespCalibrate.open());

async function loadCalibration() {
  renderPatternEditor();
  renderSettings();
  const { samples } = await api("/api/calibration");
  const host = $("#calSummary");
  if (!samples.length) {
    host.innerHTML = `<div class="empty">Not calibrated yet. Nuvia is using
      the default ${Math.round(state.settings.threshold_ms)} ms threshold.</div>`;
    return;
  }
  const by = { short: [], long: [] };
  samples.forEach(s => by[s.label].push(s.duration_ms));
  const sMax = by.short.length ? Math.max(...by.short) : null;
  const lMin = by.long.length ? Math.min(...by.long) : null;
  const clean = sMax !== null && lMin !== null && sMax < lMin;
  host.innerHTML = `
    <div class="cal-summary">
      <div><span>Threshold</span><b>${Math.round(state.settings.threshold_ms)} ms</b></div>
      <div><span>Short (${by.short.length})</span>
        <b>${by.short.map(Math.round).join(", ") || "&mdash;"}</b></div>
      <div><span>Long (${by.long.length})</span>
        <b>${by.long.map(Math.round).join(", ") || "&mdash;"}</b></div>
    </div>
    ${clean
      ? `<p class="cal-note" style="margin-top:10px">Clean separation,
         ${Math.round(lMin - sMax)} ms of margin.</p>`
      : (sMax !== null && lMin !== null
        ? `<p class="cal-warn" style="margin-top:10px">The two classes overlap.
           Recalibrate, making long breaths noticeably longer.</p>` : "")}`;
}

$("#clearCal").addEventListener("click", async () => {
  await fetch("/api/calibration", { method: "DELETE" });
  loadCalibration();
});

/* ==========================================================
   DATA - raw stream, recording, exports
   ========================================================== */

const RAW = { lines: [], paused: false, hex: false, max: 1200 };

function rawRender() {
  const box = $("#rawBox");
  if (!box || $("[data-page=data]").hidden) return;
  const tail = RAW.lines.slice(-260);
  box.textContent = RAW.hex
    ? tail.map(v => v.toString(16).padStart(3, "0")).join(" ")
    : tail.map(v => `ADC:${v}`).join("\n");
  box.scrollTop = box.scrollHeight;
}

$("#rawPause").addEventListener("click", e => {
  RAW.paused = !RAW.paused;
  e.target.textContent = RAW.paused ? "Resume" : "Pause";
});
$("#rawHex").addEventListener("click", e => {
  RAW.hex = !RAW.hex;
  e.target.textContent = RAW.hex ? "Decimal" : "Hex";
  rawRender();
});
$("#rawSave").addEventListener("click", e => {
  const text = RAW.lines.map(v => `ADC:${v}`).join("\n");
  e.target.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
});

$("#recToggle").addEventListener("click", async () => {
  const on = $("#recToggle").dataset.on === "1";
  const r = await post("/api/record", { action: on ? "stop" : "start" });
  applyRecState(r);
  loadData();
});

function applyRecState(r) {
  const btn = $("#recToggle");
  btn.dataset.on = r.recording ? "1" : "0";
  btn.textContent = r.recording ? "Stop recording" : "Start recording";
  $("#recStatus").innerHTML = r.recording
    ? `<span class="rec-live">recording</span> ${r.name} &middot; ${r.samples} samples`
    : "";
}

async function loadData() {
  rawRender();
  const [{ files, recording }, a] = await Promise.all([
    api("/api/recordings"), api("/api/analytics"),
  ]);
  applyRecState({ recording, name: "", samples: 0 });

  $("#recList").innerHTML = files.length
    ? files.slice(0, 8).map(f => `<div class="recfile">
        <span class="mono">${f}</span>
        <button class="theme-toggle" data-replay="${f}"
                style="margin-left:auto">replay</button>
        <a href="/api/recordings/${f}" download>download</a>
      </div>`).join("")
    : `<div class="empty">No sessions recorded yet.</div>`;

  $$("[data-replay]").forEach(b => b.addEventListener("click", () => replay(b.dataset.replay)));

  $("#exportSummary").innerHTML = `<div class="cal-summary">
    <div><span>Breaths</span><b>${a.total}</b></div>
    <div><span>Words</span><b>${(await api("/api/words")).words.length}</b></div>
  </div>`;
}

// Run a recording back through the detector at the current threshold. This is
// breath_live.py --replay: tune the numbers without breathing again.
async function replay(file) {
  const host = $("#replayOut");
  host.innerHTML = `<div class="muted">replaying ${file}\u2026</div>`;
  const r = await post("/api/replay", { file });
  if (r.error) { host.innerHTML = `<div class="cal-warn">${r.error}</div>`; return; }

  const shorts = r.breaths.filter(b => b.symbol === ".").length;
  host.innerHTML = `
    <div class="cal-summary">
      <div><span>Threshold</span><b>${Math.round(r.threshold_ms)} ms</b></div>
      <div><span>Breaths</span><b>${r.breaths.length}
        (${shorts} short, ${r.breaths.length - shorts} long)</b></div>
      <div><span>Words</span><b>${r.words.map(w => w.word || w.pattern).join(", ")
        || "&mdash;"}</b></div>
    </div>
    <div class="mono" style="margin-top:10px;font-size:12px;color:var(--ink-muted)">
      ${r.breaths.map(b => `${b.symbol}${Math.round(b.duration_ms)}`).join("  ")}
    </div>`;
}

/* ==========================================================
   LIVE STREAM
   ========================================================== */

// errno -> what the user should actually do about it. An echoed
// "[Errno 112] Host is down" tells them nothing.
const CONNECTION_HELP = {
  112: {                       // EHOSTDOWN
    title: "The sensor is not transmitting",
    why: "Bluetooth is working here, but nothing is answering at that address.",
    steps: ["Check the Arduino has power",
            "Check the HC-05 LED is blinking rapidly",
            "Move within a few metres of the computer"],
  },
  113: {                       // EHOSTUNREACH
    title: "The sensor is out of range",
    why: "The device was found but could not be reached.",
    steps: ["Move closer to the computer", "Check for anything blocking the signal"],
  },
  16: {                        // EBUSY
    title: "Something else is holding the connection",
    why: "Another program on this computer already has the serial port open.",
    steps: ["Close breath_live.py or bluetooth_rec.py if either is running",
            "Then reload this page"],
  },
  111: {                       // ECONNREFUSED
    title: "The sensor refused the connection",
    why: "HC-05 accepts one master at a time and is already paired to something.",
    steps: ["Disconnect it from your phone or any other laptop",
            "Turn Bluetooth off on that device if unsure"],
  },
};

function setStatus(state, info) {
  const text = state === "disconnected" && info && info.detail
    ? "disconnected" : state;
  $("#statusText").textContent = text;
  const dot = $("#statusDot");
  dot.className = "dot " + (
    state === "connected" ? "live" :
    state === "demo" ? "warn" :
    state === "disconnected" ? "down" : "");

  renderConnectionPanel(state, info);
}

// A dashboard with no data and no explanation reads as broken software. Say
// what is wrong and what to do, on the page rather than in a sidebar label.
function renderConnectionPanel(state, info) {
  const host = $("#connPanel");
  if (!host) return;

  if (state === "connected" || state === "demo") {
    host.innerHTML = "";
    host.hidden = true;
    return;
  }
  host.hidden = false;

  if (state === "connecting" || state === "reconnecting") {
    host.innerHTML = `<div class="conn"><div class="conn-title">
      Looking for the sensor\u2026</div></div>`;
    return;
  }

  const help = (info && CONNECTION_HELP[info.errno]) || {
    title: "Cannot reach the sensor",
    why: info && info.detail ? info.detail : "",
    steps: ["Check the device has power and is in range"],
  };

  host.innerHTML = `
    <div class="conn">
      <div class="conn-title"><span class="dot down"></span>${help.title}</div>
      ${help.why ? `<p class="conn-why">${help.why}</p>` : ""}
      <ul class="conn-steps">${help.steps.map(x => `<li>${x}</li>`).join("")}</ul>
      <p class="conn-why">Retrying every 3 seconds. To explore the interface
        without hardware, restart the server with
        <code>--demo</code>.</p>
      ${info && info.detail ? `<p class="conn-raw">${info.detail}</p>` : ""}
    </div>`;
}

function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);

  ws.onmessage = ev => {
    const { type, data } = JSON.parse(ev.data);

    if (type === "status") {
      window.__lastStatus = data.state;
      setStatus(data.state, data);
      RespOnboarding.status(data.state);

    } else if (type === "raw") {
      if (!RAW.paused) {
        RAW.lines.push(...data.v);
        if (RAW.lines.length > RAW.max) RAW.lines.splice(0, RAW.lines.length - RAW.max);
        rawRender();
      }

    } else if (type === "wave") {
      RespCalibrate.onWave(data, state.settings.gate || 30);
      if (activeGame) activeGame.feedLevel(data.v, state.settings.gate || 30);
      state.wave.push(data.v);
      if (state.wave.length > 1200) state.wave.shift();
      if (!$("[data-page=monitor]").hidden) {
        drawWave($("#waveChart"), state.wave.slice(-600),
                 state.settings.gate || 30);
        renderSlots(data.pattern || "");
        $("#elapsed").textContent = data.active ? `${data.elapsed_ms} ms` : "—";
      }

    } else if (type === "breath") {
      recentBreaths.unshift(data);
      if (recentBreaths.length > 40) recentBreaths.pop();
      state.todayCount++;
      $("#mToday").textContent = state.todayCount;
      $("#mLast").innerHTML =
        `${Math.round(data.duration_ms)}<span class="unit"> ms</span>`;
      $("#mSymbol").textContent = data.symbol === "." ? "Short" : "Long";
      $("#mToday").textContent = state.todayCount;
      renderRecent();

      // The calibration flow consumes a breath when it is listening.
      if (!RespCalibrate.onBreath(data) && state.exercise) exerciseBreath(data);

    } else if (type === "word") {
      recentWords.unshift(data);
      if (recentWords.length > 40) recentWords.pop();
      renderWords();
    }
  };

  ws.onclose = () => { setStatus("reconnecting"); setTimeout(connect, 1500); };
  ws.onerror = () => ws.close();
}

/* ==========================================================
   BOOT
   ========================================================== */

(async function boot() {
  const s = await api("/api/state");
  state.settings = s.settings;
  state.patterns = s.patterns;
  setStatus(s.status);
  $("#mThresh").innerHTML =
    `${Math.round(s.settings.threshold_ms)}<span class="unit"> ms</span>`;
  $("#mLast").textContent = "\u2014";
  state.todayCount = s.today || 0;
  $("#mToday").textContent = state.todayCount;
  renderSlots("");
  renderRecent();
  renderWords();
  renderPatternEditor();
  renderSettings();
  window.__lastStatus = s.status;
  RespOnboarding.init();
  connect();

  const params = new URLSearchParams(location.search);
  if (params.get("cal") === "1") { show("patterns", false); RespCalibrate.open(); }

  const autoGame = params.get("game");
  if (autoGame && EXERCISES[autoGame]) {
    show("training", false);
    await loadTraining();
    startExercise(autoGame);
  }

  const initial = location.hash.slice(1);
  if (initial && ["monitor", "analytics", "training", "patterns", "data"]
      .includes(initial))
    show(initial, false);

  addEventListener("resize", () => {
    if (!$("[data-page=analytics]").hidden && state.analytics) loadAnalytics();
  });
})();
