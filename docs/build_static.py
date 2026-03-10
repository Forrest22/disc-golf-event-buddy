#!/usr/bin/env python3
"""
build_static.py — Generate a self-contained static scoreboard for GitHub Pages.

Usage:
    python build_static.py --tourn-id 12345
    python build_static.py --tourn-id 12345 --out docs/index.html --repo user/repo
    python build_static.py --list-events          # print current PDGA events and exit

What it does:
    1. Fetches live score data from PDGA for the given tournament ID.
    2. Renders templates/scoreboard-static.html (a Jinja2 child of scoreboard.html)
       with the score data baked in as a JS constant.
    3. Writes a single self-contained index.html — no server required.
    4. Copies static/theme.css alongside it.

The output can be committed to:
    - A `docs/` folder  ->  Settings > Pages > Deploy from branch > docs/
    - A `gh-pages` branch root

The static page is a snapshot — scores are fixed at build time and do not
poll for updates. Re-run this script and push to refresh.
"""

import argparse
import json
import requests
import shutil
import sys
from datetime import datetime
from pathlib import Path

import jinja2

# Add both the script's own directory and a `src/` sibling to sys.path so
# this script works regardless of where it lives in the repo (root, docs/, etc.)
# and regardless of whether scraper.py is at root or in src/.
_here = Path(__file__).resolve().parent

# ─────────────────────────────────────────────────────────────
# PDGA fetching & score-building — copied from scraper.py so
# build_static.py has no import dependencies on the src/ package.
# Keep in sync with src/scraper.py if that file changes.
# ─────────────────────────────────────────────────────────────

PDGA_EVENTS_URL = "https://www.pdga.com/api/v1/feat/current-events/tournaments"
PDGA_LIVE_BASE  = "https://www.pdga.com/apps/tournament/live-api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PDGAScoreboard/1.0)",
    "Accept":     "application/json",
}


def fetch_current_events() -> list:
    resp = requests.get(PDGA_EVENTS_URL, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_event_info(tourn_id: str) -> dict:
    url  = f"{PDGA_LIVE_BASE}/live_results_fetch_event"
    resp = requests.get(url, params={"TournID": tourn_id}, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()["data"]


def fetch_division_scores(tourn_id: str, division_code: str, round_num: int) -> dict:
    url  = f"{PDGA_LIVE_BASE}/live_results_fetch_round"
    resp = requests.get(url, params={"TournID": tourn_id, "Division": division_code,
                                     "Round": round_num}, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()["data"]


def format_score(score) -> str:
    if score is None:
        return "-"
    try:
        score = int(score)
    except (ValueError, TypeError):
        return str(score)
    if score == 0: return "E"
    if score > 0:  return f"+{score}"
    return str(score)


def format_thru(played, completed: bool, holes=18) -> str:
    played = int(played) if played is not None else 0
    holes  = int(holes)  if holes  is not None else 18
    if completed or played >= holes:
        return "F"
    return str(played) if played else "-"


def _build_scores(tourn_id: str) -> dict:
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
            print(f"[build] Failed to fetch {div_code} Rd{div_round}: {e}")
            continue

        if not players_raw:
            continue

        players_out = []
        for p in players_raw:
            place     = int(p["RunningPlace"]) if p.get("RunningPlace") is not None else 0
            tied      = bool(p.get("Tied", False))
            to_par    = p.get("ToPar")
            round_par = p.get("RoundtoPar")
            played    = int(p["Played"])  if p.get("Played")  is not None else 0
            completed = bool(p.get("Completed", 0))
            holes     = int(p["Holes"])   if p.get("Holes")   is not None else 18

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

        players_out.sort(key=lambda x: x["place"] if x["place"] is not None else 9999)
        divisions_out.append({
            "name":    div_name,
            "code":    div_code,
            "round":   div_round,
            "players": players_out,
        })

    return {
        "tourn_id":     tourn_id,
        "event_name":   event_name,
        "event_round":  round_label,
        "end_date":     event.get("EndDate"),
        "last_updated": datetime.now().strftime("%I:%M:%S %p"),
        "divisions":    divisions_out,
    }


# ─────────────────────────────────────────────────────────────
# Jinja2 environment — points at the existing templates/ folder
# ─────────────────────────────────────────────────────────────

def _json_for_script(data) -> str:
    """
    Serialize data to JSON that is safe to embed inside a <script> tag.

    Uses ensure_ascii=False to preserve unicode (player names, ≤ symbols etc.)
    then escapes the small set of characters that are valid in JSON strings
    but dangerous inside a <script> block:

      \u2028 / \u2029  — Unicode line/paragraph separators; treated as line
                          terminators by JS engines even inside string literals
      </script>         — browser HTML parser ends the script block early
      <!--              — starts an HTML comment, can confuse some parsers

    Note: json.dumps already escapes \n, \r, and \0 inside string values,
    so those don't need special handling here.
    """
    raw = json.dumps(data, ensure_ascii=False, indent=2)
    return (
        raw
        .replace("\u2028", "\\u2028")   # Unicode line separator
        .replace("\u2029", "\\u2029")   # Unicode paragraph separator
        .replace("</",      "<\\/")      # breaks </script> -> <\/script>
        .replace("<!--",    "\\u003c!--") # breaks HTML comment opener
    )


def _find_dir(name: str) -> Path:
    """Search for a directory (e.g. 'templates', 'static') near the script.
    Searches: script dir, one level up (repo root), src/ sibling."""
    for candidate in [_here / name, _here.parent / name,
                      _here.parent / "src" / name]:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        f"Could not find '{name}/' — searched: {_here}, {_here.parent}, "
        f"{_here.parent / 'src'}"
    )


def make_jinja_env() -> jinja2.Environment:
    templates_dir = _find_dir("templates")
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(templates_dir)),
        autoescape=jinja2.select_autoescape(["html"]),
    )


