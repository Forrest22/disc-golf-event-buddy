"""
scraper.py — PDGA Live Score Scraper

Manages per-tournament scraping. The landing page selects a tournament,
then the scoreboard page drives everything via ?tournId= query params.

Our API endpoints (mirroring PDGA's pattern):
  GET /api/events                         → proxies PDGA current-events list
  GET /api/event/<tournId>                → event metadata + divisions
  GET /api/scores?tournId=<id>            → live scores for active tournament

PDGA API endpoints used:
  https://www.pdga.com/api/v1/feat/current-events/tournaments
  https://www.pdga.com/apps/tournament/live-api/live_results_fetch_event?TournID=<id>
  https://www.pdga.com/apps/tournament/live-api/live_results_fetch_round?TournID=<id>&Division=<div>&Round=<n>
"""

import time
import threading
from datetime import datetime, timezone
import requests
from src.cache import save_scores, load_scores

# ─────────────────────────────────────────────────────────────
# PDGA API base URLs
# ─────────────────────────────────────────────────────────────
PDGA_EVENTS_URL  = "https://www.pdga.com/api/v1/feat/current-events/tournaments"
PDGA_LIVE_BASE   = "https://www.pdga.com/apps/tournament/live-api"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PDGAScoreboard/1.0)",
    "Accept":     "application/json",
}

# ─────────────────────────────────────────────────────────────
# Shared scraper state — one active tournament at a time.
# Flask reads `active_scores`; landing page writes `active_tourn_id`.
# ─────────────────────────────────────────────────────────────
active_tourn_id = None          # set when user selects a tournament
active_scores   = {             # latest fetched scores, served by /api/scores
    "tourn_id":    None,
    "event_name":  "No tournament selected",
    "event_round": "",
    "last_updated": None,
    "divisions":   [],
}
state_lock = threading.Lock()   # guards both active_tourn_id and active_scores


# ─────────────────────────────────────────────────────────────
# Public setters called by Flask routes
# ─────────────────────────────────────────────────────────────
def set_active_tournament(tourn_id: str):
    """
    Switch the scraper to a new tournament. Thread-safe.

    Immediately warms active_scores from the SQLite cache (any age) so the
    scoreboard can render something while the background fetch is in flight.
    The polling loop will overwrite with fresh PDGA data within one cycle.
    """
    global active_tourn_id
    tid = str(tourn_id)

    # Try to serve stale cache immediately — max_age=0 means "any age is fine"
    cached = load_scores(tid, max_age=0)

    with state_lock:
        active_tourn_id = tid
        if cached:
            # Serve cached data right away; mark it so the frontend knows
            cached["from_cache"] = True
            active_scores.update(cached)
            print(f"[scraper] TournID={tid} — warmed from cache instantly")
        else:
            # Nothing cached yet; show loading state
            active_scores["tourn_id"]     = tid
            active_scores["event_name"]   = "Loading…"
            active_scores["event_round"]  = ""
            active_scores["last_updated"] = None
            active_scores["divisions"]    = []
            active_scores["from_cache"]   = False
    print(f"[scraper] Active tournament set to {tid}")


def get_active_scores() -> dict:
    """Return a snapshot of the latest scores. Thread-safe."""
    with state_lock:
        return dict(active_scores)


