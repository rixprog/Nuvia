#!/usr/bin/env python3
"""RespTalk live decoder.

Reads the raw A0 stream from the Arduino over Bluetooth, detects breaths,
classifies each as short (.) or long (-), and decodes three-breath patterns
into words. Thresholds come from your own recorded calibration.

Flash arduino/resptalk_raw/resptalk_raw.ino first - this needs the raw ADC
stream, not the word output of resptalk_oled.

  python3.11 breath_live.py                 # live
  python3.11 breath_live.py --replay        # decode the calibration files
"""

import argparse
import csv
import glob
import os
import socket
import sys
import time


# ============================================================
# MORSE TABLE - edit freely, patterns are 3 breaths
# ============================================================

WORDS = {
    ".-.": "FOOD",
    ".--": "WATER",
    "---": "EMERGENCY",
    "-.-": "TOILET",
    "--.": "MEDICINE",
    "...": "YES",
    "-..": "NO",
}


# ============================================================
# CONFIGURATION
# ============================================================

HC05_MAC = "00:25:00:00:56:86"
HC05_CHANNEL = 1

SAMPLE_RATE = 100          # must match resptalk_raw.ino
CALIB_DIR = "breath_calibration"

# A sample counts as breath while it is above GATE. The breath is only
# considered over once HOLD_MS passes with nothing above it - without that
# hold, one breath fragments into many.
GATE = 30
HOLD_MS = 250

# Ignore anything this brief: it is a piezo glitch, not a breath.
MIN_BREATH_MS = 150

# Maximum gap between breaths inside one pattern, measured from the end of the
# previous breath. A deliberate sequence comes in a steady rhythm; a lone
# breath followed by silence was the user breathing normally, or breathing for
# some unrelated reason, and must not be joined onto whatever arrives next.
PATTERN_TIMEOUT_MS = 4000

MS_PER_SAMPLE = 1000.0 / SAMPLE_RATE


# ============================================================
# CALIBRATION
# ============================================================

def envelope_breaths(values):
    """Yield breath durations in ms, using the gate + hold envelope."""
    breaths = []
    active = False
    start = 0
    last_above = 0

    for i, value in enumerate(values):
        if value > GATE:
            if not active:
                active = True
                start = i
            last_above = i
        elif active and (i - last_above) * MS_PER_SAMPLE > HOLD_MS:
            breaths.append((last_above - start + 1) * MS_PER_SAMPLE)
            active = False

    if active:
        breaths.append((last_above - start + 1) * MS_PER_SAMPLE)

    return breaths


def load_calibration():
    """Longest breath found in each calibration recording, by class."""
    result = {}

    for kind in ("short", "long"):
        durations = []

        for path in sorted(glob.glob(os.path.join(CALIB_DIR, f"{kind}_*.csv"))):
            with open(path) as handle:
                values = [float(row["adc"]) for row in csv.DictReader(handle)]

            found = envelope_breaths(values)
            if found:
                durations.append(max(found))

        result[kind] = sorted(durations)

    return result


def derive_threshold(profile):
    """Midpoint of the gap when the classes separate, else best split."""
    shorts, longs = profile["short"], profile["long"]

    if not shorts or not longs:
        return 1000.0, False

    if max(shorts) < min(longs):
        return (max(shorts) + min(longs)) / 2.0, True

    best_score, best_value = -1, 1000.0
    for candidate in range(200, 2500, 5):
        score = sum(d < candidate for d in shorts) + sum(d >= candidate for d in longs)
        if score > best_score:
            best_score, best_value = score, float(candidate)

    return best_value, False


def print_profile(profile, threshold, clean):
    print()
    print("========================================")
    print("       YOUR CALIBRATED BREATHS")
    print("========================================")
    print()

    for kind in ("short", "long"):
        symbol = "." if kind == "short" else "-"
        values = profile[kind]

        if not values:
            print(f"  {kind.upper():<6} ({symbol})  no calibration files found")
            continue

        listed = "  ".join(f"{value:.0f}" for value in values)
        print(f"  {kind.upper():<6} ({symbol})  {listed}  ms")
        print(f"  {'':<6}      range {values[0]:.0f}-{values[-1]:.0f}, "
              f"mean {sum(values) / len(values):.0f} ms")
        print()

    print(f"  THRESHOLD  {threshold:.0f} ms   "
          f"(under = short '.', over = long '-')")

    if clean:
        gap = min(profile["long"]) - max(profile["short"])
        print(f"  Clean separation, {gap:.0f} ms of margin.")
    else:
        print("  WARNING: your short and long breaths overlap. Recalibrate,")
        print("  making the difference more deliberate.")

    print()
    print("========================================")
    print("            MORSE TABLE")
    print("========================================")
    print()
    for pattern, word in WORDS.items():
        print(f"   {pattern}   {word}")
    print()


# ============================================================
# DECODER
# ============================================================

