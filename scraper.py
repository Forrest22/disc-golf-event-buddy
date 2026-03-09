"""
scraper.py — PDGA Live Score Scraper

Fetches live scores from the PDGA live results API.

API endpoints used:
  /live_results_fetch_event?TournID={id}
      → returns event metadata + list of divisions

  /live_results_fetch_round?TournID={id}&Division={div}&Round={round}
      → returns player scores for a division/round

Usage:
  Set TOURN_ID below to your event's tournament ID (found in the event URL).
  Run `python app.py` and open http://localhost:5000
"""

import time
import threading
import requests
from datetime import datetime

# ─────────────────────────────────────────────────────────────
# CONFIG — set your tournament ID here
# ─────────────────────────────────────────────────────────────
TOURN_ID = "97704"  # ← replace with your event's TournID

POLL_INTERVAL_SECONDS = 30  # how often to re-fetch scores

BASE_URL = "https://www.pdga.com/apps/tournament/live-api"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PDGAScoreboard/1.0)",
    "Accept": "application/json",
}

# ─────────────────────────────────────────────────────────────
# Shared state — Flask reads this dict
# ─────────────────────────────────────────────────────────────
scores_data = {
    "event_name": "Loading…",
    "event_round": "",
    "last_updated": None,
    "divisions": [],
}
scores_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────
# API fetchers
# ─────────────────────────────────────────────────────────────
def fetch_event_info():
    """Fetch event metadata and division list."""
    url = f"{BASE_URL}/live_results_fetch_event"
    resp = requests.get(url, params={"TournID": TOURN_ID}, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()["data"]


def fetch_division_scores(division_code: str, round_num: int):
    """Fetch player scores for a single division + round."""
    url = f"{BASE_URL}/live_results_fetch_round"
    resp = requests.get(
        url,
        params={"TournID": TOURN_ID, "Division": division_code, "Round": round_num},
        headers=HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["data"]


# ─────────────────────────────────────────────────────────────
# Score formatting helpers
# ─────────────────────────────────────────────────────────────
def format_score(score):
    """Convert integer score-to-par into display string (E, +N, -N)."""
    if score is None:
        return "-"
    try:
        score = int(score)
    except (ValueError, TypeError):
        return str(score)
    if score == 0:
        return "E"
    elif score > 0:
        return f"+{score}"
    else:
        return str(score)


def format_thru(played: int, completed: bool, holes: int = 18) -> str:
    """Show hole number player is through, or F if finished."""
    if completed or played >= holes:
        return "F"
    return str(played) if played else "-"


# ─────────────────────────────────────────────────────────────
# Main fetch + parse
# ─────────────────────────────────────────────────────────────
def fetch_scores():
    """
    Fetch event info, then scores for every division at the latest round.
    Returns event name, round label, and list of division dicts.
    """
    event = fetch_event_info()
    latest_round = event.get("LatestRound") or event.get("HighestCompletedRound") or 1
    event_name = event.get("Name", "PDGA Event")
    round_label = (
        event.get("RoundsList", {})
        .get(str(latest_round), {})
        .get("Label", f"Round {latest_round}")
    )

    divisions_out = []

    for div in event.get("Divisions", []):
        div_code  = div["Division"]
        div_name  = div.get("AbbreviatedName") or div.get("DivisionName") or div_code
        div_round = div.get("LatestRound") or latest_round

        try:
            round_data = fetch_division_scores(div_code, div_round)
            players_raw = round_data.get("scores", [])
        except Exception as e:
            print(f"[scraper] Failed to fetch {div_code} round {div_round}: {e}")
            continue

        if not players_raw:
            continue

        players_out = []
        for p in players_raw:
            place      = p.get("RunningPlace") or 0
            tied       = p.get("Tied", False)
            to_par     = p.get("ToPar")
            round_par  = p.get("RoundtoPar")
            played     = p.get("Played", 0)
            completed  = bool(p.get("Completed", 0))
            holes      = p.get("Holes", 18)

            players_out.append({
                "place":         place,
                "place_display": f"T{place}" if tied else str(place),
                "name":          p.get("Name", "Unknown"),
                "short_name":    p.get("ShortName", p.get("Name", "")),
                "score":         to_par,
                "score_display": format_score(to_par),
                "round_score":   format_score(round_par),
                "thru":          format_thru(played, completed, holes),
                "country":       p.get("Country", ""),
                "rating":        p.get("Rating"),
            })

        players_out.sort(key=lambda x: x["place"])

        divisions_out.append({
            "name":    div_name,
            "code":    div_code,
            "round":   div_round,
            "players": players_out,
        })

    return event_name, round_label, divisions_out


# ─────────────────────────────────────────────────────────────
# Background polling thread
# ─────────────────────────────────────────────────────────────
def scraper_loop():
    while True:
        try:
            event_name, round_label, divisions = fetch_scores()
            now = datetime.now().strftime("%I:%M:%S %p")
            with scores_lock:
                scores_data["event_name"]   = event_name
                scores_data["event_round"]  = round_label
                scores_data["last_updated"] = now
                scores_data["divisions"]    = divisions
            print(f"[scraper] Updated {len(divisions)} divisions at {now}")
        except Exception as e:
            print(f"[scraper] Error: {e}")
        time.sleep(POLL_INTERVAL_SECONDS)


def start_scraper():
    t = threading.Thread(target=scraper_loop, daemon=True)
    t.start()
    print("[scraper] Background scraper started.")
