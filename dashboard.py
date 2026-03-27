"""
Thread Network Monitor - Web Dashboard
Serves a live-updating web UI showing device signal strength, link quality, and topology.
"""

import os
import sys
import json
import time
import signal
import argparse
import threading
from datetime import datetime

from flask import Flask, jsonify, render_template_string, request
from sniffer import ThreadSniffer

app = Flask(__name__)
sniffer = None

DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Thread Network Monitor</title>
<style>
  :root {
    --bg: #f5f6f8;
    --surface: #ffffff;
    --surface2: #f0f1f4;
    --border: #e0e2e8;
    --text: #1a1d27;
    --text-dim: #6b7085;
    --excellent: #16a34a;
    --good: #65a30d;
    --fair: #ca8a04;
    --weak: #ea580c;
    --very-weak: #dc2626;
    --accent: #4f46e5;
    --accent-dim: #6366f1;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
  }

  .header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
  }

  .header h1 {
    font-size: 20px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .header h1 .dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--excellent);
    animation: pulse 2s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  .stats-bar {
    display: flex;
    gap: 24px;
    font-size: 13px;
    color: var(--text-dim);
  }

  .stats-bar span { display: flex; align-items: center; gap: 6px; }
  .stats-bar .val { color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums; }

  .controls {
    display: flex;
    gap: 8px;
    align-items: center;
  }

  .controls select, .controls button {
    background: var(--surface2);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 13px;
    cursor: pointer;
  }

  .controls button:hover { background: var(--accent-dim); border-color: var(--accent); }
  .controls button.active { background: var(--accent); border-color: var(--accent); }

  .container {
    padding: 20px 24px;
    display: grid;
    gap: 20px;
  }

  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
  }

  .card-header {
    padding: 14px 18px;
    border-bottom: 1px solid var(--border);
    font-size: 14px;
    font-weight: 600;
    display: flex;
    align-items: center;
    justify-content: space-between;
    cursor: pointer;
    user-select: none;
  }

  .card-header:hover { background: var(--surface2); }

  .card-header .chevron {
    display: inline-block;
    width: 16px;
    height: 16px;
    margin-right: 6px;
    transition: transform 0.2s;
    color: var(--text-dim);
    flex-shrink: 0;
  }

  .card.collapsed .card-header { border-bottom: none; }
  .card-header .chevron { transform: rotate(90deg); }
  .card.collapsed .card-header .chevron { transform: rotate(0deg); }
  .card.collapsed .card-body { display: none; }
  .card.hidden-panel { display: none; }

  .card-header .badge {
    background: var(--surface2);
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    color: var(--text-dim);
  }

  /* Settings Panel */
  .settings-overlay {
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.4); z-index: 1000;
    display: flex; align-items: center; justify-content: center;
  }
  .settings-box {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 24px; min-width: 340px; max-width: 420px;
  }
  .settings-box h3 { margin-bottom: 16px; font-size: 16px; }
  .settings-row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 0; border-bottom: 1px solid var(--border);
  }
  .settings-row:last-child { border-bottom: none; }
  .settings-row label { font-size: 13px; }
  .toggle-switch {
    position: relative; width: 36px; height: 20px; cursor: pointer;
  }
  .toggle-switch input { opacity: 0; width: 0; height: 0; }
  .toggle-switch .slider {
    position: absolute; top: 0; left: 0; right: 0; bottom: 0;
    background: var(--border); border-radius: 10px; transition: 0.2s;
  }
  .toggle-switch .slider:before {
    content: ""; position: absolute; height: 14px; width: 14px;
    left: 3px; bottom: 3px; background: white; border-radius: 50%; transition: 0.2s;
  }
  .toggle-switch input:checked + .slider { background: var(--accent); }
  .toggle-switch input:checked + .slider:before { transform: translateX(16px); }

  /* Device Table */
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }

  th {
    text-align: left;
    padding: 10px 14px;
    color: var(--text-dim);
    font-weight: 500;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    user-select: none;
  }

  th:hover { color: var(--text); }

  td {
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    font-variant-numeric: tabular-nums;
  }

  tr:last-child td { border-bottom: none; }
  tr:hover td { background: var(--surface2); }

  .rssi-bar {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .rssi-bar .bar {
    flex: 1;
    height: 6px;
    background: var(--surface2);
    border-radius: 3px;
    overflow: hidden;
    min-width: 80px;
  }

  .rssi-bar .bar .fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.5s ease;
  }

  .signal-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
  }

  .signal-badge.excellent { background: rgba(22,163,74,0.12); color: var(--excellent); }
  .signal-badge.good { background: rgba(101,163,13,0.12); color: var(--good); }
  .signal-badge.fair { background: rgba(202,138,4,0.12); color: var(--fair); }
  .signal-badge.weak { background: rgba(234,88,12,0.12); color: var(--weak); }
  .signal-badge.very_weak { background: rgba(220,38,38,0.12); color: var(--very-weak); }

  /* Topology */
  .topology {
    padding: 20px;
    min-height: 300px;
  }

  svg.topo {
    width: 100%;
    height: 400px;
  }

  /* Subway Map */
  .subway-map { position: relative; padding: 12px; }
  .subway-map svg { width: 100%; height: auto; }
  .subway-line { fill: none; stroke-linecap: round; stroke-linejoin: round; transition: opacity 0.4s, stroke 0.4s; }
  .subway-station { transition: opacity 0.4s, r 0.15s; cursor: pointer; }
  .subway-station:hover { filter: brightness(1.1); }
  .subway-label { font-size: 11px; fill: var(--text); pointer-events: none; transition: opacity 0.4s; font-weight: 500; }
  .subway-label-bg { fill: var(--surface); opacity: 0.92; rx: 3; ry: 3; pointer-events: none; transition: opacity 0.4s; }
  .subway-room-bg { rx: 12; ry: 12; transition: opacity 0.4s; }
  .subway-room-label { font-size: 10px; fill: var(--text-dim); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
  .subway-map svg.dimmed .subway-line,
  .subway-map svg.dimmed .subway-station,
  .subway-map svg.dimmed .subway-label,
  .subway-map svg.dimmed .subway-label-bg { opacity: 0.12; }
  .subway-map svg.dimmed .subway-line.hl,
  .subway-map svg.dimmed .subway-station.hl,
  .subway-map svg.dimmed .subway-label.hl,
  .subway-map svg.dimmed .subway-label-bg.hl { opacity: 1; }
  .subway-legend { font-size: 10px; }
  .subway-legend text { fill: var(--text-dim); }
  .subway-tooltip {
    position: absolute; pointer-events: none; background: var(--surface);
    border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px;
    font-size: 12px; line-height: 1.5; box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    z-index: 100; display: none; white-space: nowrap;
  }

  /* Link Table */
  .link-arrow { color: var(--text-dim); margin: 0 4px; }

  /* Packet Feed */
  .feed {
    max-height: 300px;
    overflow-y: auto;
    font-family: 'Cascadia Code', 'Fira Code', monospace;
    font-size: 12px;
  }

  .feed-row {
    display: grid;
    grid-template-columns: 70px 55px 40px 90px 90px 60px 50px;
    padding: 4px 14px;
    border-bottom: 1px solid rgba(46,51,72,0.5);
  }

  .feed-row:hover { background: var(--surface2); }
  .feed-row .dim { color: var(--text-dim); }

  /* Advice Card */
  .advice {
    padding: 18px;
  }

  .advice-item {
    padding: 10px 14px;
    margin-bottom: 8px;
    border-radius: 6px;
    font-size: 13px;
    line-height: 1.5;
  }

  .advice-item.warning { background: rgba(249,115,22,0.1); border-left: 3px solid var(--weak); }
  .advice-item.danger { background: rgba(239,68,68,0.1); border-left: 3px solid var(--very-weak); }
  .advice-item.success { background: rgba(34,197,94,0.1); border-left: 3px solid var(--excellent); }
  .advice-item.info { background: rgba(99,102,241,0.1); border-left: 3px solid var(--accent); }

  /* Responsive grid */
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  @media (max-width: 1200px) { .grid-2 { grid-template-columns: 1fr; } }

  /* No data state */
  .empty {
    padding: 40px;
    text-align: center;
    color: var(--text-dim);
  }

  .empty .spinner {
    width: 32px;
    height: 32px;
    border: 3px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin: 0 auto 16px;
  }

  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>

<div class="header">
  <h1><span class="dot" id="statusDot"></span> Thread Network Monitor</h1>
  <div class="stats-bar" id="statsBar">
    <span>Channel: <span class="val" id="statChannel">--</span></span>
    <span>Devices: <span class="val" id="statDevices">--</span></span>
    <span>Packets: <span class="val" id="statPackets">--</span></span>
    <span>Uptime: <span class="val" id="statUptime">--</span></span>
  </div>
  <div class="controls">
    <select id="channelSelect" title="Channel">
      {% for ch in range(11, 27) %}
      <option value="{{ ch }}" {{ 'selected' if ch == 15 }}>Ch {{ ch }} ({{ 2405 + 5 * (ch - 11) }} MHz)</option>
      {% endfor %}
    </select>
    <button onclick="changeChannel()" title="Change sniffer channel">Apply</button>
    <button onclick="togglePause()" id="pauseBtn">Pause</button>
    <button onclick="openSettings()" title="Panel Settings">&#9881;</button>
    <button onclick="showHelp()" title="Help">?</button>
  </div>
</div>

<!-- Help Modal -->
<div id="helpModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center">
  <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:28px;max-width:600px;width:90%;max-height:80vh;overflow-y:auto">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
      <h2 style="font-size:18px;font-weight:600">Thread Network Monitor — Help</h2>
      <button onclick="document.getElementById('helpModal').style.display='none'" style="background:none;border:none;color:var(--text-dim);font-size:20px;cursor:pointer">&times;</button>
    </div>

    <div style="font-size:13px;line-height:1.7;color:var(--text)">
      <h3 style="font-size:14px;margin:16px 0 8px;color:var(--accent)">What is this?</h3>
      <p>This dashboard monitors your <strong>IKEA Dirigera Thread/Matter</strong> mesh network in real time using an <strong>nRF52840 USB sniffer dongle</strong> connected to this PC. It captures all 802.15.4 radio packets on the network and shows signal strength, link quality, and device relationships.</p>

      <h3 style="font-size:14px;margin:16px 0 8px;color:var(--accent)">Device Table</h3>
      <ul style="margin-left:18px">
        <li><strong>Click column headers</strong> (Address, Name, RSSI, LQI, Packets, Last Seen) to sort.</li>
        <li><strong>Click any device row</strong> to label it with a name, type, and room.</li>
        <li><strong>RSSI</strong> = signal strength in dBm. Higher (closer to 0) is better. Color coded: green (excellent) > yellow (fair) > red (weak).</li>
        <li><strong>LQI</strong> = Link Quality Indicator (0-255). Higher is better.</li>
        <li><strong>Role</strong>: Border Router (the Dirigera hub), Router (repeaters, always-on devices like smart plugs), End Device (battery-powered sensors, remotes).</li>
      </ul>

      <h3 style="font-size:14px;margin:16px 0 8px;color:var(--accent)">Signal Strength Guide</h3>
      <ul style="margin-left:18px">
        <li><span style="color:var(--excellent);font-weight:600">Excellent</span> (-30 to -60 dBm) — strong, reliable connection</li>
        <li><span style="color:var(--good);font-weight:600">Good</span> (-60 to -70 dBm) — solid connection</li>
        <li><span style="color:var(--fair);font-weight:600">Fair</span> (-70 to -80 dBm) — works but could be better</li>
        <li><span style="color:var(--weak);font-weight:600">Weak</span> (-80 to -90 dBm) — unreliable, consider adding a repeater</li>
        <li><span style="color:var(--very-weak);font-weight:600">Very Weak</span> (below -90 dBm) — likely to drop packets</li>
      </ul>

      <h3 style="font-size:14px;margin:16px 0 8px;color:var(--accent)">Identifying Devices</h3>
      <p>Thread devices show as hex addresses (e.g. 0x2B5C). To figure out which is which:</p>
      <ul style="margin-left:18px">
        <li><strong>Dirigera Hub Integration</strong> — Pair with the hub to see all device names. Click "Assign to address" and pick from the list of discovered Thread devices.</li>
        <li><strong>Toggle Mode</strong> — Click "Start Toggle Mode", then turn off a device. The dashboard highlights which address disappeared. Click "Label this" to name it.</li>
        <li><strong>Manual labeling</strong> — Click any device row to assign a name, type, and room. Use "Remove Label" to undo mistakes.</li>
      </ul>

      <h3 style="font-size:14px;margin:16px 0 8px;color:var(--accent)">Channel Selection</h3>
      <p>Your Dirigera network runs on <strong>channel 20</strong>. Use the dropdown to switch channels. 802.15.4 uses channels 11-26 in the 2.4 GHz band.</p>

      <h3 style="font-size:14px;margin:16px 0 8px;color:var(--accent)">Wireshark</h3>
      <p>For deep packet analysis, open Wireshark on this PC. The nRF Sniffer extcap plugin is installed — select "nRF 802154 Sniffer" as the capture interface. The dashboard also saves a <strong>.pcap file</strong> in <code>C:\tools\thread-monitor\</code> that you can open in Wireshark later.</p>

      <h3 style="font-size:14px;margin:16px 0 8px;color:var(--accent)">Technical Details</h3>
      <ul style="margin-left:18px">
        <li><strong>Hardware</strong>: Nordic nRF52840 USB dongle with 802.15.4 sniffer firmware</li>
        <li><strong>Serial port</strong>: COM4</li>
        <li><strong>Dashboard</strong>: Python + Flask, auto-refreshes every 2 seconds</li>
        <li><strong>Data files</strong>: <code>C:\tools\thread-monitor\</code> — labels in <code>device_labels.json</code>, captures in <code>capture_*.pcap</code></li>
        <li><strong>To restart</strong>: <code>cd C:\tools\thread-monitor &amp;&amp; python dashboard.py --port COM4 --channel 20</code></li>
      </ul>
    </div>
  </div>
</div>

<div class="container">
  <!-- Device Overview -->
  <div class="card" data-panel="devices">
    <div class="card-header" onclick="toggleCard(this)">
      <span><svg class="chevron" viewBox="0 0 16 16"><path d="M4 2l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>Discovered Devices</span>
      <span class="badge" id="deviceCount">0</span>
    </div>
    <div class="card-body" id="deviceTable">
      <div class="empty"><div class="spinner"></div>Waiting for packets...</div>
    </div>
  </div>

  <!-- Subway Topology Map -->
  <div class="card" data-panel="topology">
    <div class="card-header" onclick="toggleCard(this)">
      <span><svg class="chevron" viewBox="0 0 16 16"><path d="M4 2l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>Network Topology</span>
      <span class="badge" id="topoNodeCount">0</span>
    </div>
    <div class="card-body subway-map" id="subwayMap">
      <div class="empty"><div class="spinner"></div>Building topology...</div>
    </div>
  </div>

  <div class="grid-2" data-panel="analysis">
    <!-- Signal Advice -->
    <div class="card">
      <div class="card-header" onclick="toggleCard(this)">
        <span><svg class="chevron" viewBox="0 0 16 16"><path d="M4 2l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>Signal Analysis</span>
      </div>
      <div class="card-body advice" id="adviceContent">
        <div class="advice-item info">Collecting data... Signal analysis will appear after devices are discovered.</div>
      </div>
    </div>

    <!-- Link Quality -->
    <div class="card">
      <div class="card-header" onclick="toggleCard(this)">
        <span><svg class="chevron" viewBox="0 0 16 16"><path d="M4 2l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>Device Links</span>
        <span class="badge" id="linkCount">0</span>
      </div>
      <div class="card-body" id="linkTable">
        <div class="empty">No links observed yet</div>
      </div>
    </div>
  </div>

  <!-- Mesh Path Analysis -->
  <div class="card" data-panel="mesh">
    <div class="card-header" onclick="toggleCard(this)">
      <span><svg class="chevron" viewBox="0 0 16 16"><path d="M4 2l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>Mesh Path Analysis</span>
      <div style="display:flex;gap:6px" onclick="event.stopPropagation()">
        <button onclick="refreshMeshAnalysis()" id="meshRefreshBtn" style="font-size:11px;padding:3px 10px;background:var(--surface2);border:1px solid var(--border);color:var(--text);border-radius:4px;cursor:pointer">Refresh</button>
        <button onclick="startRouteCheck()" id="routeCheckBtn" style="font-size:11px;padding:3px 10px;background:var(--accent);border:none;color:white;border-radius:4px;cursor:pointer">Route Check</button>
      </div>
    </div>
    <div class="card-body" id="meshPanel">
      <div class="advice"><div class="advice-item info">Collecting traffic data... Mesh analysis needs a few minutes of data to show routing paths.</div></div>
    </div>
  </div>

  <div class="grid-2" data-panel="hub">
    <!-- Dirigera Hub -->
    <div class="card">
      <div class="card-header" onclick="toggleCard(this)">
        <span><svg class="chevron" viewBox="0 0 16 16"><path d="M4 2l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>Dirigera Hub Integration</span>
      </div>
      <div class="card-body advice" id="dirigeraPanel">
        <div class="advice-item info">Checking hub connection...</div>
      </div>
    </div>

    <!-- Toggle Detection -->
    <div class="card">
      <div class="card-header" onclick="toggleCard(this)">
        <span><svg class="chevron" viewBox="0 0 16 16"><path d="M4 2l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>Device Identification</span>
        <div style="display:flex;gap:6px" onclick="event.stopPropagation()">
          <button onclick="resetToggleIgnored()" id="resetToggleIgnoreBtn" style="font-size:11px;padding:3px 10px;background:var(--surface2);border:1px solid var(--border);color:var(--text-dim);border-radius:4px;cursor:pointer;display:none">Reset ignored</button>
          <button onclick="startToggleMode()" id="toggleBtn" style="font-size:11px;padding:3px 10px;background:var(--surface2);border:1px solid var(--border);color:var(--text);border-radius:4px;cursor:pointer">Start Toggle Mode</button>
        </div>
      </div>
      <div class="card-body" id="togglePanel">
        <div class="advice">
          <div class="advice-item info">Turn off a device, then click "Start Toggle Mode" to see which address disappears. Click the device row to label it.</div>
        </div>
      </div>
    </div>
  </div>

  <!-- Live Packet Feed -->
  <div class="card" data-panel="feed">
    <div class="card-header" onclick="toggleCard(this)">
      <span><svg class="chevron" viewBox="0 0 16 16"><path d="M4 2l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>Live Packet Feed</span>
      <span class="badge" id="feedCount">0</span>
    </div>
    <div class="card-body feed" id="packetFeed">
      <div class="feed-row" style="font-weight:600;color:var(--text-dim)">
        <span>Time</span><span>RSSI</span><span>LQI</span><span>Source</span><span>Dest</span><span>Type</span><span>Size</span>
      </div>
    </div>
  </div>

  <!-- Label Modal -->
  <div id="labelModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:1000;display:none;align-items:center;justify-content:center">
    <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:24px;min-width:320px;max-width:400px">
      <h3 style="margin-bottom:16px;font-size:16px">Label Device <code id="labelAddr"></code></h3>
      <div style="margin-bottom:12px">
        <label style="font-size:12px;color:var(--text-dim)">Name</label>
        <input id="labelName" style="width:100%;padding:8px;margin-top:4px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:14px" placeholder="e.g. Living Room Lamp">
      </div>
      <div style="margin-bottom:12px">
        <label style="font-size:12px;color:var(--text-dim)">Type</label>
        <select id="labelType" style="width:100%;padding:8px;margin-top:4px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:14px">
          <option value="">Unknown</option>
          <option value="light">Light/Bulb</option>
          <option value="outlet">Smart Plug/Outlet</option>
          <option value="repeater">Signal Repeater</option>
          <option value="sensor">Sensor</option>
          <option value="blind">Blind/Curtain</option>
          <option value="remote">Remote/Switch</option>
          <option value="hub">Hub/Border Router</option>
          <option value="other">Other</option>
        </select>
      </div>
      <div style="margin-bottom:16px">
        <label style="font-size:12px;color:var(--text-dim)">Room</label>
        <input id="labelRoom" style="width:100%;padding:8px;margin-top:4px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:14px" placeholder="e.g. Living Room">
      </div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button onclick="removeLabel()" id="removeLabelBtn" style="padding:8px 16px;background:var(--very-weak);border:1px solid var(--very-weak);border-radius:6px;color:white;cursor:pointer;display:none">Remove Label</button>
        <div style="flex:1"></div>
        <button onclick="closeLabelModal()" style="padding:8px 16px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;color:var(--text);cursor:pointer">Cancel</button>
        <button onclick="saveLabel()" style="padding:8px 16px;background:var(--accent);border:1px solid var(--accent);border-radius:6px;color:white;cursor:pointer">Save</button>
      </div>
    </div>
  </div>
</div>

<script>
let paused = false;
let data = null;
let sortColumn = 'rssi';  // default sort
let sortDir = -1;          // -1 = descending (best RSSI first)

function sortDevices(devices, col, dir) {
  return [...devices].sort((a, b) => {
    let va, vb;
    switch(col) {
      case 'address':
        va = (a.short_address || a.address).toLowerCase();
        vb = (b.short_address || b.address).toLowerCase();
        return dir * va.localeCompare(vb);
      case 'name':
        va = (a.label || '').toLowerCase();
        vb = (b.label || '').toLowerCase();
        return dir * va.localeCompare(vb);
      case 'rssi':
        return dir * (a.avg_rssi - b.avg_rssi);
      case 'lqi':
        return dir * (a.avg_lqi - b.avg_lqi);
      case 'packets':
        return dir * (a.frame_count - b.frame_count);
      case 'last_seen':
        va = a.last_seen_ago ?? 9999;
        vb = b.last_seen_ago ?? 9999;
        return dir * (va - vb);
      default:
        return 0;
    }
  });
}

function setSort(col) {
  if (sortColumn === col) {
    sortDir *= -1;  // toggle direction
  } else {
    sortColumn = col;
    sortDir = col === 'address' || col === 'name' ? 1 : -1;
  }
  if (data) renderDevices(data.devices);
}

function showToast(msg, isError) {
  const toast = document.createElement('div');
  toast.textContent = msg;
  toast.style.cssText = 'position:fixed;bottom:24px;right:24px;padding:10px 20px;border-radius:6px;color:white;font-size:13px;z-index:10000;opacity:0;transition:opacity 0.3s;max-width:400px;' +
    (isError ? 'background:var(--very-weak)' : 'background:var(--excellent)');
  document.body.appendChild(toast);
  requestAnimationFrame(() => toast.style.opacity = '1');
  setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 3000);
}

