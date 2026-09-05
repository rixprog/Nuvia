/* Setup guide.
   Three steps: pair the device, place the sensor, calibrate. The placement
   step is the one that needs a picture - "right side of the chest" is
   ambiguous in words, and getting it wrong costs you the signal. */

const OB = {
  step: 0,
  steps: ["pair", "place", "calibrate"],
};

/* The figure faces the viewer, so the subject's RIGHT side is drawn on the
   viewer's LEFT. The R/L markers make that explicit rather than assumed. */
function torsoSVG() {
  return `
  <svg viewBox="0 0 260 210" class="ob-art" role="img"
       aria-label="Sensor placed on the right side of the chest">
    <defs>
      <radialGradient id="obGlow">
        <stop offset="0%"  stop-color="var(--series-1)" stop-opacity=".45"/>
        <stop offset="100%" stop-color="var(--series-1)" stop-opacity="0"/>
      </radialGradient>
    </defs>

    <g class="ob-body">
      <circle cx="130" cy="34" r="21" class="ob-line"/>
      <path d="M118 54 h24 v10 q0 4 6 6 l30 11 q14 5 16 20 l6 44
               q1 8 -7 8 h-6 l-4 -34 -3 52 h-98 l-3 -52 -4 34 h-6
               q-8 0 -7 -8 l6 -44 q2 -15 16 -20 l30 -11 q6 -2 6 -6 z"
            class="ob-line"/>
      <path d="M96 112 q34 10 68 0" class="ob-hint"/>
      <path d="M94 128 q36 11 72 0" class="ob-hint"/>
      <path d="M94 144 q36 11 72 0" class="ob-hint"/>
    </g>

    <g class="ob-sensor">
      <circle cx="100" cy="142" r="30" fill="url(#obGlow)" class="ob-halo"/>
      <circle cx="100" cy="142" r="17" class="ob-ring1"/>
      <circle cx="100" cy="142" r="17" class="ob-ring2"/>
      <rect x="88" y="130" width="24" height="24" rx="7" class="ob-puck"/>
      <circle cx="100" cy="142" r="4" class="ob-led"/>
    </g>

    <text x="52"  y="196" class="ob-side">YOUR RIGHT</text>
    <text x="208" y="196" class="ob-side">YOUR LEFT</text>
    <path d="M100 160 v18" class="ob-tick"/>
  </svg>`;
}

function pairSVG() {
  return `
  <svg viewBox="0 0 260 210" class="ob-art" role="img"
       aria-label="Pairing the sensor with this computer">
    <rect x="18" y="86" width="66" height="44" rx="9" class="ob-puck"/>
    <circle cx="51" cy="108" r="5" class="ob-led"/>
    <text x="51" y="150" class="ob-side">SENSOR</text>

    <g class="ob-waves">
      <path d="M100 108 a26 26 0 0 1 0 -34" class="ob-wave w1"/>
      <path d="M112 116 a40 40 0 0 1 0 -50" class="ob-wave w2"/>
      <path d="M124 124 a54 54 0 0 1 0 -66" class="ob-wave w3"/>
    </g>

    <rect x="164" y="78" width="80" height="52" rx="6" class="ob-line"/>
    <path d="M156 136 h96 l-8 -6 h-80 z" class="ob-line"/>
    <text x="204" y="160" class="ob-side">THIS COMPUTER</text>
  </svg>`;
}

function calibrateSVG() {
  return `
  <svg viewBox="0 0 260 210" class="ob-art" role="img"
       aria-label="A short breath and a long breath, and the symbol each makes">
    <path d="M16 150 H56 L64 100 L70 97 L78 102 L84 150 H140 L148 88 H204
             L212 150 H244" class="ob-trace"/>

    <path d="M70 72 V90" class="ob-connect"/>
    <path d="M176 72 V80" class="ob-connect"/>

    <circle cx="70" cy="58" r="9" class="ob-dotmark"/>
    <rect x="146" y="50" width="60" height="16" rx="8" class="ob-dashmark"/>

    <path d="M84 158 H140" class="ob-span"/>
    <path d="M84 154 v8 M140 154 v8" class="ob-span"/>

    <text x="70"  y="182" class="ob-side">SHORT</text>
    <text x="176" y="182" class="ob-side">LONG</text>
  </svg>`;
}


