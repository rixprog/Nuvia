/* Guided recalibration.
   Short and long breaths differ between people and drift through the day, so
   this needs to be easy enough to redo often rather than a one-time setup. */

const CAL = {
  perClass: 6,
  order: [],          // ['short' x6, 'long' x6]
  index: 0,
  taken: { short: [], long: [] },
  phase: "intro",     // intro | ready | countdown | listening | review | done
  pending: null,
  count: 3,
  timer: null,
  result: null,
};

const calEl = id => document.getElementById(id);

function calOpen() {
  CAL.phase = "intro";
  CAL.index = 0;
  CAL.taken = { short: [], long: [] };
  CAL.result = null;
  CAL.order = [...Array(CAL.perClass).fill("short"),
               ...Array(CAL.perClass).fill("long")];
  calEl("calOverlay").hidden = false;
  calRender();
}

function calClose() {
  clearInterval(CAL.timer);
  CAL.timer = null;
  CAL.phase = "intro";
  calEl("calOverlay").hidden = true;
}

const calLabel = () => CAL.order[CAL.index];
const calDone = () => CAL.index >= CAL.order.length;

function calProgressBar() {
  return CAL.order.map((lab, i) => {
    const state = i < CAL.index ? "done" : i === CAL.index ? "now" : "";
    return `<i class="cal-pip ${state} ${lab}"></i>`;
  }).join("");
}

function calRender() {
  const body = calEl("calBody");
  const foot = calEl("calFoot");
  calEl("calProgress").innerHTML =
    CAL.phase === "intro" || CAL.phase === "done" ? "" : calProgressBar();

  if (CAL.phase === "intro") {
    body.innerHTML = `
      <div class="cal-pad">
        <h3>Recalibrate</h3>
        <p>You will record <b>${CAL.perClass} short</b> and
           <b>${CAL.perClass} long</b> breaths. Nuvia uses the gap between them
           to decide which is which.</p>
        <ul class="ob-points">
          <li>Keep short breaths brief and distinct</li>
          <li>Make long breaths deliberately longer, not harder</li>
          <li>You can redo any breath that comes out wrong</li>
        </ul>
        <p class="cal-note">Recalibrate whenever it starts misreading &mdash;
           breath strength changes through the day, especially when tired.</p>
      </div>`;
    foot.innerHTML = `
      <button class="btn primary" id="calStart">Start</button>
      <button class="theme-toggle" id="calCancel" style="margin-left:auto">
        Cancel</button>`;
    calEl("calStart").onclick = () => { CAL.phase = "ready"; calRender(); };
    calEl("calCancel").onclick = calClose;
    return;
  }

  if (CAL.phase === "ready") {
    const lab = calLabel();
    const n = CAL.taken[lab].length + 1;
    body.innerHTML = `
      <div class="cal-pad cal-center">
        <div class="cal-kicker">${lab.toUpperCase()} BREATH ${n} OF ${CAL.perClass}</div>
        <h3>${lab === "short" ? "A brief breath" : "A long, steady breath"}</h3>
        <p>${lab === "short"
              ? "Short and distinct &mdash; the kind you would use for a dot."
              : "Hold it noticeably longer &mdash; the kind you would use for a dash."}</p>
        <div class="cal-glyph ${lab}"></div>
      </div>`;
    foot.innerHTML = `
      <button class="btn primary" id="calGo">I'm ready</button>
      <button class="theme-toggle" id="calQuit" style="margin-left:auto">
        Stop</button>`;
    calEl("calGo").onclick = calCountdown;
    calEl("calQuit").onclick = calClose;
    return;
  }

  if (CAL.phase === "countdown") {
    body.innerHTML = `
      <div class="cal-pad cal-center">
        <div class="cal-kicker">GET READY</div>
        <div class="cal-count">${CAL.count}</div>
      </div>`;
    foot.innerHTML = `<button class="theme-toggle" id="calQuit"
      style="margin-left:auto">Stop</button>`;
    calEl("calQuit").onclick = calClose;
    return;
  }

  if (CAL.phase === "listening") {
    const lab = calLabel();
    body.innerHTML = `
      <div class="cal-pad cal-center">
        <div class="cal-kicker cal-live">BREATHE NOW</div>
        <h3>${lab === "short" ? "Short breath" : "Long breath"}</h3>
        <div class="cal-meter"><i id="calMeterFill"></i></div>
        <div class="cal-elapsed mono" id="calElapsed">&mdash;</div>
        <p class="cal-note">Waiting for the breath to finish&hellip;</p>
      </div>`;
    foot.innerHTML = `<button class="theme-toggle" id="calQuit"
      style="margin-left:auto">Stop</button>`;
    calEl("calQuit").onclick = calClose;
    return;
  }

  if (CAL.phase === "review") {
    const b = CAL.pending;
    const lab = calLabel();
    body.innerHTML = `
      <div class="cal-pad cal-center">
        <div class="cal-kicker">${lab.toUpperCase()} BREATH RECORDED</div>
        <div class="cal-reading">${Math.round(b.duration_ms)}<span> ms</span></div>
        <p class="cal-note">peak ${b.peak}</p>
        ${calSanity(lab, b)}
      </div>`;
    foot.innerHTML = `
      <button class="btn primary" id="calAccept">Keep it</button>
      <button class="btn" id="calRedo">Redo</button>
      <button class="theme-toggle" id="calQuit" style="margin-left:auto">
        Stop</button>`;
    calEl("calAccept").onclick = calAccept;
    calEl("calRedo").onclick = () => { CAL.phase = "ready"; calRender(); };
    calEl("calQuit").onclick = calClose;
    return;
  }

  if (CAL.phase === "done") {
    const r = CAL.result;
    body.innerHTML = `
      <div class="cal-pad">
        <h3>${r.clean ? "Calibration complete" : "The two classes overlap"}</h3>
        ${r.clean
          ? `<p>Your short and long breaths separate cleanly, with
             <b>${r.margin_ms} ms</b> between the slowest short and the
             fastest long.</p>`
          : `<p>Some short breaths lasted longer than some long ones, so no
             single threshold separates them. Try again, making the long
             breaths noticeably longer.</p>`}
        <div class="cal-summary">
          <div><span>Threshold</span><b>${r.threshold_ms} ms</b></div>
          <div><span>Short</span><b>${r.shorts.map(Math.round).join(", ")}</b></div>
          <div><span>Long</span><b>${r.longs.map(Math.round).join(", ")}</b></div>
        </div>
        ${r.clean && r.margin_ms < 150
          ? `<p class="cal-warn">That margin is thin. Live breaths vary more
             than recorded ones, so it may still misread occasionally.</p>` : ""}
      </div>`;
    foot.innerHTML = `
      <button class="btn primary" id="calFinish">Done</button>
      <button class="btn" id="calAgain">Record again</button>`;
    calEl("calFinish").onclick = () => { calClose(); loadCalibration(); };
    calEl("calAgain").onclick = () => {
      fetch("/api/calibration", { method: "DELETE" }).then(calOpen);
    };
  }
}