// --- Panel Collapse & Settings ---
const PANELS = [
  { id: 'devices', label: 'Discovered Devices' },
  { id: 'topology', label: 'Network Topology' },
  { id: 'analysis', label: 'Signal Analysis & Links' },
  { id: 'mesh', label: 'Mesh Path Analysis' },
  { id: 'hub', label: 'Dirigera Hub & Identification' },
  { id: 'feed', label: 'Live Packet Feed' },
];

function loadPanelState() {
  try { return JSON.parse(localStorage.getItem('threadmon_panels') || '{}'); } catch(e) { return {}; }
}
function savePanelState(state) {
  localStorage.setItem('threadmon_panels', JSON.stringify(state));
}

function initPanels() {
  const state = loadPanelState();
  PANELS.forEach(p => {
    const el = document.querySelector(`[data-panel="${p.id}"]`);
    if (!el) return;
    if (state[p.id + '_hidden']) el.classList.add('hidden-panel');
    if (state[p.id + '_collapsed']) el.classList.add('collapsed');
    // For grid-2 panels, also collapse inner cards
    if (el.classList.contains('grid-2') && state[p.id + '_collapsed']) {
      el.querySelectorAll('.card').forEach(c => c.classList.add('collapsed'));
    }
  });
}

function toggleCard(headerEl) {
  const card = headerEl.closest('.card');
  if (card) {
    card.classList.toggle('collapsed');
    // Save state
    const panel = card.closest('[data-panel]');
    if (panel) {
      const state = loadPanelState();
      const pid = panel.dataset.panel;
      // For grid-2 panels, check if all inner cards are collapsed
      if (panel.classList.contains('grid-2')) {
        const allCollapsed = [...panel.querySelectorAll('.card')].every(c => c.classList.contains('collapsed'));
        state[pid + '_collapsed'] = allCollapsed;
      } else {
        state[pid + '_collapsed'] = card.classList.contains('collapsed');
      }
      savePanelState(state);
    }
  }
}

function openSettings() {
  const state = loadPanelState();
  let html = '<div class="settings-overlay" id="settingsOverlay" onclick="if(event.target===this)closeSettings()"><div class="settings-box">';
  html += '<h3>Panel Settings</h3>';
  PANELS.forEach(p => {
    const hidden = !!state[p.id + '_hidden'];
    html += `<div class="settings-row">
      <label>${p.label}</label>
      <label class="toggle-switch">
        <input type="checkbox" ${hidden ? '' : 'checked'} onchange="togglePanelVisibility('${p.id}',this.checked)">
        <span class="slider"></span>
      </label>
    </div>`;
  });
  html += '<div style="margin-top:16px;text-align:right"><button onclick="closeSettings()" style="padding:6px 16px;background:var(--accent);color:white;border:none;border-radius:6px;cursor:pointer;font-size:13px">Done</button></div>';
  html += '</div></div>';
  document.body.insertAdjacentHTML('beforeend', html);
}

function closeSettings() {
  const el = document.getElementById('settingsOverlay');
  if (el) el.remove();
}

function togglePanelVisibility(panelId, visible) {
  const el = document.querySelector(`[data-panel="${panelId}"]`);
  if (!el) return;
  if (visible) {
    el.classList.remove('hidden-panel');
  } else {
    el.classList.add('hidden-panel');
  }
  const state = loadPanelState();
  state[panelId + '_hidden'] = !visible;
  savePanelState(state);
}

// Init panels on load
document.addEventListener('DOMContentLoaded', initPanels);

