#!/usr/bin/env python3
"""Read the raw stream from an HC-05 over Bluetooth SPP.

The HC-05 bridges the Arduino's serial port, so whatever the sketch prints
arrives here verbatim. Nothing is assumed about the format.

  python3.11 host/bt_read.py                    # print lines as they arrive
  python3.11 host/bt_read.py --hex              # hex dump (for binary / unknown format)
  python3.11 host/bt_read.py --out raw.log      # also save a copy
  python3.11 host/bt_read.py --seconds 20

Pair first (PIN 1234); HC-05 refuses connections while bonded to another master.
"""

import argparse
import socket
import sys
import time

HC05_MAC = "00:25:00:00:56:86"
SPP_CHANNEL = 1  # HC-05 always publishes SPP on RFCOMM channel 1


def connect(mac, channel, timeout):
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    sock.settimeout(timeout)
    sock.connect((mac, channel))
    return sock


def hexdump(offset, chunk):
    hexpart = " ".join(f"{b:02x}" for b in chunk)
    text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
    return f"{offset:08x}  {hexpart:<47}  |{text}|"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mac", default=HC05_MAC)
    ap.add_argument("--channel", type=int, default=SPP_CHANNEL)
    ap.add_argument("--seconds", type=float, help="stop after this long")
    ap.add_argument("--hex", action="store_true", help="hex dump instead of text lines")
    ap.add_argument("--out", help="also write the raw bytes to this file")
    ap.add_argument("--timeout", type=float, default=10.0, help="connect timeout")
    args = ap.parse_args()

    print(f"connecting to {args.mac} channel {args.channel} ...", file=sys.stderr)
    try:
        sock = connect(args.mac, args.channel, args.timeout)
    except OSError as e:
        sys.exit(
            f"connect failed: {e}\n"
            "  - HC-05 allows only one master at a time; disconnect the other device\n"
            "  - confirm it is paired: bluetoothctl info " + args.mac
        )
    print("connected. reading...", file=sys.stderr)

    raw = open(args.out, "wb") if args.out else None
    start = time.time()
    total = 0
    pending = b""
    try:
        while args.seconds is None or time.time() - start < args.seconds:
            try:
                chunk = sock.recv(1024)
            except socket.timeout:
                continue
            if not chunk:
                print("\nremote closed the connection", file=sys.stderr)
                break
            if raw:
                raw.write(chunk)

            if args.hex:
                for i in range(0, len(chunk), 16):
                    print(hexdump(total + i, chunk[i:i + 16]))
            else:
                # Buffer until newline so partial lines are not split mid-sample.
                pending += chunk
                *lines, pending = pending.split(b"\n")
                for line in lines:
                    print(line.decode("utf-8", "replace").rstrip("\r"))
            total += len(chunk)
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        if pending and not args.hex:
            print(pending.decode("utf-8", "replace"))
        sock.close()
        if raw:
            raw.close()
        elapsed = time.time() - start
        print(f"\n{total} bytes in {elapsed:.1f}s ({total / max(elapsed, 1e-6):.0f} B/s)",
              file=sys.stderr)
        if args.out:
            print(f"raw saved to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
