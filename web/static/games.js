/* Breath training games.
   Canvas-rendered so the animation stays smooth; all three read the same live
   signal the detector uses, so a score is a real measurement, not a proxy.

   Colours come from the CSS custom properties, so the games follow the theme. */

const GameColors = () => {
  const cs = getComputedStyle(document.documentElement);
  const v = n => cs.getPropertyValue(n).trim();
  return {
    ink: v("--ink"), ink2: v("--ink-2"), muted: v("--ink-muted"),
    surface: v("--surface"), grid: v("--grid"), axis: v("--axis"),
    s1: v("--series-1"), s2: v("--series-2"), s3: v("--series-3"),
    good: v("--good"), warn: v("--warning"), crit: v("--critical"),
    wash: v("--wash"),
  };
};

class Game {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.level = 0;          // smoothed live signal, 0..1
    this.raw = 0;
    this.running = false;
    this.t = 0;
    this.onEnd = null;
  }

  resize() {
    const dpr = devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect();
    this.w = rect.width;
    this.h = rect.height;
    this.canvas.width = Math.round(this.w * dpr);
    this.canvas.height = Math.round(this.h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  start() {
    this.running = true;
    this.t = 0;
    this.last = performance.now();
    this.resize();
    const frame = now => {
      if (!this.running) return;
      const dt = Math.min((now - this.last) / 1000, 0.05);
      this.last = now;
      this.t += dt;
      this.level += (this.raw - this.level) * Math.min(1, dt * 12);
      this.step(dt);
      this.draw(GameColors());
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  }

  stop() { this.running = false; }

  /** Live envelope value, 0..1 of the useful range. */
  feedLevel(v, gate) {
    this.raw = Math.max(0, Math.min(1, v / 420));
    this.above = v > gate;
  }

  feedBreath() {}
  step() {}
  draw() {}

  roundRect(x, y, w, h, r) {
    const c = this.ctx;
    c.beginPath();
    c.moveTo(x + r, y);
    c.arcTo(x + w, y, x + w, y + h, r);
    c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r);
    c.arcTo(x, y, x + w, y, r);
    c.closePath();
  }
}

/* ==========================================================
   LIFT - sustained exhale
   The incentive spirometer, which is the standard bedside device for this:
   airflow lifts a float up a tube and you hold it in the target zone.
   ========================================================== */

class LiftGame extends Game {
  constructor(canvas, targetSeconds = 8) {
    super(canvas);
    this.held = 0;
    this.best = 0;
    this.target = targetSeconds;
    this.trail = [];
    this.motes = [];
  }

  step(dt) {
    const inZone = this.level > 0.28;
    if (inZone) {
      this.held += dt;
      this.best = Math.max(this.best, this.held);
      if (Math.random() < 0.4) {
        this.motes.push({ x: (Math.random() - 0.5) * 40, y: 0, life: 1,
                          r: 1 + Math.random() * 2 });
      }
    } else if (this.held > 0) {
      this.held = Math.max(0, this.held - dt * 2.5);
    }
    this.trail.push(this.level);
    if (this.trail.length > 160) this.trail.shift();
    this.motes.forEach(m => { m.y += dt * 90; m.life -= dt * 0.8; });
    this.motes = this.motes.filter(m => m.life > 0);
  }

  draw(C) {
    const c = this.ctx, { w, h } = this;
    c.clearRect(0, 0, w, h);

    const tubeW = Math.min(150, w * 0.26);
    const tx = w * 0.46 - tubeW / 2;
    const top = 22, bot = h - 28;
    const span = bot - top;

    // tube
    c.strokeStyle = C.grid;
    c.lineWidth = 1;
    this.roundRect(tx, top, tubeW, span, 14);
    c.stroke();

    // target zone
    const zoneTop = top + span * (1 - 0.62);
    const zoneBot = top + span * (1 - 0.28);
    c.fillStyle = C.wash;
    this.roundRect(tx + 1, zoneTop, tubeW - 2, zoneBot - zoneTop, 8);
    c.fill();
    c.strokeStyle = C.s1;
    c.setLineDash([]);
    c.lineWidth = 1.5;
    c.beginPath();
    c.moveTo(tx, zoneBot); c.lineTo(tx + tubeW, zoneBot);
    c.stroke();

    c.fillStyle = C.muted;
    c.font = "11px system-ui, sans-serif";
    c.textAlign = "right";
    c.fillText("hold above", tx - 10, zoneBot + 4);

    // float
    const fy = bot - Math.min(this.level, 1) * span;
    const glow = this.level > 0.28;
    c.save();
    c.translate(tx + tubeW / 2, fy);

    this.motes.forEach(m => {
      c.globalAlpha = m.life * 0.5;
      c.fillStyle = C.s1;
      c.beginPath(); c.arc(m.x, m.y, m.r, 0, 7); c.fill();
    });
    c.globalAlpha = 1;

    if (glow) {
      const g = c.createRadialGradient(0, 0, 2, 0, 0, 34);
      g.addColorStop(0, C.s1); g.addColorStop(1, "transparent");
      c.globalAlpha = 0.28; c.fillStyle = g;
      c.beginPath(); c.arc(0, 0, 34, 0, 7); c.fill();
      c.globalAlpha = 1;
    }
    c.fillStyle = glow ? C.s1 : C.axis;
    c.beginPath(); c.arc(0, 0, 15, 0, 7); c.fill();
    c.fillStyle = C.surface;
    c.beginPath(); c.arc(-4, -4, 4.5, 0, 7); c.fill();
    c.restore();

    // tube scale, so the zone reads as a level rather than decoration
    c.strokeStyle = C.grid; c.lineWidth = 1;
    for (let i = 1; i < 5; i++) {
      const y = bot - (i / 5) * span;
      c.beginPath(); c.moveTo(tx + tubeW, y); c.lineTo(tx + tubeW + 7, y); c.stroke();
    }

    // held-time ring
    const cx = w - 84, cy = h / 2, r = 46;
    c.strokeStyle = C.grid; c.lineWidth = 6;
    c.beginPath(); c.arc(cx, cy, r, 0, 7); c.stroke();
    const frac = Math.min(this.held / this.target, 1);
    c.strokeStyle = frac >= 1 ? C.good : C.s1;
    c.lineCap = "round";
    c.beginPath(); c.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + frac * 6.283);
    c.stroke();
    c.lineCap = "butt";
    c.fillStyle = C.ink;
    c.font = "600 20px system-ui, sans-serif";
    c.textAlign = "center";
    c.fillText(this.held.toFixed(1), cx, cy + 5);
    c.fillStyle = C.muted;
    c.font = "11px system-ui, sans-serif";
    c.fillText(`of ${this.target}s`, cx, cy + 22);

    // recent trace, filled so it carries some weight on the page
    if (this.trail.length > 2) {
      const tw = tx - 44, tox = 22;
      const px = i => tox + (i / (this.trail.length - 1)) * tw;
      const py = v => bot - v * span;
      c.beginPath();
      this.trail.forEach((v, i) => (i ? c.lineTo(px(i), py(v)) : c.moveTo(px(i), py(v))));
      c.strokeStyle = C.axis; c.lineWidth = 1.5; c.stroke();
      c.lineTo(px(this.trail.length - 1), bot); c.lineTo(px(0), bot); c.closePath();
      c.fillStyle = C.wash; c.fill();
      c.fillStyle = C.muted; c.font = "11px system-ui, sans-serif";
      c.textAlign = "left";
      c.fillText("last 8 seconds", tox, bot + 18);
    }
  }
}