# ─────────────────────────────────────────────────────────────
# PDGA proxy helpers (used directly by Flask API routes too)
# ─────────────────────────────────────────────────────────────
def fetch_current_events() -> list:
    """
    Proxy: GET /api/events
    Returns the raw PDGA current-events list.
    """
    resp = requests.get(PDGA_EVENTS_URL, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_event_info(tourn_id: str) -> dict:
    """
    Proxy: GET /api/event/<tournId>
    Returns PDGA event metadata including divisions and round info.
    """
    url  = f"{PDGA_LIVE_BASE}/live_results_fetch_event"
    resp = requests.get(url, params={"TournID": tourn_id}, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()["data"]


def fetch_division_scores(tourn_id: str, division_code: str, round_num: int) -> dict:
    """
    Fetch player scores for a single division + round from PDGA.
    Not exposed as its own route — used internally by the scraper loop.
    """
    url  = f"{PDGA_LIVE_BASE}/live_results_fetch_round"
    resp = requests.get(
        url,
        params={"TournID": tourn_id, "Division": division_code, "Round": round_num},
        headers=HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["data"]


# ─────────────────────────────────────────────────────────────
# Score formatting helpers
# ─────────────────────────────────────────────────────────────
def format_score(score) -> str:
    """Convert integer score-to-par → display string: E / +N / -N."""
    if score is None:
        return "-"
    try:
        score = int(score)
    except (ValueError, TypeError):
        return str(score)
    if score == 0:
        return "E"
    if score > 0:
        return f"+{score}"
    return str(score)


def format_thru(played, completed: bool, holes=18) -> str:
    """Return hole-through string: a number, or 'F' if round finished."""
    played = int(played) if played is not None else 0
    holes  = int(holes)  if holes  is not None else 18
    if completed or played >= holes:
        return "F"
    return str(played) if played else "-"


# ─────────────────────────────────────────────────────────────
# Full score fetch for one tournament
# ─────────────────────────────────────────────────────────────
def _build_scores(tourn_id: str) -> dict:
    """
    Fetch event info + all division scores from PDGA, return a scores dict
    ready to be stored in active_scores and served to the frontend.
    """
    event        = fetch_event_info(tourn_id)
    latest_round = event.get("LatestRound") or event.get("HighestCompletedRound") or 1
    event_name   = event.get("Name", "PDGA Event")
    round_label  = (
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
            round_data  = fetch_division_scores(tourn_id, div_code, div_round)
            players_raw = round_data.get("scores", [])
        except Exception as e:
            print(f"[scraper] Failed to fetch {div_code} Rd{div_round}: {e}")
            continue

        if not players_raw:
            continue

        # PDGA uses 999 (offset to ~+935 after par adjustment) as a sentinel
        # for DNF/incomplete rounds. Treat any round score >= 900 as DNF.
        DNF_SENTINEL = 900

        players_out = []
        for p in players_raw:
            place     = int(p["RunningPlace"]) if p.get("RunningPlace") is not None else 0
            tied      = bool(p.get("Tied", False))
            to_par    = p.get("ToPar")
            round_par = p.get("RoundtoPar")
            played    = int(p["Played"])  if p.get("Played")  is not None else 0
            completed = bool(p.get("Completed", 0))
            holes     = int(p["Holes"])   if p.get("Holes")   is not None else 18

            dnf = round_par is not None and int(round_par) >= DNF_SENTINEL

            players_out.append({
                "place":         place,
                "place_display": f"T{place}" if tied else str(place),
                "name":          p.get("Name", "Unknown"),
                "short_name":    p.get("ShortName", p.get("Name", "")),
                "score":         None if dnf else to_par,
                "score_display": "DNF" if dnf else format_score(to_par),
                "round_score":   "DNF" if dnf else format_score(round_par),
                "thru":          format_thru(played, completed, holes),
                "country":       p.get("Country", ""),
                "rating":        p.get("Rating"),
            })

        players_out.sort(key=lambda x: x["place"] if x["place"] is not None else 9999)

        divisions_out.append({
            "name":    div_name,
            "code":    div_code,
            "round":   div_round,
            "players": players_out,
        })

    return {
        "tourn_id":    tourn_id,
        "event_name":  event_name,
        "event_round": round_label,
        "end_date":    event.get("EndDate"),   # ISO date string e.g. "2026-03-08"
        "last_updated": datetime.now().strftime("%I:%M:%S %p"),
        "divisions":   divisions_out,
    }


# ─────────────────────────────────────────────────────────────
# Background polling loop
# ─────────────────────────────────────────────────────────────
def _tournament_is_over(tourn_id: str) -> bool:
    """
    Returns True if the tournament ended more than 1 day ago AND we have
    a cached result for it — meaning there is no point re-fetching from PDGA.

    Uses the end_date stored inside the cached scores dict (put there by
    _build_scores) so we don't need an extra API call to check.
    """
    cached = load_scores(tourn_id, max_age=0)   # any age — we just want end_date
    if not cached:
        return False   # no cache → must fetch at least once

    end_date_str = cached.get("end_date")
    if not end_date_str:
        return False   # no end_date stored → can't tell, fetch anyway

    try:
        # end_date is "YYYY-MM-DD"; compare against today in UTC
        end_date = datetime.strptime(end_date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now      = datetime.now(timezone.utc)
        days_ago = (now - end_date).days
        if days_ago > 1:
            print(f"[scraper] TournID={tourn_id} ended {days_ago} day(s) ago — skipping PDGA fetch, serving cache")
            return True
    except ValueError:
        pass   # malformed date → fetch anyway

    return False


def _scraper_loop(poll_interval: int = 30):
    """
    Continuously polls PDGA for the active tournament's scores.
    Sleeps poll_interval seconds between fetches.
    Skips gracefully if no tournament is selected.
    Skips PDGA fetch entirely if the tournament ended more than 1 day ago
    and a cached result already exists.
    """
    while True:
        tid = None
        with state_lock:
            tid = active_tourn_id

        if tid:
            if _tournament_is_over(tid):
                # Tournament is finished and cached — no need to re-fetch.
                # active_scores was already warmed from cache in set_active_tournament,
                # so we just sleep and check again next cycle (in case user switches events).
                pass
            else:
                try:
                    scores = _build_scores(tid)
                    # Persist to SQLite before updating in-memory state
                    save_scores(tid, scores)

                    with state_lock:
                        # Only update if the tournament hasn't changed mid-fetch
                        if active_tourn_id == tid:
                            scores["from_cache"] = False
                            active_scores.update(scores)
                    print(f"[scraper] TournID={tid} — updated {len(scores['divisions'])} divisions at {scores['last_updated']} (saved to cache)")
                except Exception as e:
                    print(f"[scraper] Error fetching TournID={tid}: {e}")
        else:
            print("[scraper] No active tournament, waiting…")

        time.sleep(poll_interval)


def start_scraper(poll_interval: int = 30):
    """Start the background scraper thread. Call once at app startup."""
    t = threading.Thread(target=_scraper_loop, args=(poll_interval,), daemon=True)
    t.start()
    print(f"[scraper] Background scraper started (poll every {poll_interval}s).")