class Decoder:
    def __init__(self, threshold, pattern_timeout=PATTERN_TIMEOUT_MS):
        self.threshold = threshold
        self.pattern_timeout = pattern_timeout
        self.pattern = ""
        self.active = False
        self.start = 0
        self.last_above = 0
        self.index = 0
        self.last_breath_index = 0

    def feed(self, value):
        """Push one ADC sample. Returns a list of (event, payload)."""
        events = []
        i = self.index
        self.index += 1

        if value > GATE:
            if not self.active:
                self.active = True
                self.start = i
            self.last_above = i

        elif self.active and (i - self.last_above) * MS_PER_SAMPLE > HOLD_MS:
            duration = (self.last_above - self.start + 1) * MS_PER_SAMPLE
            self.active = False
            self.last_breath_index = i

            if duration < MIN_BREATH_MS:
                events.append(("glitch", duration))
            else:
                symbol = "." if duration < self.threshold else "-"
                self.pattern += symbol
                events.append(("breath", (symbol, duration)))

                if len(self.pattern) == 3:
                    word = WORDS.get(self.pattern)
                    events.append(("word", (self.pattern, word)))
                    self.pattern = ""

        # Abandon a half-typed pattern rather than merging it into the next.
        if (self.pattern and not self.active
                and (i - self.last_breath_index) * MS_PER_SAMPLE
                > self.pattern_timeout):
            events.append(("timeout", self.pattern))
            self.pattern = ""

        return events

    def status(self, value):
        filled = min(int(value / 1024 * 28), 28)
        meter = "#" * filled + "-" * (28 - filled)
        slots = "".join(self.pattern[i] if i < len(self.pattern) else "_"
                        for i in range(3))
        live = ""
        if self.active:
            elapsed = (self.index - self.start) * MS_PER_SAMPLE
            live = f"  {elapsed:5.0f}ms {'-' if elapsed >= self.threshold else '.'}"
        elif self.pattern:
            waited = (self.index - self.last_breath_index) * MS_PER_SAMPLE
            left = max(0.0, self.pattern_timeout - waited)
            live = f"  next in {left / 1000:.1f}s"
        return f"\r  [{meter}] {value:4.0f}   {slots}{live}            "


def report(events):
    for kind, payload in events:
        if kind == "breath":
            symbol, duration = payload
            name = "SHORT" if symbol == "." else "LONG"
            print(f"\r  {symbol}  {name:<5} {duration:.0f} ms" + " " * 24)
        elif kind == "word":
            pattern, word = payload
            if word:
                print(f"\r  ==> {pattern}  {word}" + " " * 30)
                print()
            else:
                print(f"\r  ==> {pattern}  not in table" + " " * 24)
                print()
        elif kind == "timeout":
            print(f"\r  ... '{payload}' discarded - no follow-up breath"
                  + " " * 12)
        elif kind == "glitch":
            print(f"\r  (ignored {payload:.0f} ms glitch)" + " " * 24)


# ============================================================
# SOURCES
# ============================================================

def replay(decoder):
    paths = sorted(glob.glob(os.path.join(CALIB_DIR, "*.csv")))
    if not paths:
        sys.exit(f"no CSV files in {CALIB_DIR}/")

    print("Replaying calibration recordings:")
    print()

    for path in paths:
        with open(path) as handle:
            values = [float(row["adc"]) for row in csv.DictReader(handle)]

        print(f"  {os.path.basename(path)}")
        decoder.pattern = ""
        for value in values:
            report(decoder.feed(value))
        # Flush the trailing silence so the last breath closes.
        for _ in range(int(HOLD_MS / MS_PER_SAMPLE) + 2):
            report(decoder.feed(0))


def live(decoder):
    print(f"Connecting to {HC05_MAC}...")

    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    sock.settimeout(10.0)

    try:
        sock.connect((HC05_MAC, HC05_CHANNEL))
    except OSError as error:
        sys.exit(
            f"\nCould not connect: {error}\n\n"
            "  - HC-05 takes one master at a time; free it from any other device\n"
            "  - check the Arduino is powered and the LED blinks rapidly\n"
            f"  - confirm pairing:  bluetoothctl info {HC05_MAC}"
        )

    sock.settimeout(0.2)
    print("Connected. Breathe.  (Ctrl-C to stop)")
    print()

    buffer = b""
    ignored = 0
    last_draw = 0.0

    try:
        while True:
            try:
                chunk = sock.recv(1024)
            except socket.timeout:
                continue

            if not chunk:
                print("\nremote closed the connection")
                break

            buffer += chunk
            *lines, buffer = buffer.split(b"\n")

            for raw in lines:
                text = raw.decode("utf-8", "ignore").strip()
                if not text:
                    continue
                if text.upper().startswith("ADC:"):
                    text = text.split(":", 1)[1].strip()

                try:
                    value = float(int(text))
                except ValueError:
                    ignored += 1
                    if ignored == 20:
                        print("\r  Receiving text, not numbers - is resptalk_oled"
                              " flashed instead of resptalk_raw?")
                    continue

                report(decoder.feed(value))

                now = time.time()
                if now - last_draw > 0.05:
                    last_draw = now
                    sys.stdout.write(decoder.status(value))
                    sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", action="store_true",
                        help="decode the saved calibration files instead")
    parser.add_argument("--threshold", type=float,
                        help="override the derived duration threshold, in ms")
    parser.add_argument("--timeout", type=float, default=PATTERN_TIMEOUT_MS,
                        help=f"max gap between breaths in one pattern, ms "
                             f"(default {PATTERN_TIMEOUT_MS})")
    args = parser.parse_args()

    profile = load_calibration()
    threshold, clean = derive_threshold(profile)

    if args.threshold:
        threshold = args.threshold
        print(f"(threshold overridden to {threshold:.0f} ms)")

    print_profile(profile, threshold, clean)

    decoder = Decoder(threshold, args.timeout)
    print(f"  Pattern timeout: {args.timeout:.0f} ms between breaths.")
    print("  A breath with no follow-up inside that window is discarded.")
    print()

    if args.replay:
        replay(decoder)
    else:
        live(decoder)


if __name__ == "__main__":
    main()
