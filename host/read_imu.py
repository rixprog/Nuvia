#!/usr/bin/env python3
"""Read the ESP32 IMU stream: live view, CSV logging, or raw passthrough.

  python3.11 host/read_imu.py                  # live orientation view
  python3.11 host/read_imu.py --csv run.csv    # log to CSV while viewing
  python3.11 host/read_imu.py --raw            # dump lines as they arrive
"""

import argparse
import math
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial missing. Install with: python3.11 -m pip install pyserial")

FIELDS = ["millis", "ax", "ay", "az", "gx", "gy", "gz", "temp_c"]


def open_port(port, baud):
    s = serial.Serial(port, baud, timeout=1)
    # Pulse RTS to reset the board so we catch the boot log and a fresh stream.
    s.setDTR(False)
    s.setRTS(True)
    time.sleep(0.1)
    s.setRTS(False)
    s.reset_input_buffer()
    return s


def parse(line):
    if not line.startswith("D,"):
        return None
    parts = line.split(",")
    if len(parts) != len(FIELDS) + 1:
        return None
    try:
        return dict(zip(FIELDS, (float(p) for p in parts[1:])))
    except ValueError:
        return None


def bar(value, lo, hi, width=24):
    frac = min(1.0, max(0.0, (value - lo) / (hi - lo)))
    mark = round(frac * (width - 1))
    return "[" + "-" * mark + "#" + "-" * (width - 1 - mark) + "]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--csv", help="write samples to this CSV file")
    ap.add_argument("--raw", action="store_true", help="print every line verbatim")
    ap.add_argument("--seconds", type=float, help="stop after this long")
    args = ap.parse_args()

    ser = open_port(args.port, args.baud)
    csv = open(args.csv, "w", buffering=1) if args.csv else None
    if csv:
        csv.write(",".join(FIELDS) + ",pitch_deg,roll_deg\n")

    start = time.time()
    count = 0
    last_draw = 0.0
    try:
        while args.seconds is None or time.time() - start < args.seconds:
            line = ser.readline().decode("utf-8", "replace").strip()
            if not line:
                continue
            if args.raw:
                print(line)
                continue

            sample = parse(line)
            if sample is None:
                # Boot log or the CSV header: worth showing, it names the chip.
                print(line, file=sys.stderr)
                continue

            count += 1
            ax, ay, az = sample["ax"], sample["ay"], sample["az"]
            pitch = math.degrees(math.atan2(-ax, math.hypot(ay, az)))
            roll = math.degrees(math.atan2(ay, az))

            if csv:
                csv.write(",".join(f"{sample[f]:.4f}" for f in FIELDS)
                          + f",{pitch:.2f},{roll:.2f}\n")

            now = time.time()
            if now - last_draw > 0.05:
                last_draw = now
                rate = count / max(1e-6, now - start)
                print(
                    f"\rpitch {pitch:+6.1f}deg {bar(pitch, -90, 90)}  "
                    f"roll {roll:+6.1f}deg {bar(roll, -180, 180)}  "
                    f"|g| {math.sqrt(ax*ax + ay*ay + az*az):4.2f}  "
                    f"{sample['temp_c']:4.1f}C  {rate:5.1f}Hz",
                    end="", flush=True,
                )
    except KeyboardInterrupt:
        pass
    finally:
        print()
        if csv:
            csv.close()
            print(f"wrote {count} samples to {args.csv}")
        ser.close()


if __name__ == "__main__":
    main()
