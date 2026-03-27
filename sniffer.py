"""
Thread/802.15.4 Network Sniffer - Serial interface to nRF52840 dongle.
Captures packets, extracts RSSI/LQI per device, writes pcap files.
"""

import re
import time
import struct
import binascii
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime


PACKET_RE = re.compile(
    r"received:\s+([0-9a-fA-F]+)\s+power:\s+(-?\d+)\s+lqi:\s+(\d+)\s+time:\s+(-?\d+)"
)

# 802.15.4 frame type constants
FRAME_TYPE_BEACON = 0
FRAME_TYPE_DATA = 1
FRAME_TYPE_ACK = 2
FRAME_TYPE_CMD = 3

FRAME_TYPE_NAMES = {
    FRAME_TYPE_BEACON: "Beacon",
    FRAME_TYPE_DATA: "Data",
    FRAME_TYPE_ACK: "ACK",
    FRAME_TYPE_CMD: "Command",
}

# OUI database — first 3 bytes (big-endian) of EUI-64 → manufacturer
# EUI-64 can embed OUI in bytes 0-2 (with bytes 3-4 = FF:FE for EUI-48 derived)
OUI_DB = {
    # IKEA
    "D4:F0:EA": "IKEA", "94:B9:7E": "IKEA", "CC:D2:81": "IKEA",
    "EC:0B:AE": "IKEA", "B4:E8:42": "IKEA", "68:EC:8A": "IKEA",
    "34:25:BE": "IKEA", "50:32:75": "IKEA", "A4:CF:12": "IKEA",
    "DC:A6:32": "IKEA", "30:C6:F7": "IKEA", "78:AB:BB": "IKEA",
    # Silicon Labs
    "00:0B:57": "Silicon Labs", "04:CD:15": "Silicon Labs",
    "58:8E:81": "Silicon Labs", "84:FD:27": "Silicon Labs",
    "0C:43:14": "Silicon Labs", "68:5E:DD": "Silicon Labs",
    # Nordic Semiconductor
    "D4:CA:6E": "Nordic Semi", "E8:DB:84": "Nordic Semi",
    "F4:CE:36": "Nordic Semi", "E0:6C:B5": "Nordic Semi",
    # Espressif / ESP32
    "24:6F:28": "Espressif", "AC:67:B2": "Espressif",
    "30:AE:A4": "Espressif", "A4:CF:12": "Espressif",
    # Apple
    "28:6B:35": "Apple", "3C:E0:72": "Apple", "A8:51:AB": "Apple",
    "F0:B3:EC": "Apple", "64:B0:A6": "Apple",
    # Google/Nest
    "18:D6:C7": "Google", "54:60:09": "Google", "F4:F5:D8": "Google",
    "A4:77:33": "Google/Nest", "64:16:66": "Google/Nest",
    # Nanoleaf
    "60:FD:A8": "Nanoleaf",
    # Eve (Elgato)
    "D0:03:4B": "Eve",
    # Philips/Signify (Hue)
    "00:17:88": "Philips Hue", "EC:B5:FA": "Signify",
    # Aqara / Lumi
    "54:EF:44": "Aqara/Lumi", "04:CF:8C": "Aqara/Lumi",
    # Lidl / Silvercrest
    "84:BA:20": "Lidl/Silvercrest",
    # Tuya
    "D8:1F:12": "Tuya",
    # Sonoff
    "80:64:6F": "Sonoff",
    # Generic Thread/Zigbee chip vendors often seen
    "1C:F6:4C": "Samsung", "20:50:E7": "Samsung",
    "C2:39:6F": "Unknown (random)",
}


def lookup_oui(extended_addr):
    """Look up manufacturer from an extended (EUI-64) address string like 'AA:BB:CC:DD:EE:FF:00:11'."""
    parts = extended_addr.split(":")
    if len(parts) < 3:
        return None
    oui = ":".join(parts[0:3])
    return OUI_DB.get(oui)


