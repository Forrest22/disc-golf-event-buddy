"""
app.py — Flask Scoreboard Server

Routes:
  GET  /                          → landing page (tournament picker + settings)
  GET  /scoreboard                → live scoreboard display

  GET  /api/events                → proxy: PDGA current events list
  GET  /api/event/<tourn_id>      → proxy: PDGA event metadata + divisions
  POST /api/select                → set active tournament (body: {"tournId": "12345"})
  GET  /api/scores                → latest scores for the active tournament

Run with:
  pip install flask requests beautifulsoup4
  python app.py

Then open http://localhost:5000 in the browser.
On the TV, press F11 for fullscreen after launching the scoreboard.
"""

from flask import Flask, jsonify, render_template, request, redirect, url_for
from src.scraper import (
    fetch_current_events,
    fetch_event_info,
    get_active_scores,
    set_active_tournament,
    start_scraper,
)
from src.cache import list_cached, delete_cache

app = Flask(__name__)


# ─────────────────────────────────────────────────────────────
# Page routes
# ─────────────────────────────────────────────────────────────

@app.route("/")
def landing():
    """Landing page — tournament picker and settings."""
    return render_template("landing.html")


@app.route("/scoreboard")
def scoreboard():
    """
    Live scrolling scoreboard — meant to be run fullscreen on a TV.
    Reads ?tournId=<id> from the query string and activates that tournament.
    If no tournId is provided, redirects back to the landing page.
    """
    tourn_id = request.args.get("tournId", "").strip()
    if not tourn_id:
        return redirect(url_for("landing"))
    set_active_tournament(tourn_id)
    return render_template("scoreboard.html", tourn_id=tourn_id)


# ─────────────────────────────────────────────────────────────
# API routes (mirroring PDGA's naming convention)
# ─────────────────────────────────────────────────────────────

@app.route("/api/events")
def api_events():
    """
    GET /api/events
    Proxy for PDGA's current-events endpoint.
    Returns the raw list of current/recent tournaments.
    """
    try:
        events = fetch_current_events()
        return jsonify({"data": events})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/event/<tourn_id>")
def api_event(tourn_id):
    """
    GET /api/event/<tourn_id>
    Proxy for PDGA's live_results_fetch_event endpoint.
    Returns event metadata: name, rounds, divisions, layouts.
    """
    try:
        data = fetch_event_info(tourn_id)
        return jsonify({"data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/select", methods=["POST"])
def api_select():
    """
    POST /api/select  { "tournId": "12345" }
    Sets the active tournament for the scraper and returns the scoreboard URL
    with tournId as a query param. The frontend navigates to that URL.
    """
    body = request.get_json(silent=True) or {}
    tourn_id = str(body.get("tournId", "")).strip()
    if not tourn_id:
        return jsonify({"error": "tournId is required"}), 400
    set_active_tournament(tourn_id)
    scoreboard_url = url_for("scoreboard", tournId=tourn_id)
    return jsonify({"ok": True, "tournId": tourn_id, "url": scoreboard_url})


@app.route("/api/scores")
def api_scores():
    """
    GET /api/scores
    Returns the latest cached scores for the active tournament.
    The scoreboard polls this every N seconds (controlled by cookie setting).
    """
    return jsonify(get_active_scores())


# ─────────────────────────────────────────────────────────────
# Cache management routes
# ─────────────────────────────────────────────────────────────

@app.route("/api/cache")
def api_cache():
    """
    GET /api/cache
    Returns a list of all cached tournaments and their age.
    Useful for debugging — not linked from the UI.
    """
    return jsonify({"data": list_cached()})


@app.route("/api/cache/<tourn_id>", methods=["DELETE"])
def api_cache_delete(tourn_id):
    """
    DELETE /api/cache/<tourn_id>
    Evicts a specific tournament from the cache, forcing a fresh PDGA fetch.
    """
    deleted = delete_cache(tourn_id)
    return jsonify({"ok": deleted, "tournId": tourn_id})


# ─────────────────────────────────────────────────────────────
# Startup
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    start_scraper(poll_interval=30)
    print("[server] Scoreboard running at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
