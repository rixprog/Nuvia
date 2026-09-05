#!/usr/bin/env python3
"""Nuvia web server.

Reads the Arduino's raw ADC stream over Bluetooth, detects breaths, stores
everything in SQLite, and serves the dashboard.

  python3.11 web/server.py                 # connect to the HC-05
  python3.11 web/server.py --demo          # synthetic data, no hardware
  python3.11 web/server.py --port 8080

Then open http://127.0.0.1:8000

Timing note: breath durations are measured from wall-clock arrival time, not
from a sample count. The Arduino's nominal 100 Hz is not trustworthy - measured
recordings came in at 210-417 Hz because SoftwareSerial blocks interrupts and
starves millis(). Bluetooth adds ~10-50 ms of jitter, which on a ~1 s breath is
a few percent; assuming a wrong sample rate was a factor of 2-4.
"""

import argparse
import json
import math
import os
import random
import socket
import sqlite3
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
DB_PATH = HERE / "nuvia.db"

HC05_MAC = "00:25:00:00:56:86"
HC05_CHANNEL = 1

DEFAULTS = {
    "gate": 30,            # ADC counts above baseline that count as breath
    "hold_ms": 250,        # silence before a breath is considered over
    "threshold_ms": 1015,  # under = short '.', over = long '-'
    "min_breath_ms": 150,
    "pattern_timeout_ms": 4000,
}

DEFAULT_PATTERNS = [
    (".-.", "FOOD"), (".--", "WATER"), ("---", "EMERGENCY"), ("-.-", "TOILET"),
    ("--.", "MEDICINE"), ("...", "YES"), ("-..", "NO"),
]


# ============================================================
# STORAGE
# ============================================================