function formatUptime(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

function rssiColor(rssi) {
  if (rssi >= -60) return 'var(--excellent)';
  if (rssi >= -70) return 'var(--good)';
  if (rssi >= -80) return 'var(--fair)';
  if (rssi >= -90) return 'var(--weak)';
  return 'var(--very-weak)';
}

function rssiPercent(rssi) {
  // Map -100..-30 to 0..100
  return Math.max(0, Math.min(100, ((rssi + 100) / 70) * 100));
}

function sortIndicator(col) {
  if (sortColumn !== col) return '';
  return sortDir > 0 ? ' ▲' : ' ▼';
}

function renderDevices(devices) {
  if (!devices.length) return;
  const sorted = sortDevices(devices, sortColumn, sortDir);
  let html = '<table><thead><tr>';
  html += `<th onclick="setSort('address')">Address${sortIndicator('address')}</th>`;
  html += `<th onclick="setSort('name')">Name${sortIndicator('name')}</th>`;
  html += '<th>Manufacturer</th><th>Role</th>';
  html += `<th onclick="setSort('rssi')">RSSI (avg)${sortIndicator('rssi')}</th>`;
  html += '<th>Signal</th>';
  html += `<th onclick="setSort('lqi')">LQI${sortIndicator('lqi')}</th>`;
  html += `<th onclick="setSort('packets')">Packets${sortIndicator('packets')}</th>`;
  html += `<th onclick="setSort('last_seen')">Last Seen${sortIndicator('last_seen')}</th>`;
  html += '</tr></thead><tbody>';

  for (const d of sorted) {
    const pct = rssiPercent(d.avg_rssi);
    const color = rssiColor(d.avg_rssi);
    const addr = d.short_address || d.address;
    const ext = d.extended_address ? `<br><span class="dim" style="font-size:10px">${d.extended_address}</span>` : '';
    const mfr = d.manufacturer || '<span class="dim">—</span>';
    const role = d.role || '—';
    const label = d.label ? `<strong>${d.label}</strong>` : '<span class="dim" style="cursor:pointer" title="Click to label">click to label</span>';
    const labelTypeStr = d.label_type ? d.label_type : '';
    const labelRoomStr = d.label_room ? d.label_room : '';
    const labelExtra = [labelTypeStr, labelRoomStr].filter(Boolean).join(', ');
    const labelInfo = labelExtra ? ` <span class="dim" style="font-size:11px">(${labelExtra})</span>` : '';
    const escapedName = (d.label||'').replace(/'/g, "\\'");
    const escapedType = (d.label_type||'').replace(/'/g, "\\'");
    const escapedRoom = (d.label_room||'').replace(/'/g, "\\'");
    html += `<tr onclick="labelFromDirigera('${addr}')" style="cursor:pointer">
      <td><code>${addr}</code>${ext}</td>
      <td>${label}${labelInfo}</td>
      <td>${mfr}</td>
      <td>${role}</td>
      <td>
        <div class="rssi-bar">
          <span style="color:${color};min-width:50px">${d.avg_rssi} dBm</span>
          <div class="bar"><div class="fill" style="width:${pct}%;background:${color}"></div></div>
        </div>
      </td>
      <td><span class="signal-badge ${d.signal_quality}">${d.signal_quality.replace('_',' ')}</span></td>
      <td>${d.avg_lqi}</td>
      <td>${d.frame_count}</td>
      <td>${d.last_seen_ago != null ? d.last_seen_ago + 's ago' : '-'}</td>
    </tr>`;
  }

  html += '</tbody></table>';
  document.getElementById('deviceTable').innerHTML = html;
  document.getElementById('deviceCount').textContent = devices.length;
}

function renderLinks(links) {
  if (!links.length) {
    document.getElementById('linkTable').innerHTML = '<div class="empty">No links observed yet</div>';
    document.getElementById('linkCount').textContent = '0';
    return;
  }

  let html = '<table><thead><tr><th>Link</th><th>RSSI</th><th>LQI</th><th>Packets</th></tr></thead><tbody>';
  const sorted = [...links].sort((a, b) => a.avg_rssi - b.avg_rssi);

  for (const l of sorted) {
    const color = rssiColor(l.avg_rssi);
    html += `<tr>
      <td><code>${l.src}</code><span class="link-arrow">&rarr;</span><code>${l.dst}</code></td>
      <td style="color:${color}">${l.avg_rssi} dBm</td>
      <td>${l.avg_lqi}</td>
      <td>${l.packet_count}</td>
    </tr>`;
  }

  html += '</tbody></table>';
  document.getElementById('linkTable').innerHTML = html;
  document.getElementById('linkCount').textContent = links.length;
}

function renderAdvice(devices, links) {
  let items = [];

  if (!devices.length) {
    items.push({type: 'info', text: 'Collecting data... Signal analysis will appear after devices are discovered.'});
  } else {
    const weak = devices.filter(d => d.signal_quality === 'weak' || d.signal_quality === 'very_weak');
    const excellent = devices.filter(d => d.signal_quality === 'excellent');
    const good = devices.filter(d => d.signal_quality === 'good');

    if (weak.length > 0) {
      for (const d of weak) {
        items.push({
          type: d.signal_quality === 'very_weak' ? 'danger' : 'warning',
          text: `<strong>${d.short_address || d.address}</strong> has ${d.signal_quality.replace('_',' ')} signal (${d.avg_rssi} dBm). ` +
                `Consider moving it closer to the hub or adding a repeater nearby.`
        });
      }
    }

    if (excellent.length === devices.length) {
      items.push({type: 'success', text: 'All devices have excellent signal strength. Your network topology looks great.'});
    } else if (weak.length === 0) {
      items.push({type: 'success', text: `All ${devices.length} devices have acceptable signal. No immediate changes needed.`});
    }

    // Check for weak links
    const weakLinks = links.filter(l => l.avg_rssi < -80);
    for (const l of weakLinks) {
      items.push({
        type: 'warning',
        text: `Weak link between <strong>${l.src}</strong> and <strong>${l.dst}</strong> (${l.avg_rssi} dBm). A repeater between these devices would improve reliability.`
      });
    }

    // General tips
    if (devices.length >= 2) {
      const rssiRange = Math.max(...devices.map(d => d.avg_rssi)) - Math.min(...devices.map(d => d.avg_rssi));
      if (rssiRange > 30) {
        items.push({
          type: 'info',
          text: `Signal spread across devices is ${rssiRange.toFixed(0)} dB. Large spread may indicate some devices are much farther from the hub than others.`
        });
      }
    }
  }

  document.getElementById('adviceContent').innerHTML = items.map(
    i => `<div class="advice-item ${i.type}">${i.text}</div>`
  ).join('');
}

function renderFeed(packets) {
  const feed = document.getElementById('packetFeed');
  let html = '<div class="feed-row" style="font-weight:600;color:var(--text-dim)">' +
    '<span>Time</span><span>RSSI</span><span>LQI</span><span>Source</span><span>Dest</span><span>Type</span><span>Size</span></div>';

  const recent = packets.slice(-50).reverse();
  for (const p of recent) {
    const t = new Date(p.time * 1000);
    const ts = t.toLocaleTimeString();
    const color = rssiColor(p.rssi);
    html += `<div class="feed-row">
      <span class="dim">${ts}</span>
      <span style="color:${color}">${p.rssi}</span>
      <span>${p.lqi}</span>
      <span><code>${p.src || '-'}</code></span>
      <span><code>${p.dst || '-'}</code></span>
      <span class="dim">${p.type}</span>
      <span class="dim">${p.size}B</span>
    </div>`;
  }

  feed.innerHTML = html;
  document.getElementById('feedCount').textContent = recent.length;
}

async function fetchData() {
  if (paused) return;
  try {
    const resp = await fetch('/api/snapshot');
    data = await resp.json();

    document.getElementById('statChannel').textContent = data.channel;
    document.getElementById('statDevices').textContent = data.device_count;
    document.getElementById('statPackets').textContent = data.total_packets.toLocaleString();
    document.getElementById('statUptime').textContent = formatUptime(data.uptime_seconds);

    const dot = document.getElementById('statusDot');
    if (data.connected) {
      dot.style.background = 'var(--excellent)';
      dot.style.animation = 'pulse 2s ease-in-out infinite';
      dot.title = 'Dongle connected';
    } else {
      dot.style.background = 'var(--weak)';
      dot.style.animation = 'pulse 0.8s ease-in-out infinite';
      dot.title = 'Dongle disconnected \u2014 waiting for reconnect...';
    }

    renderDevices(data.devices);
    renderLinks(data.links);
    renderAdvice(data.devices, data.links);
    renderFeed(data.recent_packets);
    renderSubwayMap(data.devices, data.links);
    updateTogglePanel(data.devices);
  } catch (e) {
    document.getElementById('statusDot').style.background = 'var(--very-weak)';
  }
}

async function changeChannel() {
  const ch = document.getElementById('channelSelect').value;
  await fetch('/api/channel', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({channel: parseInt(ch)}) });
}

function togglePause() {
  paused = !paused;
  document.getElementById('pauseBtn').textContent = paused ? 'Resume' : 'Pause';
  document.getElementById('pauseBtn').classList.toggle('active', paused);
  if (!paused) fetchData();
}

// --- Label Modal ---
let labelTarget = null;

function openLabelModal(addr, existingName, existingType, existingRoom) {
  labelTarget = addr;
  document.getElementById('labelAddr').textContent = addr;
  document.getElementById('labelName').value = existingName || '';
  document.getElementById('labelType').value = existingType || '';
  document.getElementById('labelRoom').value = existingRoom || '';
  document.getElementById('removeLabelBtn').style.display = existingName ? 'block' : 'none';
  document.getElementById('labelModal').style.display = 'flex';
}

async function removeLabel() {
  if (!labelTarget) return;
  await fetch('/api/label', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ address: labelTarget, name: '' })
  });
  closeLabelModal();
  fetchData();
}

function closeLabelModal() {
  document.getElementById('labelModal').style.display = 'none';
  labelTarget = null;
}

async function saveLabel() {
  if (!labelTarget) return;
  await fetch('/api/label', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      address: labelTarget,
      name: document.getElementById('labelName').value,
      type: document.getElementById('labelType').value,
      room: document.getElementById('labelRoom').value,
    })
  });
  closeLabelModal();
  fetchData();
}

// --- Toggle Detection ---
let toggleMode = false;
let toggleBaseline = {};

function startToggleMode() {
  if (!data) return;
  toggleMode = !toggleMode;
  const btn = document.getElementById('toggleBtn');
  if (toggleMode) {
    btn.textContent = 'Stop Toggle Mode';
    btn.style.background = 'var(--accent)';
    btn.style.color = 'white';
    // Snapshot current devices as baseline
    toggleBaseline = {};
    for (const d of data.devices) {
      const addr = d.short_address || d.address;
      toggleBaseline[addr] = { rssi: d.avg_rssi, packets: d.frame_count, lastSeen: d.last_seen_ago };
    }
    document.getElementById('togglePanel').innerHTML = '<div class="advice"><div class="advice-item info">Baseline captured with ' + Object.keys(toggleBaseline).length + ' devices. Now turn OFF or unplug a device and watch for changes below...</div></div>';
  } else {
    btn.textContent = 'Start Toggle Mode';
    btn.style.background = 'var(--surface2)';
    btn.style.color = 'var(--text)';
    toggleBaseline = {};
    document.getElementById('togglePanel').innerHTML = '<div class="advice"><div class="advice-item info">Toggle mode off.</div></div>';
  }
}

const STALE_THRESHOLD = 300; // seconds — hide devices not seen for this long in toggle mode
let toggleIgnored = new Set();  // addresses ignored in toggle results

function resetToggleIgnored() {
  toggleIgnored.clear();
  document.getElementById('resetToggleIgnoreBtn').style.display = 'none';
  if (data) updateTogglePanel(data.devices);
}

function toggleIgnoreDevice(addr) {
  if (toggleIgnored.has(addr)) {
    toggleIgnored.delete(addr);
  } else {
    toggleIgnored.add(addr);
  }
  document.getElementById('resetToggleIgnoreBtn').style.display = toggleIgnored.size > 0 ? 'inline-block' : 'none';
  if (data) updateTogglePanel(data.devices);
}

function updateTogglePanel(devices) {
  if (!toggleMode) return;
  let html = '<div class="advice">';
  let changes = [];

  // Only consider devices that were active (seen within threshold) at baseline time
  for (const [addr, base] of Object.entries(toggleBaseline)) {
    const current = devices.find(d => (d.short_address || d.address) === addr);
    // Skip devices already stale at baseline
    if (base.lastSeen != null && base.lastSeen > STALE_THRESHOLD) continue;

    if (!current || current.last_seen_ago > 15) {
      changes.push({addr, type: 'disappeared', text: `<strong>${current?.label || addr}</strong> — gone silent (last seen ${current ? current.last_seen_ago + 's ago' : 'never'}). This might be the device you turned off!`});
    } else if (current.avg_rssi < base.rssi - 10) {
      changes.push({addr, type: 'weaker', text: `<strong>${current?.label || addr}</strong> — signal dropped significantly (${base.rssi.toFixed(0)} → ${current.avg_rssi.toFixed(0)} dBm)`});
    }
  }

  // Count how many devices were filtered out
  const totalBaseline = Object.keys(toggleBaseline).length;
  const activeBaseline = Object.entries(toggleBaseline).filter(([,b]) => b.lastSeen == null || b.lastSeen <= STALE_THRESHOLD).length;
  const staleCount = totalBaseline - activeBaseline;

  // Separate into visible and ignored
  const visibleChanges = changes.filter(c => !toggleIgnored.has(c.addr));
  const ignoredChanges = changes.filter(c => toggleIgnored.has(c.addr));

  if (visibleChanges.length > 0) {
    for (const c of visibleChanges) {
      const cls = c.type === 'disappeared' ? 'warning' : 'info';
      html += `<div class="advice-item ${cls}" style="display:flex;align-items:center;gap:8px">
        <span style="flex:1">${c.text}</span>
        <button onclick="labelFromDirigera('${c.addr}')" style="padding:2px 8px;font-size:11px;background:var(--accent);color:white;border:none;border-radius:4px;cursor:pointer;white-space:nowrap">Label this</button>
        <button onclick="toggleIgnoreDevice('${c.addr}')" style="padding:2px 8px;font-size:11px;background:var(--surface2);border:1px solid var(--border);border-radius:4px;color:var(--text-dim);cursor:pointer;white-space:nowrap">Not this</button>
      </div>`;
    }
  } else if (changes.length === 0) {
    html += '<div class="advice-item info">No changes detected yet. Turn off a device and wait a few seconds...</div>';
  } else {
    html += '<div class="advice-item info">All detected changes are ignored. Try turning off a different device.</div>';
  }

  if (ignoredChanges.length > 0) {
    html += `<div style="margin-top:8px;padding:4px 14px;font-size:11px;color:var(--text-dim)">${ignoredChanges.length} ignored: `;
    html += ignoredChanges.map(c => `<span style="opacity:0.5;text-decoration:line-through">${c.addr}</span> <button onclick="toggleIgnoreDevice('${c.addr}')" style="font-size:10px;padding:0 4px;background:none;border:none;color:var(--accent);cursor:pointer">undo</button>`).join(', ');
    html += '</div>';
  }
  if (staleCount > 0) {
    html += `<div style="color:var(--text-dim);font-size:11px;padding:4px 14px">${staleCount} stale device(s) hidden (not seen for >${STALE_THRESHOLD}s)</div>`;
  }
  html += '</div>';
  document.getElementById('togglePanel').innerHTML = html;
}

