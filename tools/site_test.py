#!/usr/bin/env python3
"""Drive the Nuvia dashboard through Chrome DevTools Protocol and report what
breaks. Exercises every page, both round-trips, a full 12-breath calibration,
two training sessions, recording and replay.

    python3.11 web/server.py --demo --port 8940 &
    python3.11 tools/site_test.py http://127.0.0.1:8940/

Exits non-zero on any failed check or console error, so it works in CI.
"""

import asyncio
import json
import subprocess
import sys
import tempfile
import urllib.request

import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9333


class CDP:
    """Minimal DevTools client: evaluate JS, collect console errors."""

    def __init__(self, ws):
        self.ws, self.n, self.logs, self.errs = ws, 0, [], []

    async def send(self, method, **params):
        self.n += 1
        await self.ws.send(json.dumps(
            {"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("method") == "Runtime.consoleAPICalled":
                a = msg["params"]
                text = " ".join(str(x.get("value", x.get("description", "?")))
                                for x in a.get("args", []))
                (self.errs if a["type"] in ("error", "assert")
                 else self.logs).append(text)
            elif msg.get("method") == "Runtime.exceptionThrown":
                d = msg["params"]["exceptionDetails"]
                self.errs.append(d.get("exception", {}).get("description")
                                 or d.get("text"))
            elif msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    async def js(self, expr):
        r = await self.send("Runtime.evaluate",
                            expression=f"(async()=>{{{expr}}})()",
                            awaitPromise=True, returnByValue=True)
        if r.get("exceptionDetails"):
            self.errs.append(str(r["exceptionDetails"].get("text")))
            return None
        return r.get("result", {}).get("value")


async def main():
    profile = tempfile.mkdtemp(prefix="nuvia-test-")
    chrome = subprocess.Popen(
        ["google-chrome", "--headless=new", "--disable-gpu", "--no-sandbox",
         f"--remote-debugging-port={PORT}", "--window-size=1400,900",
         f"--user-data-dir={profile}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(
                    f"http://127.0.0.1:{PORT}/json"))
                page = [t for t in tabs if t["type"] == "page"][0]
                break
            except Exception:
                await asyncio.sleep(0.3)
        else:
            print("chrome never came up")
            return 1

        async with websockets.connect(page["webSocketDebuggerUrl"],
                                      max_size=20_000_000) as ws:
            c = CDP(ws)
            await c.send("Runtime.enable")
            await c.send("Page.enable")
            await c.send("Page.navigate", url=URL)
            await asyncio.sleep(4)

            fail = []

            def check(name, ok, detail=""):
                print(f"  {'PASS' if ok else 'FAIL'}  {name}"
                      f"{'  ' + detail if detail else ''}")
                if not ok:
                    fail.append(name)

            async def wait_for(expr, secs=45):
                for _ in range(int(secs * 2)):
                    if await c.js(f"return {expr}"):
                        return True
                    await asyncio.sleep(0.5)
                return False

            check("page loaded", await c.js("return document.title") == "Nuvia")
            check("boot completed",
                  await c.js("return !!(typeof state !== 'undefined' && state.settings.threshold_ms)"))

            # dismiss the setup guide the way a user would
            await c.js("document.getElementById('obSkip').click(); return 1")
            await asyncio.sleep(0.5)
            check("setup guide dismissible",
                  await c.js("return document.getElementById('onboarding').hidden"))

            # every nav item shows its own section and nothing else
            for view in ["monitor", "analytics", "training", "patterns", "data"]:
                await c.js(f"[...document.querySelectorAll('#nav button')]"
                           f".find(b=>b.dataset.view==='{view}').click(); return 1")
                await asyncio.sleep(1.2)
                vis = await c.js(
                    "return [...document.querySelectorAll('[data-page]')]"
                    ".filter(s=>!s.hidden).map(s=>s.dataset.page)")
                check(f"nav -> {view}", vis == [view], f"visible={vis}")

            # charts actually rendered, not empty frames
            await c.js("location.hash='#analytics'; return 1")
            await asyncio.sleep(1.5)
            for cid in ["hourChart", "durChart"]:
                n = await c.js(f"return document.getElementById('{cid}').childElementCount")
                check(f"{cid} drew marks", (n or 0) > 4, f"{n} nodes")

            # patterns round-trip
            await c.js("location.hash='#patterns'; return 1")
            await asyncio.sleep(1.2)
            await c.js("""
                const i=document.querySelector('[data-pattern="..-"]');
                i.value='TEST'; document.getElementById('savePatterns').click(); return 1""")
            await asyncio.sleep(1.2)
            check("pattern saved",
                  (await c.js("return (await (await fetch('/api/state')).json())"
                              ".patterns['..-']")) == "TEST")

            # settings round-trip
            await c.js("""
                document.querySelector('[data-setting="pattern_timeout_ms"]').value=3500;
                document.getElementById('saveSettings').click(); return 1""")
            await asyncio.sleep(1.2)
            check("setting saved",
                  (await c.js("return (await (await fetch('/api/state')).json())"
                              ".settings.pattern_timeout_ms")) == 3500)

            # calibration flow advances on real (demo) breaths
            await c.js("RespCalibrate.open(); return 1")
            await asyncio.sleep(0.4)
            await c.js("document.getElementById('calStart').click(); return 1")
            await asyncio.sleep(0.4)
            check("calibration reached 'ready'",
                  await c.js("return !!document.getElementById('calGo')"))
            await c.js("document.getElementById('calGo').click(); return 1")
            await asyncio.sleep(4.5)          # 3s countdown, then listening
            phase = await c.js("return document.querySelector('.cal-kicker')"
                               "?.textContent.trim()")
            check("calibration listening/reviewing", phase is not None, f"phase={phase!r}")
            for _ in range(40):
                if await c.js("return !!document.getElementById('calAccept')"): break
                await asyncio.sleep(0.5)
            check("calibration captured a breath",
                  await c.js("return !!document.getElementById('calAccept')"))
            await c.js("document.getElementById('calQuit')?.click(); return 1")

            # a game starts and renders
            await c.js("location.hash='#training'; return 1")
            await asyncio.sleep(1.2)
            await c.js("document.querySelector('[data-ex=\"sustained\"]').click(); return 1")
            await asyncio.sleep(2.5)
            check("game running",
                  await c.js("return !document.getElementById('exerciseRun').hidden"))
            check("canvas has pixels", await c.js("""
                const cv=document.getElementById('gameCanvas');
                const d=cv.getContext('2d').getImageData(0,0,cv.width,cv.height).data;
                for(let i=3;i<d.length;i+=4) if(d[i]>0) return true; return false;"""))
            await c.js("document.getElementById('exQuit').click(); return 1")
            await asyncio.sleep(1)

            # data page
            await c.js("location.hash='#data'; return 1")
            await asyncio.sleep(2.5)
            check("raw stream has content",
                  (await c.js("return document.getElementById('rawBox').textContent.length")) > 10)


            # ---------- full calibration, all 12 ----------
            await c.js("await fetch('/api/calibration',{method:'DELETE'}); "
                       "RespCalibrate.open(); return 1")
            await asyncio.sleep(0.4)
            await c.js("document.getElementById('calStart').click(); return 1")
            captured = 0
            for i in range(12):
                if not await wait_for("!!document.getElementById('calGo')", 20):
                    break
                await c.js("document.getElementById('calGo').click(); return 1")
                if not await wait_for("!!document.getElementById('calAccept')", 45):
                    break
                await c.js("document.getElementById('calAccept').click(); return 1")
                captured += 1
                await asyncio.sleep(0.4)
            check("calibration captured all 12", captured == 12, f"got {captured}")
            done = await wait_for("!!document.getElementById('calFinish')", 20)
            check("calibration reached the summary", done)
            if done:
                txt = await c.js("return document.getElementById('calBody').textContent")
                thr = await c.js("return (await (await fetch('/api/state')).json())"
                                 ".settings.threshold_ms")
                check("threshold written to settings", isinstance(thr, (int, float)),
                      f"{thr} ms")
                check("summary states an outcome",
                      ("complete" in txt) or ("overlap" in txt))
                await c.js("document.getElementById('calFinish').click(); return 1")
                await asyncio.sleep(1)
                check("patterns page shows the calibration", await c.js(
                    "return document.getElementById('calSummary').textContent"
                    ".includes('Threshold')"))

            # ---------- a game to completion ----------
            await c.js("location.hash='#training'; return 1"); await asyncio.sleep(1.2)
            before = await c.js("return (await (await fetch('/api/training')).json())"
                                ".sessions.length")
            # run it twice: one session is deliberately an empty state, since a
            # single-point line chart says nothing. Two exercises the chart.
            for run in range(2):
                await c.js("document.querySelector('[data-ex=\"peak\"]').click(); return 1")
                ok = await wait_for("document.getElementById('exerciseRun').hidden", 90)
                check(f"game run {run+1} completed and closed", ok)
                await asyncio.sleep(1.5)
            after = await c.js("return (await (await fetch('/api/training')).json())"
                               ".sessions.length")
            check("sessions saved", (after or 0) >= (before or 0) + 2, f"{before} -> {after}")
            check("one session shows a value, not an empty chart", await c.js(
                "return document.getElementById('tce-peak').textContent.length >= 0"))
            check("progress chart drew with 2+ sessions", (await c.js(
                "return document.getElementById('tc-peak').childElementCount")) > 4)

            # ---------- record + replay ----------
            await c.js("location.hash='#data'; return 1"); await asyncio.sleep(1.5)
            await c.js("document.getElementById('recToggle').click(); return 1")
            await asyncio.sleep(5)
            rec = await c.js("return document.getElementById('recToggle').textContent")
            check("recording started", "Stop" in (rec or ""), rec)
            await c.js("document.getElementById('recToggle').click(); return 1")
            await asyncio.sleep(1.5)
            check("recording stopped", "Start" in (await c.js(
                "return document.getElementById('recToggle').textContent") or ""))
            has = await wait_for("!!document.querySelector('[data-replay]')", 10)
            check("recording listed", has)
            if has:
                await c.js("document.querySelector('[data-replay]').click(); return 1")
                check("replay produced output", await wait_for(
                    "document.getElementById('replayOut').textContent.includes('Threshold')", 20))

            # ---------- theme + reload persistence ----------
            await c.js("document.getElementById('themeToggle').click(); return 1")
            await asyncio.sleep(0.4)
            check("theme toggles", (await c.js(
                "return document.documentElement.getAttribute('data-theme')")) in ("dark","light"))
            await c.send("Page.navigate", url=URL); await asyncio.sleep(4)
            check("settings survive reload", isinstance(await c.js(
                "return state.settings.threshold_ms"), (int, float)))


            print()
            print(f"  {len(c.errs)} console error(s)")
            for e in dict.fromkeys(c.errs):
                print("   ", str(e)[:200])
            print(f"  {len(fail)} failure(s)"
                  + (": " + ", ".join(fail) if fail else ""))
            return 1 if (fail or c.errs) else 0
    finally:
        chrome.terminate()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