const OB_CONTENT = {
  pair: {
    art: pairSVG,
    title: "Pair the sensor",
    body: `Power the device on. The Bluetooth LED blinks rapidly when it is
           free to pair &mdash; two blinks then a pause means it is still
           connected to something else, so disconnect that first.`,
    points: ["PIN is 1234", "One device at a time",
             "Pairing is remembered afterwards"],
  },
  place: {
    art: torsoSVG,
    title: "Place it on the right side of the chest",
    body: `Sit the sensor flat against the <b>right</b> side of the chest,
           roughly level with the bottom of the ribcage, and hold it with the
           strap. It reads the movement of breathing, so it must sit against
           skin or a thin layer &mdash; not over a thick jumper.`,
    points: ["Right side, level with the lower ribs",
             "Snug but not tight",
             "Flat against the body"],
  },
  calibrate: {
    art: calibrateSVG,
    title: "Record a few breaths",
    body: `The device has to learn what your short and long breaths look like,
           because they differ from person to person and change through the
           day. Six of each is usually enough.`,
    points: ["Short breaths brief and distinct",
             "Long breaths deliberately longer",
             "Recalibrate whenever it starts misreading"],
  },
};

function renderOnboarding() {
  const key = OB.steps[OB.step];
  const c = OB_CONTENT[key];
  const host = document.getElementById("obBody");

  host.innerHTML = `
    <div class="ob-stage">${c.art()}</div>
    <div class="ob-copy">
      <div class="ob-count">Step ${OB.step + 1} of ${OB.steps.length}</div>
      <h3>${c.title}</h3>
      <p>${c.body}</p>
      <ul class="ob-points">${c.points.map(p => `<li>${p}</li>`).join("")}</ul>
      ${key === "pair" ? `<div class="ob-live" id="obLive"></div>` : ""}
    </div>`;

  document.querySelectorAll(".ob-pip").forEach((pip, i) =>
    pip.setAttribute("aria-current", String(i === OB.step)));
  document.getElementById("obBack").disabled = OB.step === 0;
  document.getElementById("obNext").textContent =
    OB.step === OB.steps.length - 1 ? "Finish" : "Next";

  if (key === "pair") updateOnboardingStatus(window.__lastStatus || "");
}

function updateOnboardingStatus(status) {
  const host = document.getElementById("obLive");
  if (!host) return;
  const ok = status === "connected" || status === "demo";
  host.innerHTML = `<span class="pill ${ok ? "good" : "warning"}"><i></i>
    ${ok ? "sensor connected" : "waiting for sensor"}</span>`;
}

function openOnboarding(step = 0) {
  OB.step = step;
  document.getElementById("onboarding").hidden = false;
  renderOnboarding();
}

function closeOnboarding() {
  document.getElementById("onboarding").hidden = true;
  localStorage.setItem("nuvia-setup-done", "1");
}

function initOnboarding() {
  document.getElementById("obNext").addEventListener("click", () => {
    if (OB.step === OB.steps.length - 1) {
      closeOnboarding();
      location.hash = "patterns";
    } else {
      OB.step++;
      renderOnboarding();
    }
  });
  document.getElementById("obBack").addEventListener("click", () => {
    OB.step = Math.max(0, OB.step - 1);
    renderOnboarding();
  });
  document.getElementById("obSkip").addEventListener("click", closeOnboarding);
  document.getElementById("obOpen").addEventListener("click", () => openOnboarding(0));
  document.querySelectorAll(".ob-pip").forEach((pip, i) =>
    pip.addEventListener("click", () => { OB.step = i; renderOnboarding(); }));

  // ?obstep=N jumps straight to a step - useful for testing and for linking
  // a carer directly to the placement instructions.
  const params = new URLSearchParams(location.search);
  const jump = params.get("obstep");
  const n = Number(jump);
  if (jump !== null && Number.isInteger(n) && n >= 0 && n <= 2) openOnboarding(n);
  else if (jump === null && !params.has("game")
           && !localStorage.getItem("nuvia-setup-done")) openOnboarding(0);
}

window.RespOnboarding = { init: initOnboarding, open: openOnboarding,
                          status: updateOnboardingStatus };