/* ==========================================================
   SURGE - peak effort
   Trains the sharp expiratory push an effective cough needs.
   ========================================================== */

class SurgeGame extends Game {
  constructor(canvas, target = 200) {
    super(canvas);
    this.target = target;
    this.peakHold = 0;
    this.best = 0;
    this.flash = 0;
    this.history = [];
  }

  feedBreath(breath) {
    this.best = Math.max(this.best, breath.peak);
    this.history.push(breath.peak);
    if (this.history.length > 8) this.history.shift();
    this.flash = 1;
  }

  step(dt) {
    const now = this.level * 420;
    this.peakHold = Math.max(this.peakHold - dt * 120, now);
    this.flash = Math.max(0, this.flash - dt * 2);
  }

  draw(C) {
    const c = this.ctx, { w, h } = this;
    c.clearRect(0, 0, w, h);

    const barW = Math.min(130, w * 0.22);
    const bx = w * 0.27 - barW / 2;
    const top = 24, bot = h - 40, span = bot - top;
    const scale = Math.max(420, this.target * 1.35);

    c.strokeStyle = C.grid; c.lineWidth = 1;
    this.roundRect(bx, top, barW, span, 10); c.stroke();

    // target marker
    const ty = bot - (this.target / scale) * span;
    c.strokeStyle = C.s2; c.lineWidth = 2;
    c.beginPath(); c.moveTo(bx - 10, ty); c.lineTo(bx + barW + 10, ty); c.stroke();
    c.fillStyle = C.ink2; c.font = "11px system-ui, sans-serif";
    c.textAlign = "left";
    c.fillText(`target ${this.target}`, bx + barW + 16, ty + 4);

    // live column
    const lv = Math.min(this.level * 420 / scale, 1);
    if (lv > 0.01) {
      c.fillStyle = C.s1;
      const bh = lv * span;
      this.roundRect(bx + 2, bot - bh, barW - 4, bh, 6);
      c.fill();
    }

    // peak-hold cap
    const py = bot - Math.min(this.peakHold / scale, 1) * span;
    if (this.peakHold > 8) {
      c.fillStyle = C.ink;
      this.roundRect(bx - 3, py - 3, barW + 6, 4, 2); c.fill();
    }

    if (this.flash > 0) {
      c.globalAlpha = this.flash * 0.35;
      c.fillStyle = C.s1;
      this.roundRect(bx - 8, top - 8, barW + 16, span + 16, 14); c.fill();
      c.globalAlpha = 1;
    }

    // per-rep history on its own baseline
    const hx = w * 0.52, hw = Math.min(w * 0.4, 320);
    c.fillStyle = C.muted; c.font = "11px system-ui, sans-serif";
    c.textAlign = "left";
    c.fillText("THIS SESSION", hx, top + 4);

    c.strokeStyle = C.axis; c.lineWidth = 1;
    c.beginPath(); c.moveTo(hx, bot); c.lineTo(hx + hw, bot); c.stroke();

    // the target, carried across so reps are read against the same line
    const hty = bot - (this.target / scale) * (span - 34);
    c.strokeStyle = C.s2; c.lineWidth = 1.5;
    c.setLineDash([]);
    c.globalAlpha = .5;
    c.beginPath(); c.moveTo(hx, hty); c.lineTo(hx + hw, hty); c.stroke();
    c.globalAlpha = 1;

    const slot = hw / 8;
    this.history.forEach((v, i) => {
      const bh = Math.min(v / scale, 1) * (span - 34);
      const x = hx + i * slot;
      c.fillStyle = v >= this.target ? C.good : C.axis;
      this.roundRect(x, bot - bh, slot - 8, bh, 4); c.fill();
    });

    c.textAlign = "left";
    c.fillStyle = C.ink;
    c.font = "600 28px system-ui, sans-serif";
    const bestText = String(Math.round(this.best));
    c.fillText(bestText, hx, bot + 30);
    c.fillStyle = C.muted; c.font = "11px system-ui, sans-serif";
    c.fillText("best peak", hx + c.measureText(bestText).width + 34, bot + 30);
  }
}

