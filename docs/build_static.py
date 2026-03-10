#!/usr/bin/env python3
"""
build_static.py — Generate a self-contained static scoreboard for GitHub Pages.

Usage:
    python build_static.py --tourn-id 12345
    python build_static.py --tourn-id 12345 --out docs/index.html --repo user/repo
    python build_static.py --list-events          # print current PDGA events and exit

What it does:
    1. Fetches live score data from PDGA for the given tournament ID.
    2. Renders templates/scoreboard_static.html (a Jinja2 child of scoreboard.html)
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
import shutil
import sys
from datetime import datetime
from pathlib import Path

import jinja2

# Reuse the existing scraper helpers so score formatting stays consistent.
# Run this script from the project root (pdga_scoreboard/) directory.
try:
    from scraper import _build_scores, fetch_current_events
except ImportError:
    print("Error: run this script from the pdga_scoreboard/ project directory.")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────
# Jinja2 environment — points at the existing templates/ folder
# ─────────────────────────────────────────────────────────────

def make_jinja_env() -> jinja2.Environment:
    templates_dir = Path(__file__).parent / "templates"
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


def build(tourn_id: str, out_path: Path, gh_repo: str):
    print(f"Fetching scores for TournID={tourn_id}...")
    scores = _build_scores(tourn_id)

    divisions = scores.get("divisions", [])
    if not divisions:
        print("Warning: no division data returned. The page will be blank.")

    snapshot_date = datetime.now().strftime("%B %-d, %Y %-I:%M %p")

    env      = make_jinja_env()
    template = env.get_template("scoreboard_static.html")
    html     = template.render(
        event_name    = scores["event_name"],
        event_round   = scores.get("event_round", ""),
        last_updated  = scores.get("last_updated", snapshot_date),
        snapshot_date = snapshot_date,
        gh_repo       = gh_repo,
        scores_json   = json.dumps(scores, ensure_ascii=False, indent=2),
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"Written to {out_path}  ({out_path.stat().st_size // 1024} KB)")
    print(f"  Event    : {scores['event_name']}")
    print(f"  Round    : {scores.get('event_round', '—')}")
    print(f"  Divisions: {len(divisions)}")
    print(f"  Players  : {sum(len(d['players']) for d in divisions)}")

    # Copy theme.css alongside the output so the page can load it
    theme_src = Path(__file__).parent / "static" / "theme.css"
    theme_dst = out_path.parent / "theme.css"
    if theme_src.exists():
        shutil.copy(theme_src, theme_dst)
        print(f"  Copied   : theme.css -> {theme_dst}")
    else:
        print("  Warning  : static/theme.css not found — page styling will be missing")


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Build a static GitHub Pages scoreboard snapshot."
    )
    parser.add_argument("--tourn-id", "-t", help="PDGA tournament ID to snapshot")
    parser.add_argument("--out", "-o", default="docs/index.html",
                        help="Output path (default: docs/index.html)")
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

    build(tourn_id=args.tourn_id, out_path=Path(args.out), gh_repo=args.repo)


if __name__ == "__main__":
    main()
