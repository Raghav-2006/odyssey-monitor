#!/usr/bin/env python3
"""
Cineplex Odyssey 70mm Langley showtime monitor.

Checks the Cineplex showtimes API for new showtimes near a chosen theatre
and sends a Discord notification the moment new ones appear.

Strategy:
  1. Hit the Cineplex theatrical API for the film's showtimes (structured JSON).
  2. Filter to the target theatre by LOCATION_KEYWORD.
  3. Extract date+time pairs and diff against state.json.
  4. If anything is new, ping Discord.

Configure via environment variables (see .env.example):
  MOVIE_URL              -- Cineplex movie page URL (used in notification links)
  FILM_ID                -- Cineplex film ID (from __NEXT_DATA__ on the movie page)
  LOCATION_KEYWORD       -- substring used to match the theatre name (e.g. "Langley")
  DISCORD_WEBHOOK_URL    -- Discord webhook for notifications (required for alerts)
  STATE_FILE             -- path to state JSON (default: state.json)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------- Configuration ----------

MOVIE_URL = os.environ.get(
    "MOVIE_URL",
    "https://www.cineplex.com/movie/the-odyssey-the-imax-experience-in-70mm-film",
)
FILM_ID = os.environ.get("FILM_ID", "38376")
LOCATION_KEYWORD = os.environ.get("LOCATION_KEYWORD", "Langley")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
STATE_FILE = Path(os.environ.get("STATE_FILE", "state.json"))

SHOWTIMES_API_BASE = "https://apis.cineplex.com/prod/cpx/theatrical/api"
SHOWTIMES_API_KEY = "dcdac5601d864addbc2675a2e96cb1f8"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Ocp-Apim-Subscription-Key": SHOWTIMES_API_KEY,
}


# ---------- Core logic ----------


def fetch_showtimes_api(film_id: str) -> list[dict]:
    """Fetch showtimes from the Cineplex theatrical API."""
    url = f"{SHOWTIMES_API_BASE}/v1/showtimes?filmId={film_id}"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def extract_showtimes(api_data: list[dict], keyword: str) -> tuple[set[str], str, str]:
    """
    Filter API response to the theatre matching `keyword` and extract
    showtime strings like 'Wed Jul 16 @ 2:00 PM'.

    Returns (set_of_showtime_strings, theatre_name_or_empty, movie_name_or_empty).
    """
    showtimes: set[str] = set()
    matched_theatre = ""
    movie_name = ""

    for theatre in api_data:
        name = theatre.get("theatre", "")
        if keyword.lower() not in name.lower():
            continue
        matched_theatre = name
        for date_entry in theatre.get("dates", []):
            for movie in date_entry.get("movies", []):
                if not movie_name:
                    movie_name = movie.get("name", "")
                for exp in movie.get("experiences", []):
                    for session in exp.get("sessions", []):
                        raw = session.get("showStartDateTime", "")
                        if not raw:
                            continue
                        try:
                            dt = datetime.fromisoformat(raw)
                            label = dt.strftime("%a %b %d @ %-I:%M %p")
                            showtimes.add(label)
                        except ValueError:
                            showtimes.add(raw)

    return showtimes, matched_theatre, movie_name


def fingerprint_data(api_data: list[dict], keyword: str) -> str:
    """Hash the filtered API data as a change-detection backup."""
    relevant = [
        t for t in api_data if keyword.lower() in t.get("theatre", "").lower()
    ]
    normalized = json.dumps(relevant, sort_keys=True)
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
    print(f"[{now_iso()}] Checking film {FILM_ID} for '{LOCATION_KEYWORD}'")

    try:
        api_data = fetch_showtimes_api(FILM_ID)
    except requests.RequestException as e:
        print(f"[!] API fetch failed: {e}", file=sys.stderr)
        return 1

    current_times, theatre_name, movie_name = extract_showtimes(api_data, LOCATION_KEYWORD)
    keyword_found = bool(theatre_name)
    current_hash = fingerprint_data(api_data, LOCATION_KEYWORD) if keyword_found else ""

    print(f"    keyword found: {keyword_found}")
    if theatre_name:
        print(f"    matched theatre: {theatre_name}")
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
            f"🎬 **NEW {movie_name or 'movie'} showtimes detected!**",
            f"Theatre: **{theatre_name or LOCATION_KEYWORD}**",
            "",
            f"**{len(new_times)} new showtime(s):**",
        ]
        for s in sorted(new_times):
            lines.append(f"• {s}")
        lines.append("")
        lines.append(f"BUY NOW → {MOVIE_URL}")
        alerts.append("\n".join(lines))

    elif hash_changed and not current_times:
        alerts.append(
            f"👀 **Cineplex {LOCATION_KEYWORD} section for Odyssey changed**, but no parseable "
            "showtimes were extracted. The page may have been updated — check manually:\n"
            f"{MOVIE_URL}"
        )

    if alerts:
        for msg in alerts:
            notify_discord(msg)
    else:
        print("    no new showtimes since last check.")

    if keyword_found:
        merged_times = sorted(prev_times | current_times)
        state["showtimes"] = merged_times
        state["fingerprint"] = current_hash
        state["last_check"] = now_iso()
        state["last_keyword_found"] = True
        save_state(state)
    else:
        state["last_check"] = now_iso()
        state["last_keyword_found"] = False
        save_state(state)
        print(f"    NOTE: '{LOCATION_KEYWORD}' not found in API response; state not updated for showtimes.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