// --- Dirigera ---
async function checkDirigera() {
  try {
    const resp = await fetch('/api/dirigera/status');
    const d = await resp.json();
    const panel = document.getElementById('dirigeraPanel');
    if (d.connected) {
      panel.innerHTML = '<div class="advice-item success">Connected to Dirigera hub at ' + d.hub_ip + '</div>' +
        '<div style="margin-bottom:8px"><button onclick="loadDirigeraDevices()" style="padding:6px 14px;background:var(--accent);color:white;border:none;border-radius:6px;cursor:pointer;font-size:13px">Reload Hub Devices</button></div>' +
        '<div id="dirigeraDevices"></div>';
      // Auto-load devices
      loadDirigeraDevices();
    } else {
      panel.innerHTML = '<div class="advice-item warning">Not paired with Dirigera hub (' + (d.hub_ip||'?') + ')</div>' +
        '<button onclick="startPairing()" style="margin:8px;padding:6px 14px;background:var(--accent);color:white;border:none;border-radius:6px;cursor:pointer;font-size:13px">Start Pairing</button>' +
        '<div id="pairingStatus"></div>';
    }
  } catch(e) {}
}

async function startPairing() {
  const resp = await fetch('/api/dirigera/pair/start', {method:'POST'});
  const d = await resp.json();
  const el = document.getElementById('pairingStatus');
  if (d.ok) {
    el.innerHTML = '<div class="advice-item warning" style="margin-top:8px">' + d.message + '</div>' +
      '<button onclick="completePairing()" style="margin:8px;padding:6px 14px;background:var(--excellent);color:white;border:none;border-radius:6px;cursor:pointer;font-size:13px">Complete Pairing</button>';
  } else {
    el.innerHTML = '<div class="advice-item danger" style="margin-top:8px">Error: ' + d.error + '</div>';
  }
}

async function completePairing() {
  const resp = await fetch('/api/dirigera/pair/complete', {method:'POST'});
  const d = await resp.json();
  if (d.ok) {
    checkDirigera();
  } else {
    document.getElementById('pairingStatus').innerHTML = '<div class="advice-item danger" style="margin-top:8px">Error: ' + d.error + '. Did you press the button?</div>';
  }
}

async function loadDirigeraDevices() {
  const resp = await fetch('/api/dirigera/devices');
  const d = await resp.json();
  const el = document.getElementById('dirigeraDevices');
  if (!d.ok) {
    el.innerHTML = '<div class="advice-item danger">Error: ' + d.error + '</div>';
    return;
  }
  cachedDirigeraDevices = d.devices;  // cache for toggle label flow

  // Get current labels to find already-assigned devices
  const labelsResp = await fetch('/api/labels');
  const labels = await labelsResp.json();
  // Build reverse map: device name → thread address
  const nameToAddr = {};
  for (const [addr, lbl] of Object.entries(labels)) {
    if (lbl.name) nameToAddr[lbl.name] = addr;
  }

  // Count unassigned blinkable devices
  const blinkableTypes = new Set(['light', 'outlet', 'blinds']);
  const assignedNames = new Set(Object.values(labels).map(l => l.name).filter(Boolean));
  const unassignedBlinkable = d.devices.filter(dev => blinkableTypes.has(dev.type) && !assignedNames.has(dev.name) && dev.reachable);

  let identifyAllBtn = '';
  if (unassignedBlinkable.length > 0) {
    identifyAllBtn = `<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
      <button id="identifyAllBtn" onclick="identifyAll()" style="padding:6px 14px;font-size:13px;background:var(--accent);border:none;border-radius:6px;color:white;cursor:pointer;white-space:nowrap">Identify All (${unassignedBlinkable.length} devices)</button>
      <span id="identifyAllStatus" style="font-size:12px;color:var(--text-dim)"></span></div>`;
  }

  let html = identifyAllBtn + '<table><thead><tr><th>Name</th><th>Type</th><th>Room</th><th>Model</th><th>Reachable</th><th>Action</th></tr></thead><tbody>';
  for (const dev of d.devices) {
    const reachable = dev.reachable ? '<span style="color:var(--excellent)">Yes</span>' : '<span style="color:var(--very-weak)">No</span>';
    const assignedAddr = nameToAddr[dev.name];

    let actionHtml;
    if (assignedAddr) {
      actionHtml = `<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap"><span style="font-size:11px;color:var(--excellent)">Assigned to <code>${assignedAddr}</code></span>
        <button onclick="unassignDirigera('${assignedAddr}')" style="padding:2px 8px;font-size:10px;background:var(--very-weak);border:none;border-radius:4px;color:white;cursor:pointer">Unassign</button></div>`;
    } else {
      const canBlink = dev.type === 'light' || dev.type === 'outlet' || dev.type === 'blinds';
      const canPress = dev.type === 'shortcutController' || dev.type === 'remote' || dev.type === 'remoteController'
        || dev.type === 'motionSensor' || dev.type === 'openCloseSensor' || dev.type === 'lightController';
      const escapedId = dev.id.replace(/'/g, "\\'");
      const escapedName2 = (dev.name||'').replace(/'/g, "\\'");
      const escapedType2 = (dev.type||'').replace(/'/g, "\\'");
      const escapedRoom2 = (dev.room||'').replace(/'/g, "\\'");
      let identifyBtn = '';
      if (canBlink) {
        identifyBtn = `<button onclick="event.stopPropagation();blinkIdentify('${escapedId}','${escapedName2}','${escapedType2}','${escapedRoom2}',this)"
            id="blink-${dev.id}" style="padding:3px 10px;font-size:11px;background:var(--accent);border:none;border-radius:4px;color:white;cursor:pointer"
            title="Toggle device on/off to auto-detect its Thread address">Auto-identify</button>`;
      } else if (canPress) {
        identifyBtn = `<button onclick="event.stopPropagation();buttonIdentify('${escapedName2}','${escapedType2}','${escapedRoom2}',this)"
            style="padding:3px 10px;font-size:11px;background:var(--accent);border:none;border-radius:4px;color:white;cursor:pointer"
            title="Press the button to identify its Thread address">Press to identify</button>`;
      }
      const manualBtn = `<button onclick="autoLabel('${(dev.name||'').replace(/'/g,'')}','${dev.type||''}','${(dev.room||'').replace(/'/g,'')}')" style="padding:3px 10px;font-size:11px;background:var(--surface2);border:1px solid var(--border);border-radius:4px;color:var(--text);cursor:pointer">Manual assign</button>`;
      actionHtml = `<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">${identifyBtn}${manualBtn}</div>`;
    }

    html += `<tr style="${assignedAddr ? 'opacity:0.7;' : ''}">
      <td>${dev.name || '—'}</td>
      <td>${dev.type || '—'}</td>
      <td>${dev.room || '—'}</td>
      <td style="font-size:11px">${dev.model || '—'}</td>
      <td>${reachable}</td>
      <td>${actionHtml}</td>
    </tr>`;
  }
  html += '</tbody></table>';
  el.innerHTML = html;
}

async function unassignDirigera(addr) {
  await fetch('/api/label', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ address: addr, name: '' })
  });
  fetchData();
  loadDirigeraDevices();
}

let pickerIgnored = new Set();  // addresses ignored during current assign session
let cachedDirigeraDevices = null;  // cache from last load

async function fetchDirigeraDevices() {
  try {
    const resp = await fetch('/api/dirigera/devices');
    const d = await resp.json();
    if (d.ok) { cachedDirigeraDevices = d.devices; return d.devices; }
  } catch(e) {}
  return null;
}

async function labelFromDirigera(threadAddr) {
  // Show a picker of Dirigera devices to assign to this Thread address
  let devices = cachedDirigeraDevices;
  if (!devices) devices = await fetchDirigeraDevices();
  if (!devices) {
    // Fall back to manual label if not paired
    openLabelModal(threadAddr);
    return;
  }

  const old = document.getElementById('dirigeraPicker');
  if (old) old.remove();

  const picker = document.createElement('div');
  picker.id = 'dirigeraPicker';
  picker.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:1000;display:flex;align-items:center;justify-content:center';

  let html = `<div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:24px;min-width:480px;max-width:600px;max-height:80vh;overflow-y:auto">`;
  html += `<h3 style="margin-bottom:4px;font-size:16px">Which device is <code>${threadAddr}</code>?</h3>`;
  html += `<div style="font-size:12px;color:var(--text-dim);margin-bottom:16px">Select the Dirigera device that matches this Thread address:</div>`;

  for (const dev of devices) {
    const reachable = dev.reachable ? '<span style="color:var(--excellent)">reachable</span>' : '<span style="color:var(--very-weak)">offline</span>';
    const escapedName = (dev.name||'').replace(/'/g,"\\'").replace(/"/g,'&quot;');
    const escapedRoom = (dev.room||'').replace(/'/g,"\\'").replace(/"/g,'&quot;');
    const escapedType = (dev.type||'').replace(/'/g,"\\'").replace(/"/g,'&quot;');

    html += `<div style="padding:10px 14px;margin-bottom:4px;border-radius:6px;border:1px solid var(--border);display:flex;align-items:center;gap:10px;cursor:pointer"
      onclick="assignDirigeraToThread('${threadAddr}','${escapedName}','${escapedType}','${escapedRoom}')"
      onmouseover="this.style.background='var(--surface2)'" onmouseout="this.style.background=''">
      <div style="flex:1">
        <div style="font-weight:600;font-size:13px">${dev.name || '(unnamed)'}</div>
        <div style="font-size:11px;color:var(--text-dim)">${dev.type || '?'} | ${dev.room || 'No room'} | ${reachable}</div>
        <div style="font-size:10px;color:var(--text-dim)">${dev.model || ''}</div>
      </div>
      <button style="padding:4px 12px;font-size:11px;background:var(--accent);color:white;border:none;border-radius:4px;cursor:pointer;white-space:nowrap">Assign</button>
    </div>`;
  }

  html += `<div style="margin-top:12px;display:flex;justify-content:space-between">
    <button onclick="document.getElementById('dirigeraPicker').remove();openLabelModal('${threadAddr}')" style="padding:8px 16px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;color:var(--text);cursor:pointer;font-size:12px">Label manually instead</button>
    <button onclick="document.getElementById('dirigeraPicker').remove()" style="padding:8px 16px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;color:var(--text);cursor:pointer">Cancel</button>
  </div>`;
  html += '</div>';
  picker.innerHTML = html;
  picker.addEventListener('click', (e) => { if (e.target === picker) picker.remove(); });
  document.body.appendChild(picker);
}

function assignDirigeraToThread(threadAddr, name, type, room) {
  document.getElementById('dirigeraPicker')?.remove();
  fetch('/api/label', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ address: threadAddr, name: name, type: type, room: room })
  }).then(() => fetchData());
}

function ignorePickerDevice(addr) {
  if (pickerIgnored.has(addr)) {
    pickerIgnored.delete(addr);
  } else {
    pickerIgnored.add(addr);
  }
  // Re-render the picker row in-place
  const row = document.getElementById('picker-' + addr);
  if (row) {
    const isIgnored = pickerIgnored.has(addr);
    row.style.opacity = isIgnored ? '0.3' : '';
    row.style.textDecoration = isIgnored ? 'line-through' : '';
    const btn = row.querySelector('button:last-child');
    if (btn) {
      btn.textContent = isIgnored ? 'Undo' : 'Not this';
      btn.style.background = isIgnored ? 'var(--accent)' : 'var(--surface2)';
      btn.style.color = isIgnored ? 'white' : 'var(--text-dim)';
    }
  }
}

