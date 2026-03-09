"""
app.py — Flask Scoreboard Server

Run with:
    pip install -r requirements.txt
    python app.py

Then open http://localhost:5000 on the TV browser (fullscreen with F11).
"""

from flask import Flask, jsonify, render_template
from scraper import scores_data, scores_lock, start_scraper

app = Flask(__name__)


@app.route("/")
def index():
    """Renders the top level scoreboard, with automatic scrolling"""
    return render_template("scoreboard.html")


@app.route("/scores")
def scores():
    """Endpoint to get the jsonified scores from"""
    with scores_lock:
        return jsonify(scores_data)


if __name__ == "__main__":
    start_scraper()  # kick off background polling thread
    print("[server] Scoreboard running at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