def infer_role(dev):
    """Infer device role from behavior."""
    if dev.address == "0x0000":
        return "Border Router"
    ft = dev.frame_types
    total = dev.frame_count
    if total == 0:
        return "Unknown"
    # Devices that send beacons are routers
    if ft.get("Beacon", 0) > 0:
        return "Router"
    # Devices that send commands and have multiple peers are likely routers
    if ft.get("Command", 0) > 0 and len(dev.peers) > 2:
        return "Router"
    # High packet rate with data frames → likely router (repeater)
    if total > 20 and ft.get("Data", 0) / max(total, 1) > 0.8:
        return "Router (likely)"
    # Devices that only talk to one peer are likely end devices (sleepy)
    if len(dev.peers) <= 1:
        return "End Device"
    return "Router/End Device"


@dataclass
class DeviceInfo:
    """Accumulated info about a discovered 802.15.4 device."""
    address: str
    short_address: str = ""
    extended_address: str = ""
    manufacturer: str = ""
    rssi_samples: list = field(default_factory=list)
    lqi_samples: list = field(default_factory=list)
    frame_count: int = 0
    last_seen: float = 0.0
    first_seen: float = 0.0
    frame_types: dict = field(default_factory=lambda: defaultdict(int))
    peers: dict = field(default_factory=lambda: defaultdict(int))  # address -> packet count
    is_coordinator: bool = False

    @property
    def avg_rssi(self) -> float:
        if not self.rssi_samples:
            return -100.0
        return sum(self.rssi_samples[-100:]) / len(self.rssi_samples[-100:])

    @property
    def min_rssi(self) -> float:
        if not self.rssi_samples:
            return -100.0
        return min(self.rssi_samples[-100:])

    @property
    def max_rssi(self) -> float:
        if not self.rssi_samples:
            return -100.0
        return max(self.rssi_samples[-100:])

    @property
    def avg_lqi(self) -> float:
        if not self.lqi_samples:
            return 0.0
        return sum(self.lqi_samples[-100:]) / len(self.lqi_samples[-100:])

    @property
    def signal_quality(self) -> str:
        rssi = self.avg_rssi
        if rssi >= -60:
            return "excellent"
        elif rssi >= -70:
            return "good"
        elif rssi >= -80:
            return "fair"
        elif rssi >= -90:
            return "weak"
        else:
            return "very_weak"


@dataclass
class LinkInfo:
    """Signal quality between two devices."""
    src: str
    dst: str
    rssi_samples: list = field(default_factory=list)
    lqi_samples: list = field(default_factory=list)
    packet_count: int = 0
    last_seen: float = 0.0

    @property
    def avg_rssi(self) -> float:
        if not self.rssi_samples:
            return -100.0
        return sum(self.rssi_samples[-50:]) / len(self.rssi_samples[-50:])

    @property
    def avg_lqi(self) -> float:
        if not self.lqi_samples:
            return 0.0
        return sum(self.lqi_samples[-50:]) / len(self.lqi_samples[-50:])


