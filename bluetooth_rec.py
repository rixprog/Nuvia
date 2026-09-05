#!/usr/bin/env python3
"""Nuvia breath calibration.

Records short and long breaths from the Arduino's raw ADC stream and derives
the duration threshold that separates them.

Flash arduino/nuvia_raw/nuvia_raw.ino first - that is the sketch that
streams A0. nuvia_oled sends words, not samples.

  python3.11 bluetooth_rec.py                    # 10 of each
  python3.11 bluetooth_rec.py --samples 15
  python3.11 bluetooth_rec.py --seconds 5        # longer recording window

Measurement note: breaths are classified by DURATION, not amplitude. A piezo
responds to rate of deformation, so a sharp short breath produces a *larger*
signal than a slow deep one - amplitude runs backwards and cannot separate
the two. Amplitude is still reported, but only as a signal-health check.
"""

import argparse
import csv
import os
import shutil
import socket
import sys
import time

import numpy as np

# Single source of truth for the detection algorithm - the same functions the
# live decoder uses, so both report identical numbers.
from breath_live import (GATE, HOLD_MS, SAMPLE_RATE, envelope_breaths,
                         derive_threshold)

try:
    import matplotlib
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAVE_PLOT = True
except ImportError:
    HAVE_PLOT = False


HC05_MAC = "00:25:00:00:56:86"
HC05_CHANNEL = 1

OUTPUT_DIR = "breath_calibration"

CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 0.2


# ============================================================
# BLUETOOTH
# ============================================================

_buffer = b""
_ignored_lines = 0


def connect():
    print()
    print(f"Connecting to {HC05_MAC}...")

    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                         socket.BTPROTO_RFCOMM)
    sock.settimeout(CONNECT_TIMEOUT)

    try:
        sock.connect((HC05_MAC, HC05_CHANNEL))
    except OSError as error:
        print()
        print(f"Could not connect: {error}")
        print()
        print("  - HC-05 takes one master at a time. Free it from any phone")
        print("    or other laptop still holding it.")
        print("  - Check the Arduino is powered and the LED blinks rapidly.")
        print(f"  - Confirm the pairing:  bluetoothctl info {HC05_MAC}")
        sys.exit(1)

    sock.settimeout(READ_TIMEOUT)
    print("Connected.")
    return sock


def read_adc(sock):
    """Parse whatever has arrived. Bluetooth splits lines across chunks, so
    the partial tail is held back until its newline turns up."""
    global _buffer, _ignored_lines

    try:
        chunk = sock.recv(1024)
    except socket.timeout:
        return []
    except OSError as error:
        print("Bluetooth error:", error)
        return []

    if not chunk:
        return []

    _buffer += chunk
    *lines, _buffer = _buffer.split(b"\n")

    values = []

    for raw in lines:
        text = raw.decode("utf-8", errors="ignore").strip()
        if not text:
            continue
        if text.upper().startswith("ADC:"):
            text = text.split(":", 1)[1].strip()

        try:
            values.append(int(text))
        except ValueError:
            _ignored_lines += 1

    return values


def collect_samples(sock, seconds):
    samples = []
    start = time.time()

    while time.time() - start < seconds:
        samples.extend(read_adc(sock))

    return samples


# ============================================================
# ANALYSIS
# ============================================================

