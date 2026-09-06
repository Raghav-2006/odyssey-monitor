#!/usr/bin/env python3
"""
Landmark Cinemas showtime monitor.

Hits the Landmark movie API directly (via curl_cffi to bypass Akamai bot
protection) and diffs against a state file. Pings Discord when new
showtimes appear.

Configure via environment variables:
  LANDMARK_FILM_ID       -- Landmark film ID (e.g. 125801)
  LANDMARK_CINEMA_ID     -- cinema ID (e.g. 214 = New Westminster)
  LANDMARK_CINEMA_NAME   -- display name for notifications
  LANDMARK_CIRCUIT       -- circuit ID (default: 22)
  LANDMARK_FILM_URL      -- page URL path for the "BUY NOW" link
  DISCORD_WEBHOOK_URL    -- Discord webhook
  STATE_FILE             -- path to state JSON (default: state_landmark.json)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from curl_cffi import requests as cffi_requests

# ---------- Configuration ----------

LANDMARK_API_BASE = "https://movieapi.landmarkcinemas.com"
LANDMARK_SITE = "https://www.landmarkcinemas.com"
FILM_ID = int(os.environ.get("LANDMARK_FILM_ID", "125801"))
CINEMA_ID = os.environ.get("LANDMARK_CINEMA_ID", "214")
CINEMA_NAME = os.environ.get("LANDMARK_CINEMA_NAME", "New Westminster")
CIRCUIT = os.environ.get("LANDMARK_CIRCUIT", "22")
FILM_URL_PATH = os.environ.get("LANDMARK_FILM_URL", "/film-info/avengers-doomsday")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
STATE_FILE = Path(os.environ.get("STATE_FILE", "state_landmark.json"))


# ---------- Core logic ----------


def fetch_showtimes_api() -> tuple[list[dict], str]:
    """
    Fetch all movies at the cinema and return (sessions_for_film, film_title).
    Sessions are the raw date entries from the API.
    """
    url = (
        f"{LANDMARK_API_BASE}/movies/{CIRCUIT}/{CINEMA_ID}"
        "?expandGenres=true&splitByAttributes=true&expandSessions=true"
    )
    resp = cffi_requests.get(url, impersonate="chrome", timeout=30)
    resp.raise_for_status()
    data = resp.json()

    for film in data:
        if film.get("FilmId") == FILM_ID:
            return film.get("Sessions", []), film.get("Title", "")

    return [], ""


def extract_showtimes(sessions: list[dict]) -> set[str]:
    """
    Extract showtime strings like 'Thu Dec 17 @ 1:00 PM' from API sessions.
    """
    showtimes: set[str] = set()
    for session in sessions:
        display_date = session.get("DisplayDate", "")
        for exp_type in session.get("ExperienceTypes", []):
            for time_slot in exp_type.get("Times", []):
                start = time_slot.get("StartTime", "")
                if start:
                    label = f"{display_date} @ {start}"
                    showtimes.add(label)
    return showtimes


def fingerprint_sessions(sessions: list[dict]) -> str:
    normalized = json.dumps(sessions, sort_keys=True)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            print("WARNING: state file unreadable, starting fresh.", file=sys.stderr)
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def notify_discord(message: str) -> None:
    if not DISCORD_WEBHOOK:
        print("[!] No DISCORD_WEBHOOK_URL set; would have sent:")
        print(message)
        return
    payload = {"content": message[:1900]}
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=15)
        r.raise_for_status()
        print("[+] Discord notification sent.")
    except requests.RequestException as e:
        print(f"[!] Discord notification failed: {e}", file=sys.stderr)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- Main ----------


def main() -> int:
    print(f"[{now_iso()}] Checking Landmark {CINEMA_NAME} for film {FILM_ID}")

    try:
        sessions, film_title = fetch_showtimes_api()
    except Exception as e:
        print(f"[!] API fetch failed: {e}", file=sys.stderr)
        return 1

    current_times = extract_showtimes(sessions)
    current_hash = fingerprint_sessions(sessions)
    film_found = bool(film_title)

    print(f"    film found: {film_found}")
    if film_title:
        print(f"    title: {film_title}")
    print(f"    dates listed: {len(sessions)}")
    print(f"    parsed showtimes: {len(current_times)}")
    if current_times:
        for s in sorted(current_times):
            print(f"      - {s}")

    state = load_state()
    prev_times = set(state.get("showtimes", []))
    prev_hash = state.get("fingerprint", "")

    new_times = current_times - prev_times
    hash_changed = bool(prev_hash) and current_hash and current_hash != prev_hash

    alerts: list[str] = []

    if new_times:
        lines = [
            f"🎬 **NEW {film_title} showtimes at Landmark {CINEMA_NAME}!**",
            "",
            f"**{len(new_times)} new showtime(s):**",
        ]
        for s in sorted(new_times):
            lines.append(f"• {s}")
        lines.append("")
        lines.append(f"BUY NOW → {LANDMARK_SITE}{FILM_URL_PATH}")
        alerts.append("\n".join(lines))

    elif hash_changed and not current_times:
        alerts.append(
            f"👀 **Landmark {CINEMA_NAME} listing for {film_title} changed** — "
            "no parseable showtimes extracted. Check manually:\n"
            f"{LANDMARK_SITE}{FILM_URL_PATH}"
        )

    if alerts:
        for msg in alerts:
            notify_discord(msg)
    else:
        print("    no new showtimes since last check.")

    if film_found:
        merged_times = sorted(prev_times | current_times)
        state["showtimes"] = merged_times
        state["fingerprint"] = current_hash
        state["last_check"] = now_iso()
        state["film_title"] = film_title
        save_state(state)
    else:
        state["last_check"] = now_iso()
        save_state(state)
        print(f"    NOTE: film {FILM_ID} not found at {CINEMA_NAME}; state not updated.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