/* ==========================================================
   CADENCE - rhythm control
   Notes flow toward the line; breathe short or long to match. Trains the
   fine control the morse patterns depend on.
   ========================================================== */

class CadenceGame extends Game {
  constructor(canvas, sequence) {
    super(canvas);
    this.sequence = sequence;
    this.notes = sequence.map((s, i) => ({ sym: s, x: 1 + i * 0.30, state: null }));
    this.speed = 0.115;
    this.hits = 0;
    this.pop = 0;
  }

  feedBreath(breath) {
    const next = this.notes.find(n => !n.state);
    if (!next) return;
    next.state = next.sym === breath.symbol ? "hit" : "miss";
    if (next.state === "hit") this.hits++;
    this.pop = 1;
  }

  step(dt) {
    this.notes.forEach(n => { if (!n.state) n.x -= this.speed * dt; });
    this.notes.forEach(n => { if (!n.state && n.x < -0.12) n.state = "miss"; });
    this.pop = Math.max(0, this.pop - dt * 2.5);
  }

  draw(C) {
    const c = this.ctx, { w, h } = this;
    c.clearRect(0, 0, w, h);

    const lineX = w * 0.22;
    const midY = h * 0.5;

    // lane
    c.fillStyle = C.wash;
    c.fillRect(0, midY - 34, w, 68);
    c.strokeStyle = C.grid; c.lineWidth = 1;
    c.beginPath(); c.moveTo(0, midY + 34); c.lineTo(w, midY + 34); c.stroke();
    c.beginPath(); c.moveTo(0, midY - 34); c.lineTo(w, midY - 34); c.stroke();

    // what is coming, so the player can prepare rather than react
    const upcoming = this.notes.filter(n => !n.state).slice(0, 4);
    c.fillStyle = C.muted; c.font = "11px system-ui, sans-serif";
    c.textAlign = "left";
    c.fillText("NEXT", 18, midY + 78);
    upcoming.forEach((n, i) => {
      const x = 58 + i * 34;
      c.fillStyle = C.axis;
      if (n.sym === ".") { c.beginPath(); c.arc(x, midY + 74, 5, 0, 7); c.fill(); }
      else { this.roundRect(x - 11, midY + 71, 22, 6, 3); c.fill(); }
    });

    // hit line
    c.strokeStyle = C.s2; c.lineWidth = 2 + this.pop * 3;
    c.beginPath(); c.moveTo(lineX, midY - 40); c.lineTo(lineX, midY + 40); c.stroke();
    c.fillStyle = C.muted; c.font = "11px system-ui, sans-serif";
    c.textAlign = "center";
    c.fillText("breathe", lineX, midY + 56);

    this.notes.forEach(n => {
      const x = lineX + n.x * (w - lineX);
      if (x < -80 || x > w + 80) return;
      const colour = n.state === "hit" ? C.good
                   : n.state === "miss" ? C.crit : C.s1;
      c.fillStyle = colour;
      c.globalAlpha = n.state ? 0.55 : 1;
      if (n.sym === ".") {
        c.beginPath(); c.arc(x, midY, 13, 0, 7); c.fill();
      } else {
        this.roundRect(x - 30, midY - 7, 60, 14, 7); c.fill();
      }
      c.globalAlpha = 1;
    });

    c.fillStyle = C.ink;
    c.font = "600 22px system-ui, sans-serif";
    c.textAlign = "left";
    c.fillText(`${this.hits}/${this.sequence.length}`, 18, 30);
  }
}

window.RespGames = { LiftGame, SurgeGame, CadenceGame };