def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS breaths (
        id INTEGER PRIMARY KEY,
        ts REAL NOT NULL,             -- unix seconds, breath end
        duration_ms REAL NOT NULL,
        peak INTEGER NOT NULL,
        symbol TEXT NOT NULL,         -- '.' or '-'
        gap_s REAL                    -- seconds since previous breath
    );
    CREATE INDEX IF NOT EXISTS idx_breaths_ts ON breaths(ts);

    CREATE TABLE IF NOT EXISTS words (
        id INTEGER PRIMARY KEY,
        ts REAL NOT NULL,
        pattern TEXT NOT NULL,
        word TEXT                     -- NULL when unrecognised
    );

    CREATE TABLE IF NOT EXISTS patterns (
        pattern TEXT PRIMARY KEY,
        word TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS calibration (
        id INTEGER PRIMARY KEY,
        ts REAL NOT NULL,
        label TEXT NOT NULL,          -- 'short' | 'long'
        duration_ms REAL NOT NULL,
        peak INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS training (
        id INTEGER PRIMARY KEY,
        ts REAL NOT NULL,
        exercise TEXT NOT NULL,
        score INTEGER NOT NULL,
        best_ms REAL,
        reps INTEGER,
        detail TEXT
    );
    """)

    if not conn.execute("SELECT 1 FROM patterns LIMIT 1").fetchone():
        conn.executemany("INSERT INTO patterns VALUES (?,?)", DEFAULT_PATTERNS)

    for key, value in DEFAULTS.items():
        conn.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (key, str(value)))

    conn.commit()


def get_settings(conn):
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    out = dict(DEFAULTS)
    for row in rows:
        try:
            out[row["key"]] = float(row["value"])
        except ValueError:
            out[row["key"]] = row["value"]
    return out


def get_patterns(conn):
    return {r["pattern"]: r["word"]
            for r in conn.execute("SELECT * FROM patterns ORDER BY pattern")}


# ============================================================
# DETECTION
# ============================================================

class BreathDetector:
    """Envelope follower over the raw ADC stream.

    A sample above `gate` opens a breath; the breath closes once `hold_ms`
    passes with nothing above the gate. Without that hold one breath
    fragments into dozens of pieces, because the piezo signal is bursty.
    """

    def __init__(self, settings, patterns):
        self.update(settings, patterns)
        self.active = False
        self.start_t = 0.0
        self.last_above = 0.0
        self.peak = 0
        self.pattern = ""
        self.last_breath_t = 0.0

    def update(self, settings, patterns):
        self.gate = float(settings["gate"])
        self.hold = float(settings["hold_ms"]) / 1000.0
        self.threshold = float(settings["threshold_ms"])
        self.min_ms = float(settings["min_breath_ms"])
        self.timeout = float(settings["pattern_timeout_ms"]) / 1000.0
        self.patterns = patterns

    def feed(self, value, now):
        events = []

        if value > self.gate:
            if not self.active:
                self.active = True
                self.start_t = now
                self.peak = 0
            self.last_above = now
            self.peak = max(self.peak, int(value))

        elif self.active and (now - self.last_above) > self.hold:
            duration = (self.last_above - self.start_t) * 1000.0
            peak = self.peak
            self.active = False

            if duration >= self.min_ms:
                gap = (now - self.last_breath_t) if self.last_breath_t else None
                self.last_breath_t = now
                symbol = "." if duration < self.threshold else "-"
                self.pattern += symbol
                events.append(("breath", {
                    "ts": now, "duration_ms": round(duration, 1),
                    "peak": peak, "symbol": symbol,
                    "gap_s": round(gap, 2) if gap else None,
                }))

                if len(self.pattern) == 3:
                    word = self.patterns.get(self.pattern)
                    events.append(("word", {"ts": now, "pattern": self.pattern,
                                            "word": word}))
                    self.pattern = ""
            else:
                events.append(("glitch", {"duration_ms": round(duration, 1)}))

        # A lone breath with no follow-up was normal breathing, not a command.
        if (self.pattern and not self.active and self.last_breath_t
                and (now - self.last_breath_t) > self.timeout):
            events.append(("timeout", {"pattern": self.pattern}))
            self.pattern = ""

        return events


# ============================================================
# HUB - owns the device connection and fans out to websockets
# ============================================================

class Hub:
    def __init__(self, demo=False):
        self.conn = db()
        init_db(self.conn)
        self.demo = demo
        self.clients = set()
        self.lock = threading.Lock()
        self.status = "starting"
        self.last_value = 0
        self.settings = get_settings(self.conn)
        self.patterns = get_patterns(self.conn)
        self.detector = BreathDetector(self.settings, self.patterns)
        self.recent = []           # rolling window for the live chart
        self.capture = None        # active calibration capture, if any
        self.loop = None

    # -- settings ------------------------------------------------------
    def reload_config(self):
        self.settings = get_settings(self.conn)
        self.patterns = get_patterns(self.conn)
        self.detector.update(self.settings, self.patterns)

    # -- fan-out -------------------------------------------------------
    def broadcast(self, kind, payload):
        # Called from the device thread; hand off to the event loop safely.
        if self.loop is None:
            return
        message = json.dumps({"type": kind, "data": payload})
        with self.lock:
            for queue in list(self.clients):
                try:
                    self.loop.call_soon_threadsafe(queue.put_nowait, message)
                except RuntimeError:
                    self.clients.discard(queue)

    # -- sample ingestion ----------------------------------------------
    def on_sample(self, value, now):
        self.last_value = value
        self.recent.append((now, value))
        if len(self.recent) > 1200:
            del self.recent[:len(self.recent) - 1200]

        if self.capture is not None:
            self.capture["samples"].append(value)

        for kind, payload in self.detector.feed(value, now):
            if kind == "breath":
                self.conn.execute(
                    "INSERT INTO breaths (ts,duration_ms,peak,symbol,gap_s)"
                    " VALUES (?,?,?,?,?)",
                    (payload["ts"], payload["duration_ms"], payload["peak"],
                     payload["symbol"], payload["gap_s"]))
                self.conn.commit()
                if self.capture is not None:
                    self.capture["breaths"].append(payload)
            elif kind == "word":
                self.conn.execute(
                    "INSERT INTO words (ts,pattern,word) VALUES (?,?,?)",
                    (payload["ts"], payload["pattern"], payload["word"]))
                self.conn.commit()
            self.broadcast(kind, payload)

    # -- device --------------------------------------------------------
    def run_device(self):
        if self.demo:
            self.run_demo()
            return

        while True:
            try:
                self.status = "connecting"
                self.broadcast("status", {"state": self.status})
                sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                                     socket.BTPROTO_RFCOMM)
                sock.settimeout(10.0)
                sock.connect((HC05_MAC, HC05_CHANNEL))
                sock.settimeout(0.5)
                self.status = "connected"
                self.broadcast("status", {"state": self.status})

                buffer = b""
                while True:
                    try:
                        chunk = sock.recv(1024)
                    except socket.timeout:
                        continue
                    if not chunk:
                        break

                    now = time.time()
                    buffer += chunk
                    *lines, buffer = buffer.split(b"\n")

                    for raw in lines:
                        text = raw.decode("utf-8", "ignore").strip()
                        if not text:
                            continue
                        if text.upper().startswith("ADC:"):
                            text = text.split(":", 1)[1].strip()
                        try:
                            self.on_sample(int(text), now)
                        except ValueError:
                            pass
                sock.close()
            except OSError as error:
                self.status = f"disconnected: {error}"
                self.broadcast("status", {"state": self.status})
                time.sleep(3)

    def run_demo(self):
        """Synthetic signal so the dashboard is usable without hardware."""
        self.status = "demo"
        next_breath = time.time() + 2
        breath_start = 0.0
        breath_end = 0.0
        breath_peak = 0
        while True:
            now = time.time()
            value = 0

            if breath_start <= now < breath_end:
                # Bursty piezo-like signal: mostly zero with sharp spikes that
                # fade towards the end of the breath.
                if random.random() < 0.55:
                    span = max(breath_end - breath_start, 0.1)
                    decay = 0.35 + 0.65 * (breath_end - now) / span
                    value = int(breath_peak
                                * (0.45 + 0.55 * abs(math.sin(now * 30))) * decay)
                    value = max(0, min(1023, value))
            elif now >= next_breath:
                long_one = random.random() < 0.5
                length = (random.uniform(1.15, 1.7) if long_one
                          else random.uniform(0.5, 0.9))
                breath_start = now
                breath_end = now + length
                breath_peak = random.randint(90, 480)
                next_breath = breath_end + random.uniform(1.2, 3.2)

            self.on_sample(value, now)
            time.sleep(0.01)

    def start(self):
        thread = threading.Thread(target=self.run_device, daemon=True)
        thread.start()


# ============================================================
# ANALYTICS
# ============================================================

def analytics(conn, days=7):
    since = time.time() - days * 86400
    rows = conn.execute(
        "SELECT ts, duration_ms, peak, symbol, gap_s FROM breaths"
        " WHERE ts >= ? ORDER BY ts", (since,)).fetchall()

    breaths = [dict(r) for r in rows]

    # Coverage by hour of day - the night/morning picture. A flat zero band
    # overnight means the sensor saw nothing, not that breathing stopped.
    hourly = [0] * 24
    hourly_dur = [[] for _ in range(24)]
    for b in breaths:
        hour = time.localtime(b["ts"]).tm_hour
        hourly[hour] += 1
        hourly_dur[hour].append(b["duration_ms"])

    # Duration histogram, 200 ms bins up to 3 s
    bins = [0] * 15
    for b in breaths:
        idx = min(int(b["duration_ms"] // 200), 14)
        bins[idx] += 1

    durations = [b["duration_ms"] for b in breaths]
    peaks = [b["peak"] for b in breaths]
    gaps = [b["gap_s"] for b in breaths if b["gap_s"]]

    def stats(values):
        if not values:
            return {"n": 0, "mean": 0, "sd": 0, "min": 0, "max": 0}
        n = len(values)
        mean = sum(values) / n
        sd = math.sqrt(sum((v - mean) ** 2 for v in values) / n) if n > 1 else 0
        return {"n": n, "mean": round(mean, 1), "sd": round(sd, 1),
                "min": round(min(values), 1), "max": round(max(values), 1)}

    dur_stats = stats(durations)
    peak_stats = stats(peaks)
    gap_stats = stats(gaps)

    # Anomalies, each against the patient's own baseline rather than a
    # population norm - what matters here is change, not absolute value.
    anomalies = []

    if gap_stats["n"] > 5:
        pause_limit = max(20.0, gap_stats["mean"] + 3 * gap_stats["sd"])
        for b in breaths:
            if b["gap_s"] and b["gap_s"] > pause_limit:
                anomalies.append({
                    "ts": b["ts"], "kind": "pause", "severity": "serious",
                    "detail": f"{b['gap_s']:.0f}s with no breath detected",
                })

    if peak_stats["n"] > 5:
        weak_limit = peak_stats["mean"] - 1.5 * peak_stats["sd"]
        for b in breaths:
            if b["peak"] < weak_limit:
                anomalies.append({
                    "ts": b["ts"], "kind": "weak", "severity": "warning",
                    "detail": f"peak {b['peak']}, baseline {peak_stats['mean']:.0f}",
                })

    # Day-over-day drift in mean peak - the trend that matters clinically.
    by_day = {}
    for b in breaths:
        day = time.strftime("%Y-%m-%d", time.localtime(b["ts"]))
        by_day.setdefault(day, []).append(b)

    daily = []
    for day in sorted(by_day):
        items = by_day[day]
        daily.append({
            "day": day,
            "count": len(items),
            "mean_duration": round(sum(i["duration_ms"] for i in items) / len(items), 1),
            "mean_peak": round(sum(i["peak"] for i in items) / len(items), 1),
        })

    anomalies.sort(key=lambda a: a["ts"], reverse=True)

    return {
        "days": days,
        "total": len(breaths),
        "hourly": hourly,
        "hourly_mean_duration": [
            round(sum(v) / len(v), 1) if v else 0 for v in hourly_dur],
        "duration_bins": bins,
        "duration": dur_stats,
        "peak": peak_stats,
        "gap": gap_stats,
        "daily": daily,
        "anomalies": anomalies[:60],
        "recent": breaths[-200:],
    }


# ============================================================
# ASGI APP
# ============================================================

MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
        ".json": "application/json"}


class App:
    def __init__(self, hub):
        self.hub = hub

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self.lifespan(scope, receive, send)
        elif scope["type"] == "websocket":
            await self.websocket(scope, receive, send)
        else:
            await self.http(scope, receive, send)

    async def lifespan(self, scope, receive, send):
        import asyncio
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                self.hub.loop = asyncio.get_running_loop()
                self.hub.start()
                asyncio.ensure_future(self.wave_ticker())
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def wave_ticker(self):
        """Push a downsampled envelope ~20x/sec. Sending every sample would be
        hundreds of messages a second for a line nobody can read that fast."""
        import asyncio
        while True:
            await asyncio.sleep(0.05)
            hub = self.hub
            now = time.time()
            window = [v for t, v in hub.recent if now - t < 0.05]
            hub.broadcast("wave", {
                "v": max(window) if window else 0,
                "active": hub.detector.active,
                "pattern": hub.detector.pattern,
                "elapsed_ms": round((now - hub.detector.start_t) * 1000)
                              if hub.detector.active else 0,
            })

    # -- websocket -----------------------------------------------------
    async def websocket(self, scope, receive, send):
        import asyncio
        message = await receive()
        if message["type"] != "websocket.connect":
            return
        await send({"type": "websocket.accept"})

        queue = asyncio.Queue(maxsize=200)
        with self.hub.lock:
            self.hub.clients.add(queue)

        await send({"type": "websocket.send",
                    "text": json.dumps({"type": "status",
                                        "data": {"state": self.hub.status}})})

        async def pump():
            while True:
                text = await queue.get()
                await send({"type": "websocket.send", "text": text})

        task = asyncio.ensure_future(pump())
        try:
            while True:
                event = await receive()
                if event["type"] == "websocket.disconnect":
                    break
        finally:
            task.cancel()
            with self.hub.lock:
                self.hub.clients.discard(queue)

    # -- http ----------------------------------------------------------
    async def http(self, scope, receive, send):
        path = scope["path"]
        method = scope["method"]

        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break

        try:
            status, headers, payload = self.route(method, path, body)
        except Exception as error:  # a broken API call must not kill the page
            status = 500
            headers = [(b"content-type", b"application/json")]
            payload = json.dumps({"error": str(error)}).encode()

        await send({"type": "http.response.start", "status": status,
                    "headers": headers})
        await send({"type": "http.response.body", "body": payload})

    def json_response(self, obj, status=200):
        return status, [(b"content-type", b"application/json")], \
            json.dumps(obj).encode()

    def route(self, method, path, body):
        hub = self.hub
        conn = hub.conn

        if path == "/" or path == "/index.html":
            return self.serve_file(STATIC / "index.html")

        if path.startswith("/static/"):
            name = path[len("/static/"):]
            target = (STATIC / name).resolve()
            if STATIC.resolve() in target.parents and target.is_file():
                return self.serve_file(target)
            return 404, [(b"content-type", b"text/plain")], b"not found"

        if path == "/api/state":
            return self.json_response({
                "status": hub.status,
                "settings": hub.settings,
                "patterns": hub.patterns,
                "demo": hub.demo,
            })

        if path == "/api/analytics":
            return self.json_response(analytics(conn, days=30))

        if path == "/api/patterns" and method == "PUT":
            items = json.loads(body or b"{}")
            conn.execute("DELETE FROM patterns")
            conn.executemany("INSERT INTO patterns VALUES (?,?)",
                             [(k, v) for k, v in items.items() if k and v])
            conn.commit()
            hub.reload_config()
            return self.json_response({"patterns": hub.patterns})

        if path == "/api/settings" and method == "PUT":
            items = json.loads(body or b"{}")
            for key, value in items.items():
                if key in DEFAULTS:
                    conn.execute("REPLACE INTO settings VALUES (?,?)",
                                 (key, str(value)))
            conn.commit()
            hub.reload_config()
            return self.json_response({"settings": hub.settings})

        if path == "/api/calibration" and method == "GET":
            rows = conn.execute(
                "SELECT * FROM calibration ORDER BY ts").fetchall()
            return self.json_response({"samples": [dict(r) for r in rows]})

        if path == "/api/calibration" and method == "DELETE":
            conn.execute("DELETE FROM calibration")
            conn.commit()
            return self.json_response({"ok": True})

        if path == "/api/calibration/save" and method == "POST":
            item = json.loads(body or b"{}")
            conn.execute(
                "INSERT INTO calibration (ts,label,duration_ms,peak)"
                " VALUES (?,?,?,?)",
                (time.time(), item["label"], item["duration_ms"], item["peak"]))
            conn.commit()
            return self.json_response({"ok": True})

        if path == "/api/calibration/apply" and method == "POST":
            rows = conn.execute("SELECT label, duration_ms FROM calibration").fetchall()
            shorts = sorted(r["duration_ms"] for r in rows if r["label"] == "short")
            longs = sorted(r["duration_ms"] for r in rows if r["label"] == "long")
            if not shorts or not longs:
                return self.json_response(
                    {"error": "need at least one of each"}, 400)

            if max(shorts) < min(longs):
                threshold = (max(shorts) + min(longs)) / 2
                clean, margin = True, min(longs) - max(shorts)
            else:
                best, value = -1, 1000
                for candidate in range(200, 2600, 5):
                    score = (sum(d < candidate for d in shorts)
                             + sum(d >= candidate for d in longs))
                    if score > best:
                        best, value = score, candidate
                threshold, clean, margin = float(value), False, 0

            conn.execute("REPLACE INTO settings VALUES ('threshold_ms',?)",
                         (str(round(threshold)),))
            conn.commit()
            hub.reload_config()
            return self.json_response({
                "threshold_ms": round(threshold), "clean": clean,
                "margin_ms": round(margin), "shorts": shorts, "longs": longs,
            })

        if path == "/api/training" and method == "GET":
            rows = conn.execute(
                "SELECT * FROM training ORDER BY ts DESC LIMIT 100").fetchall()
            return self.json_response({"sessions": [dict(r) for r in rows]})

        if path == "/api/training" and method == "POST":
            item = json.loads(body or b"{}")
            conn.execute(
                "INSERT INTO training (ts,exercise,score,best_ms,reps,detail)"
                " VALUES (?,?,?,?,?,?)",
                (time.time(), item["exercise"], item["score"],
                 item.get("best_ms"), item.get("reps"),
                 json.dumps(item.get("detail"))))
            conn.commit()
            return self.json_response({"ok": True})

        if path == "/api/words":
            rows = conn.execute(
                "SELECT * FROM words ORDER BY ts DESC LIMIT 50").fetchall()
            return self.json_response({"words": [dict(r) for r in rows]})

        return 404, [(b"content-type", b"text/plain")], b"not found"

    def serve_file(self, path):
        if not path.is_file():
            return 404, [(b"content-type", b"text/plain")], b"not found"
        mime = MIME.get(path.suffix, "application/octet-stream")
        return 200, [(b"content-type", mime.encode()),
                     (b"cache-control", b"no-cache")], path.read_bytes()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true",
                        help="synthetic data, no hardware needed")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    import uvicorn
    hub = Hub(demo=args.demo)
    print(f"Nuvia -> http://{args.host}:{args.port}"
          + ("   [demo mode]" if args.demo else ""))
    uvicorn.run(App(hub), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