function autoLabel(name, type, room, btnEl) {
  // Build a dropdown of known sniffer devices next to the button
  if (!data || !data.devices.length) { alert('No devices discovered yet'); return; }

  // Remove any existing picker
  const old = document.getElementById('addrPicker');
  if (old) old.remove();

  const picker = document.createElement('div');
  picker.id = 'addrPicker';
  picker.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:1000;display:flex;align-items:center;justify-content:center';

  // Sort by RSSI descending for the picker; ignored ones go to bottom
  const devs = [...data.devices].sort((a,b) => {
    const aIgn = pickerIgnored.has(a.short_address || a.address) ? 1 : 0;
    const bIgn = pickerIgnored.has(b.short_address || b.address) ? 1 : 0;
    if (aIgn !== bIgn) return aIgn - bIgn;
    return b.avg_rssi - a.avg_rssi;
  });

  let html = `<div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:24px;min-width:500px;max-width:600px;max-height:80vh;overflow-y:auto">`;
  html += `<h3 style="margin-bottom:4px;font-size:16px">Assign "${name}" to a Thread device</h3>`;
  if (room) html += `<div style="font-size:12px;color:var(--text-dim);margin-bottom:8px">Room: ${room} | Type: ${type || '?'}</div>`;
  html += `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px"><span style="font-size:12px;color:var(--text-dim)">Select the device address this corresponds to:</span>`;
  html += `<button onclick="pickerIgnored.clear();autoLabel('${name.replace(/'/g,"\\'")}','${(type||'').replace(/'/g,"\\'")}','${(room||'').replace(/'/g,"\\'")}',this)" style="font-size:11px;padding:2px 8px;background:var(--surface2);border:1px solid var(--border);border-radius:4px;color:var(--text-dim);cursor:pointer">Reset ignored</button></div>`;

  for (const d of devs) {
    const addr = d.short_address || d.address;
    const isIgnored = pickerIgnored.has(addr);
    const existingLabel = d.label ? ` — <strong>${d.label}</strong>` : '';
    const rssiColor_ = d.avg_rssi >= -60 ? 'var(--excellent)' : d.avg_rssi >= -70 ? 'var(--good)' : d.avg_rssi >= -80 ? 'var(--fair)' : d.avg_rssi >= -90 ? 'var(--weak)' : 'var(--very-weak)';
    const staleStyle = (d.last_seen_ago != null && d.last_seen_ago > 300) ? 'opacity:0.4;' : '';
    const ignoredStyle = isIgnored ? 'opacity:0.3;text-decoration:line-through;' : '';
    const role = d.role || '';
    const mfr = d.manufacturer ? ` | ${d.manufacturer}` : '';

    html += `<div id="picker-${addr}" style="padding:8px 14px;margin-bottom:4px;border-radius:6px;border:1px solid var(--border);display:flex;align-items:center;gap:10px;${staleStyle}${ignoredStyle}"
      onmouseover="this.style.background='var(--surface2)'" onmouseout="this.style.background=''">
        <code style="font-size:14px;min-width:60px">${addr}</code>
        <div style="flex:1;font-size:12px">
          <span style="color:${rssiColor_};font-weight:600">${d.avg_rssi} dBm</span>
          <span style="color:var(--text-dim)"> | ${d.signal_quality} | ${role}${mfr}</span>
          <span>${existingLabel}</span>
        </div>
        <span style="font-size:11px;color:var(--text-dim)">${d.frame_count} pkts</span>
        <button onclick="confirmAutoLabel('${addr}',${JSON.stringify(name).replace(/'/g,"\\'")} ,${JSON.stringify(type).replace(/'/g,"\\'")} ,${JSON.stringify(room).replace(/'/g,"\\'")})"
          style="padding:3px 10px;font-size:11px;background:var(--accent);color:white;border:none;border-radius:4px;cursor:pointer;white-space:nowrap">Assign</button>
        <button onclick="event.stopPropagation();ignorePickerDevice('${addr}')" title="${isIgnored ? 'Un-ignore' : 'Not this one'}"
          style="font-size:10px;padding:3px 8px;background:${isIgnored ? 'var(--accent)' : 'var(--surface2)'};border:1px solid var(--border);border-radius:4px;color:${isIgnored ? 'white' : 'var(--text-dim)'};cursor:pointer;white-space:nowrap">${isIgnored ? 'Undo' : 'Not this'}</button>
    </div>`;
  }

  const ignoredCount = pickerIgnored.size;
  if (ignoredCount > 0) {
    html += `<div style="font-size:11px;color:var(--text-dim);padding:8px 0">${ignoredCount} device(s) marked as "not this"</div>`;
  }

  html += `<div style="margin-top:16px;text-align:right"><button onclick="document.getElementById('addrPicker').remove()" style="padding:8px 16px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;color:var(--text);cursor:pointer">Cancel</button></div>`;
  html += '</div>';
  picker.innerHTML = html;

  // Close on backdrop click
  picker.addEventListener('click', (e) => { if (e.target === picker) picker.remove(); });

  document.body.appendChild(picker);
}

function confirmAutoLabel(addr, name, type, room) {
  document.getElementById('addrPicker')?.remove();
  fetch('/api/label', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ address: addr, name: name, type: type, room: room })
  }).then(() => fetchData());
}

async function blinkIdentify(deviceId, name, type, room, btnEl) {
  const origText = btnEl.textContent;
  btnEl.textContent = type === 'blinds' ? 'Moving...' : 'Blinking...';
  btnEl.disabled = true;
  btnEl.style.opacity = '0.6';

  try {
    const resp = await fetch('/api/dirigera/blink-identify', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ device_id: deviceId, device_name: name, device_type: type, device_room: room })
    });
    const d = await resp.json();

    if (d.ok) {
      btnEl.textContent = d.matched_address;
      btnEl.style.background = 'var(--excellent)';
      btnEl.style.opacity = '1';

      const confLabel = {high: 'High confidence', good: 'Good confidence', low: 'Low confidence — multiple candidates'}[d.confidence || 'high'] || 'High confidence';

      if (d.confidence === 'low') {
        // Low confidence — ask user to confirm
        const otherSpikes = d.all_spikes.slice(1).map(s => `${s.address} (+${s.delta})`).join(', ');
        alert(`Low confidence match: "${name}" = ${d.matched_address}\n\n` +
          `Traffic spike: +${d.delta_packets} packets\n` +
          (otherSpikes ? `Other candidates: ${otherSpikes}` : ''));
      } else {
        // High/good confidence — auto-dismiss with toast
        showToast(`${name} → ${d.matched_address} (${confLabel})`);
      }

      fetchData();
      loadDirigeraDevices();
    } else if (d.suggestion) {
      // Last-device fallback — weak spike, ask user to confirm
      btnEl.textContent = d.matched_address + '?';
      btnEl.style.background = 'var(--fair)';
      btnEl.style.opacity = '1';
      const accept = confirm(
        `Weak match: "${d.device_name}" might be ${d.matched_address} (+${d.delta_packets} packets)\n\n` +
        `This is the last unassigned device. Accept this assignment?`);
      if (accept) {
        fetch('/api/label', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({address: d.matched_address, name: d.device_name, type: d.device_type, room: d.device_room})
        }).then(() => { fetchData(); loadDirigeraDevices(); });
        btnEl.textContent = d.matched_address;
        btnEl.style.background = 'var(--excellent)';
        showToast(`${d.device_name} → ${d.matched_address} (manual confirm)`);
      } else {
        btnEl.textContent = origText;
        btnEl.style.background = 'var(--accent)';
        btnEl.disabled = false;
      }
    } else {
      btnEl.textContent = 'Failed';
      btnEl.style.background = 'var(--very-weak)';
      btnEl.style.opacity = '1';
      showToast('Could not identify: ' + d.error, true);
      setTimeout(() => {
        btnEl.textContent = origText;
        btnEl.style.background = 'var(--accent)';
        btnEl.disabled = false;
      }, 2000);
    }
  } catch(e) {
    btnEl.textContent = origText;
    btnEl.style.background = 'var(--accent)';
    btnEl.style.opacity = '1';
    btnEl.disabled = false;
    alert('Error: ' + e.message);
  }
}

// --- Identify All ---
let identifyAllPoller = null;
async function identifyAll() {
  const btn = document.getElementById('identifyAllBtn');
  const status = document.getElementById('identifyAllStatus');
  btn.disabled = true;
  btn.textContent = 'Starting...';
  btn.style.opacity = '0.6';

  try {
    const resp = await fetch('/api/dirigera/identify-all/start', {method:'POST'});
    const d = await resp.json();
    if (!d.ok) { throw new Error(d.error || 'Failed to start'); }
    if (d.total === 0) { status.textContent = d.message; btn.style.display='none'; return; }

    btn.textContent = 'Stop';
    btn.style.background = 'var(--very-weak)';
    btn.style.opacity = '1';
    btn.disabled = false;
    btn.onclick = stopIdentifyAll;

    identifyAllPoller = setInterval(pollIdentifyAll, 1000);
  } catch(e) {
    btn.textContent = 'Identify All';
    btn.style.opacity = '1';
    btn.disabled = false;
    alert('Error: ' + e.message);
  }
}

async function stopIdentifyAll() {
  await fetch('/api/dirigera/identify-all/stop', {method:'POST'});
  if (identifyAllPoller) { clearInterval(identifyAllPoller); identifyAllPoller = null; }
  finishIdentifyAll();
}

async function pollIdentifyAll() {
  try {
    const resp = await fetch('/api/dirigera/identify-all/status');
    const d = await resp.json();
    const status = document.getElementById('identifyAllStatus');
    const btn = document.getElementById('identifyAllBtn');

    const ok = d.results.filter(r => r.status === 'ok').length;
    const fail = d.results.filter(r => r.status !== 'ok').length;
    status.innerHTML = `${d.done}/${d.total} — <span style="color:var(--excellent)">${ok} matched</span>` +
      (fail ? `, <span style="color:var(--weak)">${fail} failed</span>` : '') +
      (d.current ? ` — trying "${d.current}"...` : '');

    if (!d.running && d.done > 0) {
      clearInterval(identifyAllPoller);
      identifyAllPoller = null;
      finishIdentifyAll();
    }
  } catch(e) {}
}

function finishIdentifyAll() {
  const btn = document.getElementById('identifyAllBtn');
  if (btn) {
    btn.textContent = 'Done';
    btn.style.background = 'var(--excellent)';
    btn.disabled = true;
  }
  fetchData();
  loadDirigeraDevices();
}

// --- Button Identification ---
async function buttonIdentify(name, type, room, btnEl) {
  const origText = btnEl.textContent;

  // Step 1: capture baseline
  btnEl.textContent = 'Waiting...';
  btnEl.disabled = true;
  btnEl.style.opacity = '0.6';

  try {
    const startResp = await fetch('/api/button-identify/start', {method: 'POST'});
    const startData = await startResp.json();
    if (!startData.ok) { throw new Error(startData.error); }

    // Step 2: ask user to press the button
    btnEl.textContent = 'Press button NOW!';
    btnEl.style.background = 'var(--weak)';
    btnEl.style.opacity = '1';
    btnEl.style.animation = 'pulse 1s ease-in-out infinite';

    // Wait for user to press (give them 8 seconds)
    await new Promise(r => setTimeout(r, 8000));

    // Step 3: check for spike
    btnEl.textContent = 'Checking...';
    btnEl.style.animation = '';
    btnEl.style.opacity = '0.6';

    const checkResp = await fetch('/api/button-identify/check', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ device_name: name, device_type: type, device_room: room })
    });
    const checkData = await checkResp.json();

    if (checkData.ok) {
      btnEl.textContent = checkData.matched_address;
      btnEl.style.background = 'var(--excellent)';
      btnEl.style.opacity = '1';
      btnEl.disabled = false;

      const otherSpikes = checkData.all_spikes.slice(1).map(s => `${s.address} (+${s.delta})`).join(', ');
      const confLabel2 = {high: 'High confidence', good: 'Good confidence', low: 'Low confidence — multiple candidates'}[checkData.confidence || 'high'] || 'High confidence';

      alert(`Identified: "${name}" = ${checkData.matched_address}\n\n` +
        `Packets sent: +${checkData.delta_packets}\n` +
        `${confLabel2}\n` +
        (otherSpikes ? `Other candidates: ${otherSpikes}` : 'No other candidates — clean match!'));

      fetchData();
      loadDirigeraDevices();
    } else {
      btnEl.textContent = 'Not detected';
      btnEl.style.background = 'var(--very-weak)';
      btnEl.style.opacity = '1';
      alert('Could not identify: ' + checkData.error + '\n\nTip: Press the button multiple times quickly during the detection window.');
      setTimeout(() => {
        btnEl.textContent = origText;
        btnEl.style.background = 'var(--accent)';
        btnEl.disabled = false;
      }, 3000);
    }
  } catch(e) {
    btnEl.textContent = origText;
    btnEl.style.background = 'var(--accent)';
    btnEl.style.opacity = '1';
    btnEl.disabled = false;
    alert('Error: ' + e.message);
  }
}

// --- Subway Topology Map ---
let subwayCache = { addrs: null, positions: null };

function buildSubwayTree(devices, links) {
  // Filter: only devices with enough traffic or a label
  const devMap = {};
  devices.forEach(d => {
    const addr = d.short_address || d.address;
    if (d.frame_count >= 3 || d.label) devMap[addr] = d;
  });

  // Build link weight map
  const linkWeight = {};
  links.forEach(l => {
    const key = l.src + '>' + l.dst;
    linkWeight[key] = (linkWeight[key] || 0) + l.packet_count;
  });

  // Find parent for each device (peer with most traffic, closer to hub)
  const hub = '0x0000';
  const parent = {};
  const children = {};
  Object.keys(devMap).forEach(a => { children[a] = []; });

  // BFS from hub to assign depth
  const depth = { [hub]: 0 };
  const queue = [hub];
  const visited = new Set([hub]);

  // Adjacency from links
  const adj = {};
  links.forEach(l => {
    if (!devMap[l.src] || !devMap[l.dst]) return;
    if (!adj[l.src]) adj[l.src] = [];
    if (!adj[l.dst]) adj[l.dst] = [];
    adj[l.src].push({ peer: l.dst, weight: l.packet_count, rssi: l.avg_rssi });
    adj[l.dst].push({ peer: l.src, weight: l.packet_count, rssi: l.avg_rssi });
  });

  while (queue.length) {
    const cur = queue.shift();
    (adj[cur] || []).forEach(({ peer }) => {
      if (!visited.has(peer)) {
        visited.add(peer);
        depth[peer] = depth[cur] + 1;
        parent[peer] = cur;
        if (children[cur]) children[cur].push(peer);
        queue.push(peer);
      }
    });
  }

  // Devices not reached by BFS — attach to hub
  Object.keys(devMap).forEach(a => {
    if (a !== hub && !parent[a]) {
      parent[a] = hub;
      if (children[hub]) children[hub].push(a);
      depth[a] = 1;
    }
  });

  // Group by room
  const rooms = {};
  Object.entries(devMap).forEach(([addr, d]) => {
    if (addr === hub) return;
    const room = d.label_room || '';
    if (!rooms[room]) rooms[room] = [];
    rooms[room].push(addr);
  });

  // Get link RSSI for drawing
  const linkRssi = {};
  links.forEach(l => {
    const k1 = l.src + '>' + l.dst;
    const k2 = l.dst + '>' + l.src;
    linkRssi[k1] = l.avg_rssi;
    linkRssi[k2] = l.avg_rssi;
  });

  return { devMap, hub, parent, children, depth, rooms, linkRssi };
}