// Flag a reading that plainly contradicts its label, so a mis-performed
// breath is caught now rather than poisoning the threshold later.
function calSanity(label, b) {
  const others = CAL.taken[label === "short" ? "long" : "short"];
  if (!others.length) return "";
  const mean = others.reduce((s, x) => s + x.duration_ms, 0) / others.length;
  if (label === "short" && b.duration_ms > mean) {
    return `<p class="cal-warn">That was longer than your average long breath.
            Consider redoing it.</p>`;
  }
  if (label === "long" && b.duration_ms < mean) {
    return `<p class="cal-warn">That was shorter than your average short
            breath. Consider redoing it.</p>`;
  }
  return "";
}

function calCountdown() {
  CAL.phase = "countdown";
  CAL.count = 3;
  calRender();
  clearInterval(CAL.timer);
  CAL.timer = setInterval(() => {
    CAL.count--;
    if (CAL.count <= 0) {
      clearInterval(CAL.timer);
      CAL.timer = null;
      CAL.phase = "listening";
    }
    calRender();
  }, 1000);
}

async function calAccept() {
  const b = CAL.pending;
  const lab = calLabel();
  CAL.taken[lab].push(b);
  CAL.pending = null;
  CAL.index++;

  await fetch("/api/calibration/save", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ label: lab, duration_ms: b.duration_ms, peak: b.peak }),
  });

  if (calDone()) {
    const res = await fetch("/api/calibration/apply", { method: "POST" });
    CAL.result = await res.json();
    CAL.phase = "done";
    if (CAL.result.threshold_ms) {
      state.settings.threshold_ms = CAL.result.threshold_ms;
      const t = document.getElementById("mThresh");
      if (t) t.innerHTML =
        `${CAL.result.threshold_ms}<span class="unit"> ms</span>`;
      renderSettings();
    }
  } else {
    CAL.phase = "ready";
  }
  calRender();
}

/* --- hooks called from the live stream --- */

function calOnBreath(breath) {
  if (CAL.phase !== "listening") return false;
  CAL.pending = breath;
  CAL.phase = "review";
  calRender();
  return true;                 // consumed
}

function calOnWave(data, gate) {
  if (CAL.phase !== "listening") return;
  const fill = calEl("calMeterFill");
  if (fill) fill.style.width = Math.min(100, (data.v / 420) * 100) + "%";
  const el = calEl("calElapsed");
  if (el) el.textContent = data.active ? `${data.elapsed_ms} ms` : "—";
}

window.RespCalibrate = { open: calOpen, onBreath: calOnBreath, onWave: calOnWave };
