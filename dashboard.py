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
  }

  .card-header .badge {
    background: var(--surface2);
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    color: var(--text-dim);
  }

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
  <div class="card" id="deviceCard">
    <div class="card-header">
      Discovered Devices
      <span class="badge" id="deviceCount">0</span>
    </div>
    <div id="deviceTable">
      <div class="empty"><div class="spinner"></div>Waiting for packets...</div>
    </div>
  </div>

  <div class="grid-2">
    <!-- Signal Advice -->
    <div class="card">
      <div class="card-header">Signal Analysis</div>
      <div class="advice" id="adviceContent">
        <div class="advice-item info">Collecting data... Signal analysis will appear after devices are discovered.</div>
      </div>
    </div>

    <!-- Link Quality -->
    <div class="card">
      <div class="card-header">
        Device Links
        <span class="badge" id="linkCount">0</span>
      </div>
      <div id="linkTable">
        <div class="empty">No links observed yet</div>
      </div>
    </div>
  </div>

  <div class="grid-2">
    <!-- Dirigera Hub -->
    <div class="card">
      <div class="card-header">Dirigera Hub Integration</div>
      <div class="advice" id="dirigeraPanel">
        <div class="advice-item info">Checking hub connection...</div>
      </div>
    </div>

    <!-- Toggle Detection -->
    <div class="card">
      <div class="card-header">
        Device Identification
        <div style="display:flex;gap:6px">
          <button onclick="resetToggleIgnored()" id="resetToggleIgnoreBtn" style="font-size:11px;padding:3px 10px;background:var(--surface2);border:1px solid var(--border);color:var(--text-dim);border-radius:4px;cursor:pointer;display:none">Reset ignored</button>
          <button onclick="startToggleMode()" id="toggleBtn" style="font-size:11px;padding:3px 10px;background:var(--surface2);border:1px solid var(--border);color:var(--text);border-radius:4px;cursor:pointer">Start Toggle Mode</button>
        </div>
      </div>
      <div id="togglePanel">
        <div class="advice">
          <div class="advice-item info">Turn off a device, then click "Start Toggle Mode" to see which address disappears. Click the device row to label it.</div>
        </div>
      </div>
    </div>
  </div>

  <!-- Live Packet Feed -->
  <div class="card">
    <div class="card-header">
      Live Packet Feed
      <span class="badge" id="feedCount">0</span>
    </div>
    <div class="feed" id="packetFeed">
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
    const labelInfo = d.label_room ? ` <span class="dim" style="font-size:11px">(${d.label_room})</span>` : '';
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
    document.getElementById('statusDot').style.background = 'var(--excellent)';

    renderDevices(data.devices);
    renderLinks(data.links);
    renderAdvice(data.devices, data.links);
    renderFeed(data.recent_packets);
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
        '<button onclick="loadDirigeraDevices()" style="margin:8px;padding:6px 14px;background:var(--accent);color:white;border:none;border-radius:6px;cursor:pointer;font-size:13px">Load Hub Devices</button>' +
        '<div id="dirigeraDevices"></div>';
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

  let html = '<table style="margin-top:8px"><thead><tr><th>Name</th><th>Type</th><th>Room</th><th>Model</th><th>Reachable</th><th>Action</th></tr></thead><tbody>';
  for (const dev of d.devices) {
    const reachable = dev.reachable ? '<span style="color:var(--excellent)">Yes</span>' : '<span style="color:var(--very-weak)">No</span>';
    const assignedAddr = nameToAddr[dev.name];

    let actionHtml;
    if (assignedAddr) {
      actionHtml = `<span style="font-size:11px;color:var(--excellent)">Assigned to <code>${assignedAddr}</code></span>
        <button onclick="unassignDirigera('${assignedAddr}')" style="margin-left:6px;padding:2px 8px;font-size:10px;background:var(--very-weak);border:none;border-radius:4px;color:white;cursor:pointer">Unassign</button>`;
    } else {
      actionHtml = `<button onclick="autoLabel('${(dev.name||'').replace(/'/g,'')}','${dev.type||''}','${(dev.room||'').replace(/'/g,'')}')" style="padding:2px 8px;font-size:11px;background:var(--surface2);border:1px solid var(--border);border-radius:4px;color:var(--text);cursor:pointer">Assign to address</button>`;
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