function computeSubwayLayout(tree, width, height) {
  const { devMap, hub, parent, children, rooms } = tree;
  const cx = width / 2, cy = height / 2;
  const pos = {};
  const cell = 65;
  const snap = v => Math.round(v / cell) * cell;

  pos[hub] = { x: cx, y: cy };

  // Sort rooms by size, assign angular sectors
  const roomNames = Object.keys(rooms).sort((a, b) => rooms[b].length - rooms[a].length);
  if (roomNames.length === 0) return pos;

  const sectorSize = (2 * Math.PI) / Math.max(roomNames.length, 1);
  const innerR = Math.min(width, height) * 0.25;
  const outerR = Math.min(width, height) * 0.42;

  const occupied = new Set();
  occupied.add(snap(cx) + ',' + snap(cy));

  function findFreeSpot(idealX, idealY) {
    let sx = snap(idealX), sy = snap(idealY);
    const key = sx + ',' + sy;
    if (!occupied.has(key)) { occupied.add(key); return { x: sx, y: sy }; }
    // Spiral outward to find free cell
    for (let r = 1; r <= 4; r++) {
      for (let dx = -r; dx <= r; dx++) {
        for (let dy = -r; dy <= r; dy++) {
          if (Math.abs(dx) !== r && Math.abs(dy) !== r) continue;
          const nx = sx + dx * cell, ny = sy + dy * cell;
          const nk = nx + ',' + ny;
          if (!occupied.has(nk)) { occupied.add(nk); return { x: nx, y: ny }; }
        }
      }
    }
    return { x: sx + cell, y: sy };
  }

  roomNames.forEach((roomName, ri) => {
    const angle0 = ri * sectorSize - Math.PI / 2;
    const addrs = rooms[roomName];

    // Separate routers and end devices
    const routers = addrs.filter(a => {
      const d = devMap[a];
      return d && (d.role === 'Router' || d.role === 'Router (likely)' || d.role === 'Router/End Device');
    });
    const ends = addrs.filter(a => !routers.includes(a));

    // Place routers on inner ring
    routers.forEach((addr, i) => {
      const a = angle0 + (i + 0.5) * sectorSize / Math.max(routers.length, 1);
      pos[addr] = findFreeSpot(cx + Math.cos(a) * innerR, cy + Math.sin(a) * innerR);
    });

    // Place end devices on outer ring, near their parent
    ends.forEach((addr, i) => {
      const p = parent[addr];
      const pPos = pos[p] || { x: cx, y: cy };
      const a = angle0 + (i + 0.5) * sectorSize / Math.max(ends.length, 1);
      const dx = Math.cos(a) * outerR;
      const dy = Math.sin(a) * outerR;
      pos[addr] = findFreeSpot(cx + dx, cy + dy);
    });
  });

  return pos;
}

function subwayPath(x1, y1, x2, y2) {
  const R = 12;
  const dx = x2 - x1, dy = y2 - y1;
  if (Math.abs(dx) < 2) return `M${x1},${y1}V${y2}`;
  if (Math.abs(dy) < 2) return `M${x1},${y1}H${x2}`;
  // L-shape with rounded corner
  const sx = dx > 0 ? 1 : -1, sy = dy > 0 ? 1 : -1;
  const mx = x2 - sx * R;
  const my = y1 + sy * R;
  return `M${x1},${y1}H${mx}Q${x2},${y1},${x2},${my}V${y2}`;
}

function signalColor(quality) {
  const m = { excellent: 'var(--excellent)', good: 'var(--good)', fair: 'var(--fair)', weak: 'var(--weak)', very_weak: 'var(--very-weak)' };
  return m[quality] || 'var(--text-dim)';
}

function rssiToQuality(rssi) {
  if (rssi >= -60) return 'excellent';
  if (rssi >= -70) return 'good';
  if (rssi >= -80) return 'fair';
  if (rssi >= -90) return 'weak';
  return 'very_weak';
}

function renderSubwayMap(devices, links) {
  const container = document.getElementById('subwayMap');
  if (!container || !devices.length) return;

  document.getElementById('topoNodeCount').textContent = devices.filter(d => d.frame_count >= 3 || d.label).length;

  const tree = buildSubwayTree(devices, links);
  const { devMap, hub, parent, linkRssi, rooms } = tree;

  // Check if we need a full relayout
  const currentAddrs = Object.keys(devMap).sort().join(',');
  let positions;
  if (subwayCache.addrs === currentAddrs && subwayCache.positions) {
    positions = subwayCache.positions;
  } else {
    const W = 900, H = 600;
    positions = computeSubwayLayout(tree, W, H);
    subwayCache = { addrs: currentAddrs, positions };
  }

  // Compute SVG viewBox from positions
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  Object.values(positions).forEach(p => {
    minX = Math.min(minX, p.x); minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x); maxY = Math.max(maxY, p.y);
  });
  const pad = 80;
  minX -= pad; minY -= pad; maxX += pad; maxY += pad;
  const vw = maxX - minX, vh = maxY - minY;

  let svg = `<svg viewBox="${minX} ${minY} ${vw} ${vh}" style="min-height:350px;max-height:550px">`;

  // Layer 1: Room backgrounds
  const roomColors = ['rgba(79,70,229,0.06)', 'rgba(22,163,74,0.06)', 'rgba(202,138,4,0.06)', 'rgba(234,88,12,0.06)', 'rgba(220,38,38,0.06)'];
  const roomBorders = ['rgba(79,70,229,0.25)', 'rgba(22,163,74,0.25)', 'rgba(202,138,4,0.25)', 'rgba(234,88,12,0.25)', 'rgba(220,38,38,0.25)'];
  let ri2 = 0;
  Object.entries(rooms).forEach(([roomName, addrs]) => {
    if (!roomName) return;
    let rx1 = Infinity, ry1 = Infinity, rx2 = -Infinity, ry2 = -Infinity;
    addrs.forEach(a => {
      const p = positions[a];
      if (!p) return;
      rx1 = Math.min(rx1, p.x); ry1 = Math.min(ry1, p.y);
      rx2 = Math.max(rx2, p.x); ry2 = Math.max(ry2, p.y);
    });
    if (rx1 === Infinity) return;
    const rpad = 35;
    const ci = ri2 % roomColors.length;
    svg += `<rect class="subway-room-bg" x="${rx1-rpad}" y="${ry1-rpad-14}" width="${rx2-rx1+rpad*2}" height="${ry2-ry1+rpad*2+14}" fill="${roomColors[ci]}" stroke="${roomBorders[ci]}" stroke-width="1.5" stroke-dasharray="6,4"/>`;
    svg += `<text class="subway-room-label" x="${rx1-rpad+8}" y="${ry1-rpad-2}">${roomName}</text>`;
    ri2++;
  });

  // Layer 2: Lines (parent links)
  Object.entries(parent).forEach(([addr, par]) => {
    const p1 = positions[par], p2 = positions[addr];
    if (!p1 || !p2) return;
    const d = devMap[addr];
    const isRouter = d && (d.role === 'Router' || d.role === 'Router (likely)' || d.role === 'Router/End Device');
    const sw = isRouter ? 7 : 4;
    const lk = par + '>' + addr;
    const rssi = linkRssi[lk] || linkRssi[addr + '>' + par] || (d ? d.avg_rssi : -80);
    const color = signalColor(rssiToQuality(rssi));
    const path = subwayPath(p1.x, p1.y, p2.x, p2.y);
    svg += `<path class="subway-line" data-src="${par}" data-dst="${addr}" d="${path}" stroke="${color}" stroke-width="${sw}" opacity="0.8"/>`;
  });

  // Layer 3: Stations
  Object.entries(devMap).forEach(([addr, d]) => {
    const p = positions[addr];
    if (!p) return;
    const isHub = addr === hub;
    const isRouter = d.role === 'Router' || d.role === 'Router (likely)' || d.role === 'Router/End Device' || d.role === 'Border Router';
    const color = signalColor(d.signal_quality);
    const r = isHub ? 14 : isRouter ? 10 : 6;
    const fill = isHub ? 'var(--accent)' : isRouter ? 'var(--surface)' : color;
    const stroke = isHub ? 'var(--surface)' : isRouter ? color : 'var(--surface)';
    const strokeW = isHub ? 4 : isRouter ? 3.5 : 1.5;

    if (isHub) {
      svg += `<circle cx="${p.x}" cy="${p.y}" r="${r+5}" fill="none" stroke="var(--accent)" stroke-width="2" opacity="0.3"><animate attributeName="r" values="${r+5};${r+10};${r+5}" dur="3s" repeatCount="indefinite"/><animate attributeName="opacity" values="0.3;0.08;0.3" dur="3s" repeatCount="indefinite"/></circle>`;
    }
    svg += `<circle class="subway-station" data-addr="${addr}" cx="${p.x}" cy="${p.y}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeW}"/>`;
  });

  // Layer 4: Labels with white background pills (like London Tube map)
  // First pass: collect label positions and dimensions, then render bg + text
  const labelData = [];
  Object.entries(devMap).forEach(([addr, d]) => {
    const p = positions[addr];
    if (!p) return;
    const name = d.label || (addr === hub ? 'Hub' : '');
    if (!name) return;

    // Choose label direction to avoid center (push labels outward)
    const dx = p.x - (minX + vw / 2);
    const dy = p.y - (minY + vh / 2);
    // Prefer horizontal offset; use vertical if node is near horizontal center
    let lx, ly, anchor;
    const isHub2 = addr === hub;
    const offset = isHub2 ? 22 : 18;
    if (Math.abs(dx) > Math.abs(dy) * 0.5) {
      // Place left or right
      const right = dx >= 0;
      lx = right ? p.x + offset : p.x - offset;
      ly = p.y + 4;
      anchor = right ? 'start' : 'end';
    } else {
      // Place above or below
      const below = dy >= 0;
      lx = p.x;
      ly = below ? p.y + offset + 4 : p.y - offset + 4;
      anchor = 'middle';
    }

    // Estimate text width (~6.5px per character at 11px font)
    const tw = name.length * 6.5;
    const th = 14;
    const pad = 4;
    let bgX;
    if (anchor === 'start') bgX = lx - pad;
    else if (anchor === 'end') bgX = lx - tw - pad;
    else bgX = lx - tw / 2 - pad;
    const bgY = ly - th + 1;

    labelData.push({ addr, name, lx, ly, anchor, bgX, bgY, tw: tw + pad * 2, th: th + pad });
  });

  // Render background rects first, then text on top
  labelData.forEach(l => {
    svg += `<rect class="subway-label-bg" data-addr="${l.addr}" x="${l.bgX}" y="${l.bgY}" width="${l.tw}" height="${l.th}"/>`;
  });
  labelData.forEach(l => {
    svg += `<text class="subway-label" data-addr="${l.addr}" x="${l.lx}" y="${l.ly}" text-anchor="${l.anchor}">${l.name}</text>`;
  });

  // Layer 5: Legend
  const lx = maxX - 20, ly = minY + 20;
  const legendItems = [
    ['Excellent', 'var(--excellent)'], ['Good', 'var(--good)'], ['Fair', 'var(--fair)'],
    ['Weak', 'var(--weak)'], ['Very Weak', 'var(--very-weak)']
  ];
  svg += `<g class="subway-legend" transform="translate(${lx},${ly})">`;
  legendItems.forEach(([label, color], i) => {
    svg += `<line x1="-50" y1="${i*16}" x2="-30" y2="${i*16}" stroke="${color}" stroke-width="4" stroke-linecap="round"/>`;
    svg += `<text x="-24" y="${i*16+3.5}" text-anchor="start" font-size="9">${label}</text>`;
  });
  svg += `</g>`;

  svg += `</svg><div class="subway-tooltip" id="subwayTooltip"></div>`;
  container.innerHTML = svg;

  // Interaction
  const svgEl = container.querySelector('svg');
  const tooltip = document.getElementById('subwayTooltip');

  svgEl.addEventListener('mouseover', e => {
    const station = e.target.closest('.subway-station');
    if (!station) return;
    const addr = station.dataset.addr;
    svgEl.classList.add('dimmed');
    // Highlight this station and connected lines/labels
    station.classList.add('hl');
    svgEl.querySelectorAll(`.subway-label[data-addr="${addr}"],.subway-label-bg[data-addr="${addr}"]`).forEach(el => el.classList.add('hl'));
    svgEl.querySelectorAll(`.subway-line[data-src="${addr}"],.subway-line[data-dst="${addr}"]`).forEach(el => {
      el.classList.add('hl');
      const other = el.dataset.src === addr ? el.dataset.dst : el.dataset.src;
      svgEl.querySelectorAll(`.subway-station[data-addr="${other}"],.subway-label[data-addr="${other}"],.subway-label-bg[data-addr="${other}"]`).forEach(o => o.classList.add('hl'));
    });
    // Tooltip
    const d = devMap[addr];
    if (d) {
      tooltip.innerHTML = `<strong>${d.label || addr}</strong><br>` +
        `<span style="color:var(--text-dim)">${addr} &middot; ${d.role}</span><br>` +
        `RSSI: <strong style="color:${signalColor(d.signal_quality)}">${d.avg_rssi} dBm</strong>` +
        (d.label_room ? `<br>Room: ${d.label_room}` : '');
      tooltip.style.display = 'block';
    }
  });

  svgEl.addEventListener('mousemove', e => {
    if (tooltip.style.display === 'block') {
      const rect = container.getBoundingClientRect();
      tooltip.style.left = (e.clientX - rect.left + 14) + 'px';
      tooltip.style.top = (e.clientY - rect.top - 10) + 'px';
    }
  });

  svgEl.addEventListener('mouseout', e => {
    const station = e.target.closest('.subway-station');
    if (!station) return;
    svgEl.classList.remove('dimmed');
    svgEl.querySelectorAll('.hl').forEach(el => el.classList.remove('hl'));
    tooltip.style.display = 'none';
  });
}