# ─────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────

def list_events():
    print("Fetching current PDGA events...\n")
    events = fetch_current_events()
    if not events:
        print("No events found.")
        return
    print(f"{'TournID':<10} {'Tier':<6} {'Start':<12} {'End':<12} Name")
    print("─" * 80)
    for e in events:
        print(
            f"{str(e.get('tournId', '?')):<10} "
            f"{str(e.get('tier', '?')):<6} "
            f"{str(e.get('startDate', '?')):<12} "
            f"{str(e.get('endDate', '?')):<12} "
            f"{e.get('officialName', '?')}"
        )


def _load_cache(tourn_id: str) -> dict | None:
    """
    Try to read scores from the app's SQLite cache (scoreboard_cache.db).
    Returns the cached scores dict, or None if not found.
    """
    import sqlite3, json as _json
    for candidate in [_here.parent / "scoreboard_cache.db",
                      _here / "scoreboard_cache.db"]:
        if candidate.exists():
            try:
                conn = sqlite3.connect(candidate)
                row  = conn.execute(
                    "SELECT scores_json FROM tournament_cache WHERE tourn_id = ?",
                    (str(tourn_id),)
                ).fetchone()
                conn.close()
                if row:
                    print(f"  Found cached data in {candidate}")
                    return _json.loads(row[0])
            except Exception as e:
                print(f"  Cache read failed ({candidate}): {e}")
    return None


def build(tourn_id: str, out_path: Path, gh_repo: str):
    # Try the local SQLite cache first — avoids hitting PDGA directly
    # (which often returns 403 outside of a browser session).
    scores = _load_cache(tourn_id)

    if scores:
        print(f"Fetching scores for TournID={tourn_id}... (from cache)")
    else:
        print(f"Fetching scores for TournID={tourn_id}... (from PDGA)")
        scores = _build_scores(tourn_id)

    build_html(scores, out_path, gh_repo)
    print(f"  Event    : {scores['event_name']}")

    # Copy static assets alongside the output
    static_dir = _find_dir("static")
    for asset in ["theme.css", "scoreboard.js"]:
        src = static_dir / asset
        dst = out_path / asset
        if src.exists():
            shutil.copy(src, dst)
            print(f"  Copied   : {asset} -> {dst}")
        else:
            print(f"  Warning  : {asset} not found in {static_dir}")


def build_html(scores: dict, out_path: Path, gh_repo: str):
    """Render a static landing page pre-populated with the tournament and divisions."""
    divisions = scores.get("divisions", [])
    if not divisions:
        print("Warning: no division data returned. The page will be blank.")

    snapshot_date = datetime.now().strftime("%B %-d, %Y %-I:%M %p")

    env      = make_jinja_env()
    template = env.get_template("scoreboard-static.html")
    html     = template.render(
        event_name    = scores["event_name"],
        event_round   = scores.get("event_round", ""),
        last_updated  = scores.get("last_updated", snapshot_date),
        snapshot_date = snapshot_date,
        gh_repo       = gh_repo,
    )
    # Inject scores via plain string replace so JSON never touches
    # Jinja2's autoescape or whitespace pipeline.
    html = html.replace("__SCORES_JSON__", _json_for_script(scores))

    scoreboard_path = out_path / "scoreboard.html"
    scoreboard_path.write_text(html, encoding="utf-8")
    print(f"Written to {scoreboard_path}  ({scoreboard_path.stat().st_size // 1024} KB)")

    event_info = {
        "tournId":       scores["tourn_id"],
        "officialName":  scores["event_name"],
        "tier":          "?",
        "city":          "",
        "stateProvince": "",
        "countryISO":    "",
        "startDate":     "",
        "endDate":       scores.get("end_date", ""),
    }
    divs = [{"code": d["code"], "name": d["name"]} for d in scores.get("divisions", [])]

    env      = make_jinja_env()
    template = env.get_template("landing-static.html")
    html     = template.render(event_name=scores["event_name"], gh_repo=gh_repo)
    html     = html.replace("__EVENT_JSON__", _json_for_script(event_info))
    html     = html.replace("__DIVS_JSON__",  _json_for_script(divs))

    landing_path = out_path / "landing.html"
    landing_path.write_text(html, encoding="utf-8")
    print(f"Written to {landing_path}  ({landing_path.stat().st_size // 1024} KB)")


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Build a static GitHub Pages scoreboard snapshot."
    )
    parser.add_argument("--tourn-id", "-t", help="PDGA tournament ID to snapshot")
    parser.add_argument("--repo", "-r", default="your-username/disc-golf-event-buddy",
                        help="GitHub repo slug shown in the footer")
    parser.add_argument("--list-events", "-l", action="store_true",
                        help="Print current PDGA events and exit")
    args = parser.parse_args()

    if args.list_events:
        list_events()
        return

    if not args.tourn_id:
        parser.error("--tourn-id is required (or use --list-events to find one)")

    build(tourn_id=args.tourn_id, out_path=Path("docs/"), gh_repo=args.repo)


if __name__ == "__main__":
    main()