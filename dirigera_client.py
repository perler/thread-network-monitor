"""
Minimal Dirigera hub API client.
Handles OAuth2 PKCE authentication and device listing.
"""

import os
import json
import hashlib
import base64
import string
import random
import urllib3
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TOKEN_FILE = "dirigera_token.json"


def _random_verifier(length=128):
    chars = string.ascii_letters + string.digits + "-._~"
    return "".join(random.choice(chars) for _ in range(length))


def _code_challenge(verifier):
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class DigeraClient:
    def __init__(self, ip, token=None, token_file=TOKEN_FILE):
        self.ip = ip
        self.base = f"https://{ip}:8443"
        self.token = token
        self.token_file = token_file
        if not token:
            self._load_token()

    def _load_token(self):
        if os.path.exists(self.token_file):
            with open(self.token_file) as f:
                data = json.load(f)
                self.token = data.get("access_token")

    def _save_token(self, token):
        self.token = token
        with open(self.token_file, "w") as f:
            json.dump({"access_token": token, "hub_ip": self.ip}, f, indent=2)

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def start_pairing(self):
        """Start OAuth flow. Returns (auth_code, code_verifier).
        User must press the button on the hub within 60 seconds."""
        verifier = _random_verifier()
        challenge = _code_challenge(verifier)
        resp = requests.get(
            f"{self.base}/v1/oauth/authorize",
            params={
                "audience": "homesmart.local",
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            verify=False,
            timeout=10,
        )
        resp.raise_for_status()
        code = resp.json().get("code")
        return code, verifier

    def complete_pairing(self, code, verifier, name="ThreadMonitor"):
        """Exchange auth code for access token. Must be called after button press."""
        resp = requests.post(
            f"{self.base}/v1/oauth/token",
            data={
                "code": code,
                "name": name,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            verify=False,
            timeout=10,
        )
        resp.raise_for_status()
        token = resp.json().get("access_token")
        self._save_token(token)
        return token

    def is_authenticated(self):
        if not self.token:
            return False
        try:
            resp = requests.get(
                f"{self.base}/v1/hub/status",
                headers=self._headers(),
                verify=False,
                timeout=5,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def get_devices(self):
        """Get all devices from the hub. Returns list of device dicts."""
        resp = requests.get(
            f"{self.base}/v1/devices",
            headers=self._headers(),
            verify=False,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def get_device_summary(self):
        """Get a simplified list: name, type, reachable, room, model."""
        devices = self.get_devices()
        result = []
        for d in devices:
            attrs = d.get("attributes", {})
            room = d.get("room", {})
            result.append({
                "id": d.get("id", ""),
                "name": attrs.get("customName", d.get("customName", "")),
                "type": d.get("deviceType", d.get("type", "")),
                "model": attrs.get("model", d.get("model", "")),
                "manufacturer": attrs.get("manufacturer", d.get("manufacturer", "")),
                "firmware": attrs.get("firmwareVersion", ""),
                "reachable": d.get("isReachable", None),
                "room": room.get("name", room.get("customName", "")),
                "is_on": attrs.get("isOn"),
            })
        return result

    def toggle_device(self, device_id, on=True):
        """Toggle a device on or off."""
        resp = requests.patch(
            f"{self.base}/v1/devices/{device_id}",
            headers={**self._headers(), "Content-Type": "application/json"},
            json=[{"attributes": {"isOn": on}}],
            verify=False,
            timeout=5,
        )
        resp.raise_for_status()
        return resp.status_code == 200

    def blink_device(self, device_id):
        """Blink a device to create a traffic burst for identification."""
        import time
        # Get current state
        resp = requests.get(
            f"{self.base}/v1/devices/{device_id}",
            headers=self._headers(),
            verify=False,
            timeout=5,
        )
        resp.raise_for_status()
        dev = resp.json()
        attrs = dev.get("attributes", {})
        dev_type = dev.get("deviceType", dev.get("type", ""))

        if "blindsTargetLevel" in attrs:
            # Blinds: nudge level slightly then back
            current_level = attrs.get("blindsTargetLevel", 0)
            nudge = min(current_level + 5, 100) if current_level < 95 else max(current_level - 5, 0)
            for level in [nudge, current_level, nudge, current_level]:
                self._set_attribute(device_id, "blindsTargetLevel", level)
                time.sleep(0.5)
        else:
            # Lights/outlets: toggle on/off
            was_on = attrs.get("isOn", False)
            for state in [not was_on, was_on, not was_on, was_on]:
                self.toggle_device(device_id, on=state)
                time.sleep(0.4)

        return True

    def _set_attribute(self, device_id, attr, value):
        """Set a single attribute on a device."""
        resp = requests.patch(
            f"{self.base}/v1/devices/{device_id}",
            headers={**self._headers(), "Content-Type": "application/json"},
            json=[{"attributes": {attr: value}}],
            verify=False,
            timeout=5,
        )
        resp.raise_for_status()