// --- Mesh Path Analysis ---
let meshData = null;
let routeCheckBaseline = null;

async function refreshMeshAnalysis() {
  const btn = document.getElementById('meshRefreshBtn');
  btn.textContent = 'Loading...';
  try {
    const resp = await fetch('/api/mesh-analysis');
    meshData = await resp.json();
    renderMeshPanel();
  } catch(e) {}
  btn.textContent = 'Refresh';
}

function renderMeshPanel() {
  const panel = document.getElementById('meshPanel');
  if (!meshData || !meshData.ok || !meshData.devices.length) {
    panel.innerHTML = '<div class="advice"><div class="advice-item info">No routing data available yet. Let the sniffer collect traffic for a few minutes, then click Refresh.</div></div>';
    return;
  }

  let html = '<table><thead><tr>';
  html += '<th>Device</th><th>Direct to Hub</th><th>Best Relay Path</th><th>Status</th><th>Recommendation</th>';
  html += '</tr></thead><tbody>';

  for (const d of meshData.devices) {
    const name = d.name || d.address;
    const directStr = d.direct_rssi != null
      ? `<span style="color:${rssiColor(d.direct_rssi)};font-weight:600">${d.direct_rssi} dBm</span> <span class="dim">(${d.direct_packets} pkts)</span>`
      : '<span class="dim">No direct link</span>';

    let relayStr = '<span class="dim">None found</span>';
    if (d.best_relay) {
      const r = d.best_relay;
      relayStr = `<span style="color:${rssiColor(r.worst_rssi)};font-weight:600">${r.worst_rssi} dBm</span> via <strong>${r.router_name}</strong><br>`;
      relayStr += `<span class="dim" style="font-size:10px">${d.address}→${r.router}: ${r.leg1_rssi} dBm | ${r.router}→hub: ${r.leg2_rssi} dBm</span>`;
    }

    let statusBadge, statusColor;
    switch(d.status) {
      case 'suboptimal':
        statusBadge = 'Suboptimal'; statusColor = 'var(--weak)'; break;
      case 'weak_direct':
        statusBadge = 'Weak'; statusColor = 'var(--very-weak)'; break;
      case 'weak_no_relay':
        statusBadge = 'Weak (no relay)'; statusColor = 'var(--very-weak)'; break;
      case 'relay_only':
        statusBadge = 'Relay only'; statusColor = 'var(--fair)'; break;
      default:
        statusBadge = 'OK'; statusColor = 'var(--excellent)'; break;
    }

    const suggestion = d.suggestion
      ? `<span style="font-size:11px">${d.suggestion}</span>`
      : '<span class="dim" style="font-size:11px">No action needed</span>';

    html += `<tr>
      <td><strong>${name}</strong><br><code style="font-size:10px">${d.address}</code></td>
      <td>${directStr}</td>
      <td>${relayStr}</td>
      <td><span style="color:${statusColor};font-weight:600;font-size:12px">${statusBadge}</span></td>
      <td>${suggestion}</td>
    </tr>`;
  }

  html += '</tbody></table>';
  panel.innerHTML = html;
}

// Route Check: snapshot routes, user power-cycles a device, then compare
async function startRouteCheck() {
  const btn = document.getElementById('routeCheckBtn');
  if (routeCheckBaseline) {
    // Second click: compare
    btn.textContent = 'Checking...';
    btn.disabled = true;
    await refreshMeshAnalysis();

    const resp = await fetch('/api/mesh-analysis');
    const after = await resp.json();

    let changes = [];
    if (routeCheckBaseline.devices && after.ok) {
      for (const afterDev of after.devices) {
        const beforeDev = routeCheckBaseline.devices.find(d => d.address === afterDev.address);
        if (!beforeDev) continue;

        const beforeDirect = beforeDev.direct_rssi;
        const afterDirect = afterDev.direct_rssi;
        const beforeRelay = beforeDev.best_relay;
        const afterRelay = afterDev.best_relay;

        // Check if routing changed
        if (beforeDirect && !afterDirect && afterRelay) {
          changes.push({addr: afterDev.address, name: afterDev.name, type: 'switched_to_relay',
            text: `<strong>${afterDev.name || afterDev.address}</strong> switched from direct (${beforeDirect} dBm) to relay via ${afterRelay.router_name}`});
        } else if (!beforeDirect && afterDirect) {
          changes.push({addr: afterDev.address, name: afterDev.name, type: 'switched_to_direct',
            text: `<strong>${afterDev.name || afterDev.address}</strong> switched from relay to direct (${afterDirect} dBm)`});
        } else if (beforeDirect && afterDirect && Math.abs(beforeDirect - afterDirect) > 5) {
          changes.push({addr: afterDev.address, name: afterDev.name, type: 'rssi_change',
            text: `<strong>${afterDev.name || afterDev.address}</strong> signal changed: ${beforeDirect} → ${afterDirect} dBm`});
        } else if (beforeRelay && afterRelay && beforeRelay.router !== afterRelay.router) {
          changes.push({addr: afterDev.address, name: afterDev.name, type: 'relay_change',
            text: `<strong>${afterDev.name || afterDev.address}</strong> changed relay: ${beforeRelay.router_name} → ${afterRelay.router_name}`});
        }
      }
    }

    // Show results
    let html = '<div class="advice" style="margin-top:8px">';
    if (changes.length > 0) {
      html += '<div class="advice-item success" style="margin-bottom:4px"><strong>Route changes detected:</strong></div>';
      for (const c of changes) {
        html += `<div class="advice-item info">${c.text}</div>`;
      }
    } else {
      html += '<div class="advice-item warning">No route changes detected. The device may need more time, or Thread chose the same path again.</div>';
    }
    html += '</div>';

    const panel = document.getElementById('meshPanel');
    panel.innerHTML += html;

    routeCheckBaseline = null;
    btn.textContent = 'Route Check';
    btn.disabled = false;
    btn.style.background = 'var(--accent)';
  } else {
    // First click: take baseline
    const resp = await fetch('/api/mesh-analysis');
    routeCheckBaseline = await resp.json();
    btn.textContent = 'Power-cycle device, then click here';
    btn.style.background = 'var(--weak)';
    document.getElementById('meshPanel').innerHTML += '<div class="advice"><div class="advice-item warning" style="margin-top:8px">Baseline captured. Now power-cycle the device you want to check, wait for it to rejoin (~30s), then click the button again.</div></div>';
  }
}

// Auto-refresh mesh every 30 seconds
setInterval(() => { if (!routeCheckBaseline) refreshMeshAnalysis(); }, 30000);
// Initial load after 10s of data collection
setTimeout(refreshMeshAnalysis, 10000);

function showHelp() {
  document.getElementById('helpModal').style.display = 'flex';
}
document.getElementById('helpModal')?.addEventListener('click', (e) => {
  if (e.target.id === 'helpModal') e.target.style.display = 'none';
});

// Init
checkDirigera();

