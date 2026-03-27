# Thread Network Monitor - Agent Guide

This file is for AI coding assistants (Claude Code, Cursor, etc.) working on or with this project. It explains the architecture, the identification algorithm, and known pitfalls.

## Project Overview

A Flask web dashboard (`dashboard.py`) that captures 802.15.4/Thread radio packets via an nRF52840 USB sniffer dongle and visualizes the mesh network. It integrates with an IKEA Dirigera hub to map human-readable device names to Thread short addresses (e.g. `0x2C14`).

## Architecture

```
dashboard.py          Flask app, HTML/JS frontend, REST API
  -> sniffer.py       Serial interface to nRF52840, packet parsing, device tracking
  -> dirigera_client.py  Dirigera hub OAuth2 client, device listing, blink/toggle
```

- **Labels** are stored in `device_labels.json` (address -> {name, type, room}).
- The sniffer runs in a background thread with auto-reconnect if the dongle is removed.
- The dashboard is deployed on a Windows PC (`Q`) at `C:\tools\thread-monitor\` and runs as a scheduled task (`ThreadMonitor`).

## Key API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/snapshot` | GET | Full sniffer state: devices, links, packets, connection status |
| `/api/labels` | GET | Current device labels |
| `/api/label` | POST | Set/clear a label `{address, name, type, room}` |
| `/api/dirigera/devices` | GET | List all Dirigera hub devices (summarized) |
| `/api/dirigera/blink-identify` | POST | Blink one device and detect its Thread address |
| `/api/dirigera/identify-all/start` | POST | Start batch identification of all unassigned devices |
| `/api/dirigera/identify-all/status` | GET | Poll batch progress |
| `/api/dirigera/identify-all/stop` | POST | Cancel batch identification |

## The Identification Algorithm

Auto-identify works by:

1. Taking a baseline snapshot of per-device packet counts
2. Triggering a device action via the Dirigera hub (toggle lights, nudge blinds)
3. Waiting for traffic (2s for lights, 3s for blinds)
4. Measuring which Thread address had the largest traffic spike
5. Assigning the label if the spike is confident (dominant candidate)

Two detection methods are combined:
- `detect_spike()` — tracks link-level packet counts (hub-to-device and device-to-hub links)
- `detect_sender_spike()` — tracks per-device sent frame counts

Results are merged and the address with the highest combined delta wins.

## Known Pitfalls — Read Before Debugging Identification

### 1. Mesh relay causes false positives

Thread is a mesh network. When device A is toggled, its packets may be relayed by devices B and C. The sniffer sees B and C transmitting, not A directly. This means:

- The **spike on address X doesn't necessarily mean X is the toggled device** — X might be a router relaying for the actual device.
- Devices close together (e.g. multiple lights on one fixture or table) produce overlapping spikes and are easily confused.

### 2. Already-labeled addresses are filtered out

The algorithm filters spikes: `a not in labeled_addrs`. This means if device A was **mislabeled** as address X, then the real device X can never be identified because its address is excluded as "already assigned."

**This is the #1 cause of "no spike detected" failures.** When a device can't be identified, first check whether its real address was already claimed by a wrong label.

### 3. Distant devices produce weak or invisible spikes

The sniffer dongle has limited radio range. Devices far from it communicate through mesh routers. Their direct transmissions may be too weak to detect, and all visible traffic appears on the router's address instead.

### 4. Blinds produce weaker spikes than lights

Lights toggle on/off (large state change, multiple packets). Blinds nudge by 5% (small command). Blinds spikes are typically 3-5x weaker than light spikes.

### 5. Batch "Identify All" compounds errors

Sequential identification means early misidentifications affect later ones (see pitfall #2). Devices identified later in the batch are more likely to fail if an earlier device claimed the wrong address.

## How to Debug Identification Problems

If a device can't be auto-identified, follow this process:

### Step 1: Manual blink test

```bash
# Take baseline
BEFORE=$(curl -s http://<host>:8154/api/snapshot)

# Wait 1s, take fresh baseline
sleep 1
BEFORE=$(curl -s http://<host>:8154/api/snapshot)

# Blink the device (get device_id from /api/dirigera/devices)
curl -s -X POST http://<host>:8154/api/dirigera/blink-identify \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"<id>","device_name":"<name>","device_type":"<type>","device_room":"<room>"}'

# Or blink directly on the host machine:
ssh Q "cd C:\tools\thread-monitor && python -c \"
from dirigera_client import DigeraClient
d = DigeraClient(ip='192.168.200.156')
d.blink_device('<device_id>')
\""

# Wait, then compare
sleep 4
AFTER=$(curl -s http://<host>:8154/api/snapshot)
# Compare frame_count per device between BEFORE and AFTER
```

### Step 2: Check ALL spikes, including labeled addresses

Don't filter out labeled addresses — the target might be hidden behind an existing label. Look at the raw spike list including already-assigned addresses.

### Step 3: Cross-verify existing labels

If the target's address appears to be already labeled as something else, blink that "something else" and see if the same address is its dominant spike. If not — the label is wrong.

### Step 4: Fix and re-identify

```bash
# Remove wrong label
curl -s -X POST http://<host>:8154/api/label \
  -H 'Content-Type: application/json' \
  -d '{"address":"0xXXXX","name":""}'

# Assign correct label
curl -s -X POST http://<host>:8154/api/label \
  -H 'Content-Type: application/json' \
  -d '{"address":"0xXXXX","name":"Right","type":"blinds","room":"Living Room"}'
```

## Deployment

- **Host**: Windows PC `Q` at `192.168.200.100`
- **Serial port**: COM4 (nRF52840 dongle, VID:PID 1915:154B)
- **Channel**: 20 (Thread network)
- **Dirigera hub**: `192.168.200.156`
- **Scheduled task**: `ThreadMonitor` (runs on boot, auto-restarts on crash)
- **Dashboard URL**: `http://192.168.200.100:8154`

### Start/stop manually

```powershell
# On Q (PowerShell)
schtasks /Run /TN "ThreadMonitor"     # start
schtasks /End /TN "ThreadMonitor"     # stop

# Remote via SSH
ssh Q "powershell -Command \"Start-Process -FilePath python -ArgumentList 'C:\\tools\\thread-monitor\\dashboard.py --port COM4 --channel 20 --hub-ip 192.168.200.156' -WorkingDirectory 'C:\\tools\\thread-monitor' -WindowStyle Hidden\""
```

## Dongle Resilience

The sniffer auto-reconnects if the USB dongle is removed and re-plugged. On reconnect, all stale device data is cleared and capture restarts fresh. The dashboard shows connection status (green dot = connected, orange pulsing = disconnected/reconnecting).