def analyze(samples):
    if len(samples) == 0:
        return None

    data = np.array(samples, dtype=float)

    baseline = np.median(data[:min(len(data), SAMPLE_RATE // 2)])
    amplitude = float(np.max(np.abs(data - baseline)))

    found = envelope_breaths(data)

    return {
        "data": data,
        "baseline": float(baseline),
        "min": float(np.min(data)),
        "max": float(np.max(data)),
        "amplitude": amplitude,
        "duration_ms": max(found) if found else 0.0,
        "breath_count": len(found),
    }


def save_csv(breath_type, number, samples):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = os.path.join(OUTPUT_DIR, f"{breath_type}_{number}.csv")

    with open(filename, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample", "time_ms", "adc"])
        for i, value in enumerate(samples):
            writer.writerow([i, i * (1000 / SAMPLE_RATE), value])

    return filename


# ============================================================
# RECORD
# ============================================================

def record_breath(sock, breath_type, number, total, seconds):
    while True:
        print()
        print("----------------------------------------")
        print(f"{breath_type.upper()} BREATH {number}/{total}")
        print("----------------------------------------")

        input("Press ENTER when ready...")

        print()
        print("Get ready...")
        for i in range(3, 0, -1):
            print(i)
            time.sleep(1)

        print()
        if breath_type == "short":
            print(">>> TAKE A SHORT BREATH NOW <<<")
        else:
            print(">>> TAKE A LONG / DEEP BREATH NOW <<<")

        print(f"Recording for {seconds} seconds...")

        samples = collect_samples(sock, seconds)
        print()
        print(f"Received {len(samples)} ADC values.")

        result = analyze(samples)

        if result is None:
            print()
            print("No ADC data received.")
            if _ignored_lines:
                print(f"{_ignored_lines} non-numeric lines arrived instead -")
                print("that looks like nuvia_oled is flashed, not nuvia_raw.")
            continue

        expected = int(SAMPLE_RATE * seconds)
        if len(samples) < expected * 0.5:
            print(f"WARNING: expected ~{expected} samples, got {len(samples)}.")

        print()
        print("RESULT")
        print("----------------------------------------")
        print(f"Baseline   : {result['baseline']:.0f}")
        print(f"Peak       : {result['max']:.0f}")
        print(f"Amplitude  : {result['amplitude']:.0f}")
        print(f"DURATION   : {result['duration_ms']:.0f} ms   <- what matters")
        print(f"Breaths    : {result['breath_count']} detected")
        print("----------------------------------------")

        if result["breath_count"] == 0:
            print("No breath detected above the gate. Redo.")
            continue

        if result["breath_count"] > 1:
            print(f"NOTE: {result['breath_count']} separate breaths detected;")
            print("only the longest is used. Consider redoing.")

        choice = input("ENTER = accept | R = redo: ").strip().lower()

        if choice == "r":
            print("Redoing sample...")
            continue

        print(f"Saved: {save_csv(breath_type, number, samples)}")
        return result


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=10,
                        help="recordings per class (default 10)")
    parser.add_argument("--seconds", type=float, default=4.0,
                        help="recording window (default 4)")
    args = parser.parse_args()

    print()
    print("========================================")
    print("       RESP-TALK CALIBRATION")
    print("========================================")
    print()
    print(f"  {args.samples} short + {args.samples} long, "
          f"{args.seconds:.0f}s each")
    print(f"  gate={GATE}  hold={HOLD_MS}ms  rate={SAMPLE_RATE}Hz")

    # Old recordings are globbed by breath_live.py, so leftovers from a larger
    # run would contaminate the next one. Archive rather than delete.
    if os.path.isdir(OUTPUT_DIR) and os.listdir(OUTPUT_DIR):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        archive = f"{OUTPUT_DIR}_archive/{stamp}"
        os.makedirs(os.path.dirname(archive), exist_ok=True)
        shutil.move(OUTPUT_DIR, archive)
        print()
        print(f"  previous calibration moved to {archive}/")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    sock = connect()

    results = {}
    for kind in ("short", "long"):
        print()
        print("========================================")
        print(f"       {kind.upper()} BREATH CALIBRATION")
        print("========================================")
        results[kind] = [
            record_breath(sock, kind, i, args.samples, args.seconds)
            for i in range(1, args.samples + 1)
        ]

    sock.close()

    profile = {k: sorted(r["duration_ms"] for r in results[k]) for k in results}
    threshold, clean = derive_threshold(profile)

    print()
    print()
    print("========================================")
    print("          CALIBRATION RESULT")
    print("========================================")

    for kind in ("short", "long"):
        durations = profile[kind]
        amplitudes = [r["amplitude"] for r in results[kind]]
        print()
        print(f"{kind.upper()} BREATH")
        for i, (d, a) in enumerate(zip(durations, sorted(amplitudes)), 1):
            print(f"  {i:>2}: {d:>6.0f} ms      (amplitude {a:.0f})")
        print(f"  range {durations[0]:.0f}-{durations[-1]:.0f} ms, "
              f"mean {sum(durations) / len(durations):.0f} ms")

    print()
    print("----------------------------------------")
    print(f"DURATION THRESHOLD = {threshold:.0f} ms")
    print("----------------------------------------")
    print()

    if clean:
        margin = min(profile["long"]) - max(profile["short"])
        print(f"GOOD: clean separation, {margin:.0f} ms of margin.")
        print(f"  slowest short {max(profile['short']):.0f} ms")
        print(f"  fastest long  {min(profile['long']):.0f} ms")
        if margin < 150:
            print()
            print("  That margin is thin. Live breaths vary more than")
            print("  recorded ones - consider making longs more deliberate.")
    else:
        correct = (sum(d < threshold for d in profile["short"])
                   + sum(d >= threshold for d in profile["long"]))
        print(f"OVERLAP: best split gets {correct}/{len(profile['short']) * 2}.")
        print("Recalibrate, exaggerating the difference between the two.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "threshold.txt"), "w") as handle:
        handle.write(f"duration_threshold_ms={threshold:.0f}\n")
        handle.write(f"gate={GATE}\n")
        handle.write(f"hold_ms={HOLD_MS}\n")

    print()
    print(f"Saved to {OUTPUT_DIR}/threshold.txt")
    print()
    print("Now test it live:   python3.11 breath_live.py")

    if HAVE_PLOT:
        try:
            count = len(profile["short"])
            plt.figure(figsize=(10, 5))
            plt.plot(range(1, count + 1), profile["short"], marker="o",
                     label="Short breath")
            plt.plot(range(1, len(profile["long"]) + 1), profile["long"],
                     marker="o", label="Long breath")
            plt.axhline(threshold, linestyle="--",
                        label=f"Threshold = {threshold:.0f} ms")
            plt.xlabel("Calibration sample (sorted)")
            plt.ylabel("Breath duration (ms)")
            plt.title("Short vs Long Breath Duration")
            plt.legend()
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            path = os.path.join(OUTPUT_DIR, "calibration.png")
            plt.savefig(path, dpi=120)
            print(f"Plot saved to {path}")
            if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
                plt.show()
        except Exception as error:
            print(f"Plot failed ({error}) - numbers above are saved.")
    else:
        print()
        print("No plot: python3.11 -m pip install matplotlib")


if __name__ == "__main__":
    main()