def parse_802154_frame(raw_bytes):
    """Parse an 802.15.4 MAC frame header. Returns dict with src, dst, frame_type."""
    if len(raw_bytes) < 3:
        return None

    # Frame Control Field (2 bytes, little-endian)
    fcf = struct.unpack("<H", raw_bytes[0:2])[0]
    frame_type = fcf & 0x07
    security_enabled = (fcf >> 3) & 0x01
    frame_pending = (fcf >> 4) & 0x01
    ack_request = (fcf >> 5) & 0x01
    panid_compress = (fcf >> 6) & 0x01
    dst_addr_mode = (fcf >> 10) & 0x03
    frame_version = (fcf >> 12) & 0x03
    src_addr_mode = (fcf >> 14) & 0x03

    result = {
        "frame_type": frame_type,
        "frame_type_name": FRAME_TYPE_NAMES.get(frame_type, f"Unknown({frame_type})"),
        "security": security_enabled,
        "ack_request": ack_request,
        "version": frame_version,
        "src": None,
        "dst": None,
        "src_short": None,
        "dst_short": None,
        "src_ext": None,
        "dst_ext": None,
    }

    # Sequence Number (1 byte)
    idx = 3

    # ACK frames have no addressing
    if frame_type == FRAME_TYPE_ACK:
        return result

    # Destination PAN ID + Address
    if dst_addr_mode == 2:  # Short address (2 bytes)
        if idx + 4 > len(raw_bytes):
            return result
        dst_pan = struct.unpack("<H", raw_bytes[idx:idx+2])[0]
        dst_addr = struct.unpack("<H", raw_bytes[idx+2:idx+4])[0]
        result["dst"] = f"0x{dst_addr:04X}"
        result["dst_short"] = f"0x{dst_addr:04X}"
        idx += 4
    elif dst_addr_mode == 3:  # Extended address (8 bytes)
        if idx + 10 > len(raw_bytes):
            return result
        dst_pan = struct.unpack("<H", raw_bytes[idx:idx+2])[0]
        dst_addr = raw_bytes[idx+2:idx+10]
        ext_str = ":".join(f"{b:02X}" for b in reversed(dst_addr))
        result["dst"] = ext_str
        result["dst_ext"] = ext_str
        result["dst_short"] = f"0x{struct.unpack('<H', dst_addr[0:2])[0]:04X}"
        idx += 10
    elif dst_addr_mode == 0:
        pass  # No destination address
    else:
        return result

    # Source PAN ID + Address
    if src_addr_mode > 0 and not panid_compress:
        if idx + 2 > len(raw_bytes):
            return result
        idx += 2  # Skip source PAN ID

    if src_addr_mode == 2:  # Short address
        if idx + 2 > len(raw_bytes):
            return result
        src_addr = struct.unpack("<H", raw_bytes[idx:idx+2])[0]
        result["src"] = f"0x{src_addr:04X}"
        result["src_short"] = f"0x{src_addr:04X}"
        idx += 2
    elif src_addr_mode == 3:  # Extended address
        if idx + 8 > len(raw_bytes):
            return result
        src_addr = raw_bytes[idx:idx+8]
        ext_str = ":".join(f"{b:02X}" for b in reversed(src_addr))
        result["src"] = ext_str
        result["src_ext"] = ext_str
        result["src_short"] = f"0x{struct.unpack('<H', src_addr[0:2])[0]:04X}"
        idx += 8

    return result