// Poll every 2 seconds
setInterval(fetchData, 2000);
fetchData();
</script>
</body>
</html>
"""


LABELS_FILE = "device_labels.json"
dirigera = None  # DigeraClient instance
_pairing_state = {}  # temp state for OAuth flow


def load_labels():
    if os.path.exists(LABELS_FILE):
        with open(LABELS_FILE) as f:
            return json.load(f)
    return {}


def save_labels(labels):
    with open(LABELS_FILE, "w") as f:
        json.dump(labels, f, indent=2)


@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/snapshot")
def api_snapshot():
    snap = sniffer.get_snapshot()
    # Merge labels into device data
    labels = load_labels()
    for dev in snap["devices"]:
        addr = dev["short_address"] or dev["address"]
        if addr in labels:
            lbl = labels[addr]
            dev["label"] = lbl.get("name", "")
            dev["label_type"] = lbl.get("type", "")
            dev["label_room"] = lbl.get("room", "")
            if lbl.get("manufacturer") and not dev.get("manufacturer"):
                dev["manufacturer"] = lbl["manufacturer"]
    return jsonify(snap)


@app.route("/api/channel", methods=["POST"])
def api_channel():
    data = request.get_json()
    ch = data.get("channel", 15)
    if 11 <= ch <= 26:
        sniffer.set_channel(ch)
        return jsonify({"ok": True, "channel": ch})
    return jsonify({"ok": False, "error": "Channel must be 11-26"}), 400


@app.route("/api/label", methods=["POST"])
def api_label():
    """Set a label for a device address."""
    data = request.get_json()
    addr = data.get("address", "")
    name = data.get("name", "")
    dev_type = data.get("type", "")
    room = data.get("room", "")
    labels = load_labels()
    if name:
        labels[addr] = {"name": name, "type": dev_type, "room": room}
    elif addr in labels:
        del labels[addr]
    save_labels(labels)
    return jsonify({"ok": True})


@app.route("/api/labels")
def api_labels():
    return jsonify(load_labels())


@app.route("/api/dirigera/status")
def api_dirigera_status():
    if not dirigera:
        return jsonify({"connected": False, "reason": "no_hub_ip"})
    return jsonify({
        "connected": dirigera.is_authenticated(),
        "hub_ip": dirigera.ip,
    })


@app.route("/api/dirigera/pair/start", methods=["POST"])
def api_dirigera_pair_start():
    if not dirigera:
        return jsonify({"ok": False, "error": "Hub IP not configured"}), 400
    try:
        code, verifier = dirigera.start_pairing()
        _pairing_state["code"] = code
        _pairing_state["verifier"] = verifier
        return jsonify({"ok": True, "message": "Press the button on the bottom of the Dirigera hub within 60 seconds, then click 'Complete Pairing'"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/dirigera/pair/complete", methods=["POST"])
def api_dirigera_pair_complete():
    if not dirigera or "code" not in _pairing_state:
        return jsonify({"ok": False, "error": "No pairing in progress"}), 400
    try:
        token = dirigera.complete_pairing(_pairing_state["code"], _pairing_state["verifier"])
        _pairing_state.clear()
        return jsonify({"ok": True, "message": "Paired successfully!"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/dirigera/devices")
def api_dirigera_devices():
    if not dirigera or not dirigera.is_authenticated():
        return jsonify({"ok": False, "error": "Not paired with hub"}), 401
    try:
        devices = dirigera.get_device_summary()
        return jsonify({"ok": True, "devices": devices})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/mesh-analysis")
def api_mesh_analysis():
    """Analyze mesh routing paths for all devices."""
    snap = sniffer.get_snapshot()
    labels = load_labels()

    # Build link map: (src, dst) -> {rssi, packets}
    link_map = {}
    for l in snap["links"]:
        link_map[(l["src"], l["dst"])] = {"rssi": l["avg_rssi"], "packets": l["packet_count"], "lqi": l["avg_lqi"]}

    # Find all routers (devices that relay traffic — have links both to hub and to other devices)
    hub = "0x0000"
    routers = set()
    for l in snap["links"]:
        if l["src"] != hub and l["dst"] != hub:
            # This device talks to something other than the hub — might be routing
            routers.add(l["src"])
            routers.add(l["dst"])
    # Also add labeled repeaters
    for addr, lbl in labels.items():
        if lbl.get("type") == "repeater":
            routers.add(addr)

    devices_analysis = []
    for dev in snap["devices"]:
        addr = dev["short_address"] or dev["address"]
        if addr == hub:
            continue

        lbl = labels.get(addr, {})
        name = lbl.get("name", "") or dev.get("label", "")

        # Direct link to hub
        direct_to_hub = link_map.get((addr, hub))
        direct_from_hub = link_map.get((hub, addr))

        # Find best relay path: device -> router -> hub
        best_relay = None
        for router in routers:
            if router == addr or router == hub:
                continue
            # Check if this device talks to the router
            dev_to_router = link_map.get((addr, router))
            router_to_hub = link_map.get((router, hub))
            # Or router talks to device
            router_to_dev = link_map.get((router, addr))
            hub_to_router = link_map.get((hub, router))

            leg1 = dev_to_router or router_to_dev
            leg2 = router_to_hub or hub_to_router

            if leg1 and leg2:
                # Relay path quality = worst of the two legs
                worst_rssi = min(leg1["rssi"], leg2["rssi"])
                router_lbl = labels.get(router, {})
                router_label = router_lbl.get("name", "") or router
                router_type = router_lbl.get("type", "")
                if router_type:
                    router_label = f"{router_label} ({router_type})"
                relay = {
                    "router": router,
                    "router_name": router_label,
                    "leg1_rssi": leg1["rssi"],
                    "leg2_rssi": leg2["rssi"],
                    "worst_rssi": worst_rssi,
                    "leg1_packets": leg1["packets"],
                    "leg2_packets": leg2["packets"],
                }
                if not best_relay or worst_rssi > best_relay["worst_rssi"]:
                    best_relay = relay

        # Determine routing status
        direct_rssi = direct_to_hub["rssi"] if direct_to_hub else None
        relay_rssi = best_relay["worst_rssi"] if best_relay else None

        if direct_rssi is not None and relay_rssi is not None:
            if relay_rssi > direct_rssi + 5:
                status = "suboptimal"
                suggestion = f"Could improve by routing through {best_relay['router_name']} ({relay_rssi:.0f} dBm vs {direct_rssi:.0f} dBm direct)"
            elif direct_rssi < -80:
                status = "weak_direct"
                suggestion = f"Weak direct link ({direct_rssi:.0f} dBm). Relay via {best_relay['router_name']} would give {relay_rssi:.0f} dBm"
            else:
                status = "ok"
                suggestion = ""
        elif direct_rssi is not None and direct_rssi < -80:
            status = "weak_no_relay"
            suggestion = "Weak signal and no relay path found. Consider adding a repeater."
        elif direct_rssi is None and relay_rssi is not None:
            status = "relay_only"
            suggestion = f"No direct hub link observed. Routing through {best_relay['router_name']}"
        else:
            status = "ok"
            suggestion = ""

        dev_type = lbl.get("type", "")
        display_name = f"{name} ({dev_type})" if name and dev_type else name

        devices_analysis.append({
            "address": addr,
            "name": display_name,
            "direct_rssi": direct_rssi,
            "direct_packets": direct_to_hub["packets"] if direct_to_hub else 0,
            "best_relay": best_relay,
            "status": status,
            "suggestion": suggestion,
            "signal_quality": dev["signal_quality"],
        })

    # Sort: problems first
    status_order = {"suboptimal": 0, "weak_direct": 0, "weak_no_relay": 1, "relay_only": 2, "ok": 3}
    devices_analysis.sort(key=lambda x: (status_order.get(x["status"], 3), x["direct_rssi"] or -100))

    return jsonify({
        "ok": True,
        "devices": devices_analysis,
        "routers": list(routers),
    })


@app.route("/api/button-identify/start", methods=["POST"])
def api_button_identify_start():
    """Start button identification — take a baseline of sender counts."""
    baseline = sniffer.snapshot_send_counts()
    # Store in a simple global
    app.config["_button_baseline"] = baseline
    return jsonify({"ok": True, "message": "Baseline captured. Press the button now."})


@app.route("/api/button-identify/check", methods=["POST"])
def api_button_identify_check():
    """Check which device sent new packets since baseline."""
    data = request.get_json()
    device_name = data.get("device_name", "")
    device_type = data.get("device_type", "")
    device_room = data.get("device_room", "")

    baseline = app.config.get("_button_baseline")
    if not baseline:
        return jsonify({"ok": False, "error": "No baseline. Click 'Identify' first."}), 400

    all_spikes = sniffer.detect_sender_spike(baseline, min_delta=2)

    # Filter out hub and already-labeled devices
    labels = load_labels()
    labeled_addrs = {addr for addr, lbl in labels.items() if lbl.get("name")}
    filtered = [(a, d) for a, d in all_spikes if a != "0x0000" and a not in labeled_addrs]

    if filtered:
        best_addr, best_delta = filtered[0]

        # Confidence
        if len(filtered) == 1:
            confidence = "high"
        elif best_delta >= filtered[1][1] * 1.5:
            confidence = "high"
        elif best_delta >= filtered[1][1] * 1.2:
            confidence = "good"
        else:
            confidence = "low"

        # Auto-assign if name provided
        if device_name:
            labels[best_addr] = {
                "name": device_name,
                "type": device_type,
                "room": device_room,
            }
            save_labels(labels)

        return jsonify({
            "ok": True,
            "matched_address": best_addr,
            "delta_packets": best_delta,
            "confidence": confidence,
            "all_spikes": [{"address": a, "delta": d} for a, d in filtered[:5]],
            "message": f"Identified! '{device_name}' = {best_addr} ({best_delta} packets sent)",
        })
    else:
        return jsonify({
            "ok": False,
            "error": "No new sender detected. Press the button again and try 'Check' once more.",
            "all_spikes": [],
        })


@app.route("/api/dirigera/blink-identify", methods=["POST"])
def api_blink_identify():
    """Blink a device and detect which Thread address responds."""
    if not dirigera or not dirigera.is_authenticated():
        return jsonify({"ok": False, "error": "Not paired with hub"}), 401

    data = request.get_json()
    device_id = data.get("device_id", "")
    device_name = data.get("device_name", "")
    device_type = data.get("device_type", "")
    device_room = data.get("device_room", "")

    if not device_id:
        return jsonify({"ok": False, "error": "No device_id provided"}), 400

    import time as _time

    try:
        # Take baseline snapshots (both methods)
        _time.sleep(0.5)
        baseline_link = sniffer.snapshot_link_counts()
        baseline_send = sniffer.snapshot_send_counts()

        # Blink the device (toggles on/off/on/off)
        dirigera.blink_device(device_id)

        # Wait for traffic — blinds are slower
        wait = 3.0 if device_type == "blinds" else 2.0
        _time.sleep(wait)

        # Detect spikes using both methods and merge
        link_spikes = sniffer.detect_spike(baseline_link, min_delta=2)
        send_spikes = sniffer.detect_sender_spike(baseline_send, min_delta=2)

        # Merge: sum deltas from both methods per address
        combined = {}
        for addr, delta in link_spikes + send_spikes:
            combined[addr] = combined.get(addr, 0) + delta
        all_spikes = sorted(combined.items(), key=lambda x: x[1], reverse=True)

        # Filter out hub and already-labeled devices from candidates
        labels = load_labels()
        labeled_addrs = {addr for addr, lbl in labels.items() if lbl.get("name")}
        filtered = [(a, d) for a, d in all_spikes if a != "0x0000" and a not in labeled_addrs]

        if filtered:
            best_addr, best_delta = filtered[0]

            # Confidence: compare top candidate to next non-hub, non-labeled candidate
            if len(filtered) == 1:
                confidence = "high"
            elif best_delta >= filtered[1][1] * 1.5:
                confidence = "high"
            elif best_delta >= filtered[1][1] * 1.2:
                confidence = "good"
            else:
                confidence = "low"

            # Auto-assign label
            labels[best_addr] = {
                "name": device_name,
                "type": device_type,
                "room": device_room,
            }
            save_labels(labels)

            return jsonify({
                "ok": True,
                "matched_address": best_addr,
                "delta_packets": best_delta,
                "confidence": confidence,
                "all_spikes": [{"address": a, "delta": d} for a, d in filtered[:5]],
                "message": f"Identified! '{device_name}' = {best_addr} ({best_delta} extra packets detected)",
            })
        else:
            # Fallback: check if this is the last unassigned blinkable device
            # If so, look for any unlabeled address that spiked at all (even weakly)
            try:
                hub_devices = dirigera.get_device_summary()
                assigned_names = {lbl.get("name") for lbl in labels.values() if lbl.get("name")}
                blinkable_types = {"light", "outlet", "blinds"}
                unassigned_blinkable = [d for d in hub_devices
                                        if d.get("type") in blinkable_types
                                        and d.get("name") not in assigned_names
                                        and d.get("reachable", True)]

                if len(unassigned_blinkable) <= 1:
                    # Last device — check for ANY unlabeled spike, even min_delta=1
                    all_weak = sniffer.detect_spike(baseline_link, min_delta=1)
                    weak_send = sniffer.detect_sender_spike(baseline_send, min_delta=1)
                    weak_combined = {}
                    for addr, delta in all_weak + weak_send:
                        weak_combined[addr] = weak_combined.get(addr, 0) + delta
                    weak_filtered = [(a, d) for a, d in sorted(weak_combined.items(), key=lambda x: -x[1])
                                     if a != "0x0000" and a not in labeled_addrs]

                    if weak_filtered:
                        best_addr, best_delta = weak_filtered[0]
                        return jsonify({
                            "ok": False,
                            "suggestion": True,
                            "matched_address": best_addr,
                            "delta_packets": best_delta,
                            "device_name": device_name,
                            "device_type": device_type,
                            "device_room": device_room,
                            "error": f"Weak spike on {best_addr} (+{best_delta}). This is the last unassigned device — assign it?",
                            "all_spikes": [{"address": a, "delta": d} for a, d in weak_filtered[:5]],
                        })
            except Exception:
                pass

            return jsonify({
                "ok": False,
                "error": "No traffic spike detected. The device may not be reachable or the blink didn't generate enough traffic.",
                "all_spikes": [],
            })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# --- Identify-all state (runs in background thread) ---
_identify_all_state = {"running": False, "results": [], "current": None, "total": 0, "done": 0}
_identify_all_lock = threading.Lock()

@app.route("/api/dirigera/identify-all/start", methods=["POST"])
def api_identify_all_start():
    """Start identifying all unassigned blinkable devices sequentially."""
    if not dirigera or not dirigera.is_authenticated():
        return jsonify({"ok": False, "error": "Not paired with hub"}), 401

    with _identify_all_lock:
        if _identify_all_state["running"]:
            return jsonify({"ok": False, "error": "Already running"}), 409

    # Get devices and labels to find unassigned blinkable ones
    try:
        devices = dirigera.get_device_summary()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    labels = load_labels()
    assigned_names = {lbl.get("name") for lbl in labels.values() if lbl.get("name")}

    blinkable_types = {"light", "outlet", "blinds"}
    candidates = [d for d in devices
                  if d.get("type") in blinkable_types
                  and d.get("name") not in assigned_names
                  and d.get("reachable", True)]

    if not candidates:
        return jsonify({"ok": True, "total": 0, "message": "No unassigned blinkable devices found"})

    with _identify_all_lock:
        _identify_all_state["running"] = True
        _identify_all_state["results"] = []
        _identify_all_state["current"] = None
        _identify_all_state["total"] = len(candidates)
        _identify_all_state["done"] = 0

    def run_identify_all():
        import time as _time
        for dev in candidates:
            with _identify_all_lock:
                if not _identify_all_state["running"]:
                    break
                _identify_all_state["current"] = dev.get("name", "?")

            device_id = dev["id"]
            device_name = dev.get("name", "")
            device_type = dev.get("type", "")
            device_room = dev.get("room", "")

            try:
                _time.sleep(0.5)
                baseline_link = sniffer.snapshot_link_counts()
                baseline_send = sniffer.snapshot_send_counts()

                dirigera.blink_device(device_id)
                wait = 3.0 if device_type == "blinds" else 2.0
                _time.sleep(wait)

                link_spikes = sniffer.detect_spike(baseline_link, min_delta=2)
                send_spikes = sniffer.detect_sender_spike(baseline_send, min_delta=2)
                combined = {}
                for addr, delta in link_spikes + send_spikes:
                    combined[addr] = combined.get(addr, 0) + delta
                all_spikes = sorted(combined.items(), key=lambda x: x[1], reverse=True)

                labels = load_labels()
                labeled_addrs = {addr for addr, lbl in labels.items() if lbl.get("name")}
                filtered = [(a, d) for a, d in all_spikes if a != "0x0000" and a not in labeled_addrs]

                if filtered:
                    best_addr, best_delta = filtered[0]
                    if len(filtered) == 1 or best_delta >= filtered[1][1] * 1.2:
                        labels[best_addr] = {"name": device_name, "type": device_type, "room": device_room}
                        save_labels(labels)
                        result = {"name": device_name, "status": "ok", "address": best_addr, "delta": best_delta}
                    else:
                        result = {"name": device_name, "status": "ambiguous", "address": None, "delta": best_delta}
                else:
                    result = {"name": device_name, "status": "no_spike", "address": None, "delta": 0}
            except Exception as e:
                result = {"name": device_name, "status": "error", "address": None, "error": str(e)}

            with _identify_all_lock:
                _identify_all_state["results"].append(result)
                _identify_all_state["done"] += 1

            # Pause between devices so traffic settles
            _time.sleep(1.0)

        with _identify_all_lock:
            _identify_all_state["running"] = False
            _identify_all_state["current"] = None

    threading.Thread(target=run_identify_all, daemon=True).start()
    return jsonify({"ok": True, "total": len(candidates)})

@app.route("/api/dirigera/identify-all/status")
def api_identify_all_status():
    """Poll progress of identify-all."""
    with _identify_all_lock:
        return jsonify({
            "running": _identify_all_state["running"],
            "current": _identify_all_state["current"],
            "total": _identify_all_state["total"],
            "done": _identify_all_state["done"],
            "results": list(_identify_all_state["results"]),
        })

@app.route("/api/dirigera/identify-all/stop", methods=["POST"])
def api_identify_all_stop():
    """Cancel identify-all."""
    with _identify_all_lock:
        _identify_all_state["running"] = False
    return jsonify({"ok": True})


def main():
    global sniffer, dirigera

    parser = argparse.ArgumentParser(description="Thread Network Monitor Dashboard")
    parser.add_argument("--port", default="COM3", help="Serial port for nRF52840 dongle")
    parser.add_argument("--channel", type=int, default=15, help="802.15.4 channel (11-26)")
    parser.add_argument("--host", default="0.0.0.0", help="Dashboard listen address")
    parser.add_argument("--web-port", type=int, default=8154, help="Dashboard web port")
    parser.add_argument("--pcap", default=None, help="Save pcap capture to file")
    parser.add_argument("--hub-ip", default=None, help="Dirigera hub IP (e.g. 192.168.1.100)")
    args = parser.parse_args()

    # Default pcap path
    if not args.pcap:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.pcap = f"capture_{ts}.pcap"

    print(f"Thread Network Monitor")
    print(f"  Dongle:    {args.port}")
    print(f"  Channel:   {args.channel}")
    print(f"  Dashboard: http://localhost:{args.web_port}")
    print(f"  PCAP:      {args.pcap}")
    print()

    sniffer = ThreadSniffer(port=args.port, channel=args.channel)

    # Set up Dirigera client
    if args.hub_ip:
        from dirigera_client import DigeraClient
        dirigera = DigeraClient(ip=args.hub_ip)
        if dirigera.is_authenticated():
            print(f"  Dirigera:  {args.hub_ip} (paired)")
        else:
            print(f"  Dirigera:  {args.hub_ip} (not paired - use dashboard to pair)")

    def shutdown(sig, frame):
        print("\nStopping capture...")
        sniffer.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    sniffer.start(pcap_path=args.pcap)
    print(f"Capturing on channel {args.channel}... Open http://localhost:{args.web_port}")

    app.run(host=args.host, port=args.web_port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
