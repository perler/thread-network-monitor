"""Scan all 802.15.4 channels (11-26) to find active Thread networks."""
import serial
import time
import re
import sys

PACKET_RE = re.compile(r"received:\s+([0-9a-fA-F]+)\s+power:\s+(-?\d+)\s+lqi:\s+(\d+)\s+time:\s+(-?\d+)")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

SCAN_SECONDS = 3  # seconds per channel

def scan(port_name="COM4"):
    port = serial.Serial(port_name, timeout=1)
    time.sleep(0.3)
    port.reset_input_buffer()
    port.write(b"sleep\r\n")
    time.sleep(0.5)
    port.write(b"shell echo off\r\n")
    time.sleep(0.3)
    port.reset_input_buffer()

    results = []
    for ch in range(11, 27):
        port.reset_input_buffer()
        port.write(f"channel {ch}\r\n".encode())
        time.sleep(0.15)
        port.write(b"receive\r\n")
        time.sleep(0.1)
        port.reset_input_buffer()

        start = time.time()
        pkts = []
        buf = ""
        while time.time() - start < SCAN_SECONDS:
            data = port.read(4096)
            if data:
                buf += ANSI_RE.sub("", data.decode("ascii", errors="ignore"))
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    m = PACKET_RE.search(line.strip())
                    if m:
                        pkts.append(int(m.group(2)))

        port.write(b"sleep\r\n")
        time.sleep(0.1)
        results.append((ch, pkts))

    port.write(b"sleep\r\n")
    port.close()
    return results


if __name__ == "__main__":
    port_name = sys.argv[1] if len(sys.argv) > 1 else "COM4"

    with open("scan_results.txt", "w") as f:
        f.write("802.15.4 Channel Scan Results\n")
        f.write("=" * 60 + "\n")
        results = scan(port_name)
        for ch, pkts in results:
            if pkts:
                avg = sum(pkts) / len(pkts)
                best = max(pkts)
                line = f"Ch {ch:2d}: {len(pkts):3d} packets | avg RSSI: {avg:6.1f} dBm | best: {best:4d} dBm"
            else:
                line = f"Ch {ch:2d}:   0 packets"
            f.write(line + "\n")
            print(line, flush=True)

        # Summary
        active = [(ch, p) for ch, p in results if p]
        f.write("\n")
        if active:
            best_ch = max(active, key=lambda x: len(x[1]))
            f.write(f"Most active channel: {best_ch[0]} ({len(best_ch[1])} packets)\n")
        else:
            f.write("No active channels found!\n")
        f.write("SCAN COMPLETE\n")

    print("\nResults saved to scan_results.txt")