class ThreadSniffer:
    """Captures 802.15.4 packets from nRF52840 dongle and tracks device stats."""

    def __init__(self, port="COM3", channel=15):
        self.port = port
        self.channel = channel
        self.devices = {}       # address -> DeviceInfo
        self.links = {}         # (src, dst) -> LinkInfo
        self.packets = []       # recent raw packets for debug
        self._ext_to_short = {} # extended addr -> short addr
        self._short_to_ext = {} # short addr -> extended addr
        self.lock = threading.Lock()
        self._running = False
        self._thread = None
        self._serial = None
        self.total_packets = 0
        self.start_time = None
        self.pcap_file = None
        self.pcap_path = None
        self.connected = False
        self._reconnect_count = 0

    def _open_serial(self):
        """Open serial port and initialize dongle. Returns True on success."""
        import serial
        try:
            if self._serial:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None

            self._serial = serial.Serial(self.port, exclusive=True, timeout=1)

            # Initialize dongle — drain any buffered data first
            self._serial.reset_input_buffer()
            self._send("sleep")
            time.sleep(0.5)
            self._serial.reset_input_buffer()
            self._send("shell echo off")
            time.sleep(0.3)
            self._serial.reset_input_buffer()
            self._send(f"channel {self.channel}")
            time.sleep(0.3)
            self._serial.reset_input_buffer()
            self._send("receive")
            time.sleep(0.2)

            self.connected = True
            return True
        except Exception as e:
            self.connected = False
            self._serial = None
            return False

    def _clear_stale_data(self):
        """Reset device/link data on reconnect so the dashboard starts fresh."""
        with self.lock:
            self.devices.clear()
            self.links.clear()
            self.packets.clear()
            self._ext_to_short.clear()
            self._short_to_ext.clear()
            self.total_packets = 0
            self.start_time = time.time()

    def start(self, pcap_path=None):
        """Start capturing in a background thread."""
        self._running = True
        self.start_time = time.time()

        if pcap_path:
            self.pcap_path = pcap_path
            self.pcap_file = open(pcap_path, "wb")
            self._write_pcap_header()

        if not self._open_serial():
            print(f"  WARNING: Dongle not found on {self.port} — will retry automatically")

        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop capturing."""
        self._running = False
        self.connected = False
        if self._serial:
            try:
                self._send("sleep")
                time.sleep(0.2)
                self._serial.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=3)
        if self.pcap_file:
            self.pcap_file.close()
            self.pcap_file = None

    def set_channel(self, channel):
        """Change the capture channel (11-26)."""
        self.channel = channel
        if self._serial and self._running:
            self._send("sleep")
            time.sleep(0.1)
            self._send(f"channel {channel}")
            time.sleep(0.1)
            self._send("receive")

    def _send(self, cmd):
        if self._serial and self._serial.is_open:
            self._serial.write(f"{cmd}\r\n".encode())

    def _capture_loop(self):
        buf = ""
        # Strip ANSI escape codes from firmware output
        import re as _re
        ansi_re = _re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
        while self._running:
            # If not connected, try to reconnect
            if not self.connected or not self._serial:
                time.sleep(2)
                if not self._running:
                    break
                if self._open_serial():
                    self._reconnect_count += 1
                    print(f"  Dongle reconnected on {self.port} (reconnect #{self._reconnect_count})")
                    buf = ""  # reset buffer on reconnect
                    self._clear_stale_data()
                continue

            try:
                data = self._serial.read(4096)
                if not data:
                    continue
                text = data.decode("ascii", errors="ignore")
                text = ansi_re.sub("", text)  # strip ANSI escapes
                buf += text
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    m = PACKET_RE.search(line)  # search, not match — line may have prefix
                    if m:
                        self._process_packet(
                            hex_data=m.group(1),
                            rssi=int(m.group(2)),
                            lqi=int(m.group(3)),
                            timestamp=int(m.group(4)),
                        )
            except Exception as e:
                if self._running:
                    self.connected = False
                    print(f"  Dongle disconnected ({type(e).__name__}: {e}) — waiting for reconnect...")
                    try:
                        self._serial.close()
                    except Exception:
                        pass
                    self._serial = None

    def _process_packet(self, hex_data, rssi, lqi, timestamp):
        # Strip FCS (last 2 bytes = 4 hex chars)
        if len(hex_data) > 4:
            frame_hex = hex_data[:-4]
        else:
            frame_hex = hex_data

        try:
            raw = binascii.a2b_hex(frame_hex)
        except Exception:
            return

        parsed = parse_802154_frame(raw)
        if not parsed:
            return

        now = time.time()

        with self.lock:
            self.total_packets += 1

            # Keep last 200 packets for display
            self.packets.append({
                "time": now,
                "rssi": rssi,
                "lqi": lqi,
                "src": parsed["src"],
                "dst": parsed["dst"],
                "type": parsed["frame_type_name"],
                "size": len(raw),
            })
            if len(self.packets) > 200:
                self.packets = self.packets[-200:]

            # Map extended addresses to short addresses
            src_key = parsed["src"]
            dst_key = parsed["dst"]

            # If we see an extended address with a short address, create mapping
            if parsed.get("src_ext"):
                ext = parsed["src_ext"]
                short = parsed.get("src_short")
                if ext and short:
                    self._ext_to_short[ext] = short
                    self._short_to_ext[short] = ext
                # Use short address as primary key if available
                if short and short in self.devices:
                    src_key = short
                elif short:
                    src_key = short

            if parsed.get("dst_ext"):
                ext = parsed["dst_ext"]
                short = parsed.get("dst_short")
                if ext and short:
                    self._ext_to_short[ext] = short
                    self._short_to_ext[short] = ext
                if short and short in self.devices:
                    dst_key = short
                elif short:
                    dst_key = short

            # Track source device
            if src_key:
                dev = self._get_device(src_key)
                dev.rssi_samples.append(rssi)
                dev.lqi_samples.append(lqi)
                dev.frame_count += 1
                dev.last_seen = now
                dev.frame_types[parsed["frame_type_name"]] += 1
                if parsed.get("src_short"):
                    dev.short_address = parsed["src_short"]
                # Store extended address and look up manufacturer
                if parsed.get("src_ext") and not dev.extended_address:
                    dev.extended_address = parsed["src_ext"]
                    mfr = lookup_oui(parsed["src_ext"])
                    if mfr:
                        dev.manufacturer = mfr
                # Also check reverse mapping
                if not dev.extended_address and src_key in self._short_to_ext:
                    dev.extended_address = self._short_to_ext[src_key]
                    mfr = lookup_oui(dev.extended_address)
                    if mfr:
                        dev.manufacturer = mfr
                if dst_key:
                    dev.peers[dst_key] += 1

                # Track link
                if dst_key and dst_key != "0xFFFF":
                    link_key = (src_key, dst_key)
                    if link_key not in self.links:
                        self.links[link_key] = LinkInfo(src=src_key, dst=dst_key)
                    link = self.links[link_key]
                    link.rssi_samples.append(rssi)
                    link.lqi_samples.append(lqi)
                    link.packet_count += 1
                    link.last_seen = now

            # Track destination device (we see it being addressed)
            if dst_key and dst_key != "0xFFFF":
                dst_dev = self._get_device(dst_key)
                if not dst_dev.first_seen:
                    dst_dev.first_seen = now
                dst_dev.last_seen = now
                # Check reverse mapping for ext address
                if not dst_dev.extended_address and dst_key in self._short_to_ext:
                    dst_dev.extended_address = self._short_to_ext[dst_key]
                    mfr = lookup_oui(dst_dev.extended_address)
                    if mfr:
                        dst_dev.manufacturer = mfr

        # Write to pcap
        if self.pcap_file:
            self._write_pcap_packet(raw, rssi, lqi, timestamp)

    def _get_device(self, address):
        if address not in self.devices:
            self.devices[address] = DeviceInfo(
                address=address,
                first_seen=time.time(),
                last_seen=time.time(),
            )
        return self.devices[address]

    def _write_pcap_header(self):
        # Global pcap header with DLT 283 (IEEE802_15_4_TAP)
        header = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 255, 283)
        self.pcap_file.write(header)
        self.pcap_file.flush()

    def _write_pcap_packet(self, raw, rssi, lqi, timestamp_ms):
        now = time.time()
        ts_sec = int(now)
        ts_usec = int((now - ts_sec) * 1_000_000)

        # Build IEEE 802.15.4 TAP header (28 bytes)
        tap = struct.pack("<HH", 0, 28)                      # version, total length
        tap += struct.pack("<HHf", 1, 4, float(rssi))        # RSS TLV
        tap += struct.pack("<HHHH", 3, 3, self.channel, 0)   # Channel TLV
        tap += struct.pack("<HHI", 10, 1, lqi)               # LQI TLV

        pkt_data = tap + raw
        pkt_len = len(pkt_data)

        # Packet record header
        rec = struct.pack("<IIII", ts_sec, ts_usec, pkt_len, pkt_len)
        self.pcap_file.write(rec + pkt_data)
        self.pcap_file.flush()

    def get_snapshot(self):
        """Return current state as a dict for the dashboard."""
        with self.lock:
            now = time.time()
            devices = []
            for addr, dev in sorted(self.devices.items(), key=lambda x: x[1].avg_rssi, reverse=True):
                devices.append({
                    "address": dev.address,
                    "short_address": dev.short_address,
                    "extended_address": dev.extended_address,
                    "manufacturer": dev.manufacturer,
                    "role": infer_role(dev),
                    "avg_rssi": round(dev.avg_rssi, 1),
                    "min_rssi": round(dev.min_rssi, 1),
                    "max_rssi": round(dev.max_rssi, 1),
                    "avg_lqi": round(dev.avg_lqi, 1),
                    "signal_quality": dev.signal_quality,
                    "frame_count": dev.frame_count,
                    "last_seen_ago": round(now - dev.last_seen, 1) if dev.last_seen else None,
                    "frame_types": dict(dev.frame_types),
                    "peer_count": len(dev.peers),
                    "peers": dict(dev.peers),
                })

            links = []
            for (src, dst), link in self.links.items():
                links.append({
                    "src": src,
                    "dst": dst,
                    "avg_rssi": round(link.avg_rssi, 1),
                    "avg_lqi": round(link.avg_lqi, 1),
                    "packet_count": link.packet_count,
                    "last_seen_ago": round(now - link.last_seen, 1),
                })

            return {
                "channel": self.channel,
                "total_packets": self.total_packets,
                "uptime_seconds": round(now - self.start_time, 0) if self.start_time else 0,
                "device_count": len(self.devices),
                "connected": self.connected,
                "reconnect_count": self._reconnect_count,
                "devices": devices,
                "links": links,
                "recent_packets": self.packets[-50:],
                "pcap_path": self.pcap_path,
            }

    def snapshot_link_counts(self):
        """Take a snapshot of current link packet counts (from hub)."""
        with self.lock:
            counts = {}
            for (src, dst), link in self.links.items():
                if src == "0x0000":
                    counts[dst] = link.packet_count
                elif dst == "0x0000":
                    counts[src] = counts.get(src, 0)  # ensure device is tracked
            # Also snapshot total per device
            for addr, dev in self.devices.items():
                counts[addr] = counts.get(addr, 0) + dev.frame_count
            return counts

    def snapshot_send_counts(self):
        """Snapshot per-device sent packet counts (frames where device is the source)."""
        with self.lock:
            counts = {}
            for addr, dev in self.devices.items():
                counts[addr] = dev.frame_count
            return counts

    def detect_sender_spike(self, baseline, min_delta=2):
        """Detect which device started sending more packets since baseline."""
        with self.lock:
            current = {}
            for addr, dev in self.devices.items():
                current[addr] = dev.frame_count

        spikes = []
        for addr, cur_count in current.items():
            base_count = baseline.get(addr, 0)
            delta = cur_count - base_count
            if delta >= min_delta and addr != "0x0000":  # exclude hub
                spikes.append((addr, delta))

        spikes.sort(key=lambda x: x[1], reverse=True)
        return spikes

    def detect_spike(self, baseline, min_delta=3):
        """Compare current link counts to baseline. Returns list of (addr, delta) sorted by delta."""
        with self.lock:
            current = {}
            for (src, dst), link in self.links.items():
                if src == "0x0000":
                    current[dst] = link.packet_count
                elif dst == "0x0000":
                    current[src] = current.get(src, 0)
            for addr, dev in self.devices.items():
                current[addr] = current.get(addr, 0) + dev.frame_count

        spikes = []
        for addr, cur_count in current.items():
            base_count = baseline.get(addr, 0)
            delta = cur_count - base_count
            if delta >= min_delta:
                spikes.append((addr, delta))

        spikes.sort(key=lambda x: x[1], reverse=True)
        return spikes
