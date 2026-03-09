# disc-golf-event-buddy

A live scoreboard display for disc golf events. Pulls real-time scores from the PDGA live scoring API and displays them as a smooth, auto-scrolling TV scoreboard. Includes a landing page for selecting tournaments and configuring display settings.

---

## Features

- **Live scores** pulled directly from the PDGA live scoring API, refreshed on a configurable interval
- **Landing page** with searchable/filterable list of current PDGA events
- **TV scoreboard** — fullscreen, auto-scrolling display with seamless loop
- **Per-division display** with place, player name, country, total score, round score, and holes completed
- **Dark / light mode** toggle, persisted across sessions
- **Configurable settings** — scroll speed, poll interval, and division filter stored as cookies
- **SQLite cache** — scores persist to disk so reloading the scoreboard is instant even after a server restart
- **Bookmarkable URLs** — scoreboard URL includes `?tournId=` so you can link directly to an event

---

## Quickstart

**1. Install dependencies**

```bash
pip install -r requirements.txt
```

**2. Run the server**

```bash
python app.py
```

**3. Open the app**

```
http://localhost:5000
```

Select your tournament, configure settings, and click **Launch Scoreboard**. On the TV machine, press `F11` for fullscreen.

---

## API Reference

The server exposes a small REST API that mirrors PDGA's own naming conventions.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/events` | Proxies PDGA's current-events list |
| `GET` | `/api/event/<tournId>` | Proxies PDGA event metadata (divisions, rounds, layouts) |
| `POST` | `/api/select` | Sets the active tournament `{ "tournId": "12345" }` |
| `GET` | `/api/scores` | Latest cached scores for the active tournament |
| `GET` | `/api/cache` | Lists all cached tournaments and their age (debug) |
| `DELETE` | `/api/cache/<tournId>` | Evicts a tournament from the cache, forcing a fresh fetch |

---

## PDGA API Endpoints Used

```
GET https://www.pdga.com/api/v1/feat/current-events/tournaments
GET https://www.pdga.com/apps/tournament/live-api/live_results_fetch_event?TournID=<id>
GET https://www.pdga.com/apps/tournament/live-api/live_results_fetch_round?TournID=<id>&Division=<div>&Round=<n>
```

These are undocumented internal endpoints used by the PDGA live scoring web app. They are not an official public API and may change without notice.

---

## Settings

All settings are saved as cookies and persist across page loads.

| Setting | Description | Default |
|---------|-------------|---------|
| Dark / Light mode | Scoreboard and landing page theme | Dark |
| Scroll speed | Pixels per second for the auto-scroll | 60 |
| Poll interval | How often the scoreboard re-fetches scores | 30s |
| Division filter | Which divisions to show on the scoreboard | All |

---

## Caching

Scores are persisted to a local SQLite database (`scoreboard_cache.db`) after every successful PDGA fetch. When a tournament is selected, the cached data is served immediately while a fresh fetch runs in the background — so the scoreboard is never blank on reload.

To force a cold fetch for a specific tournament:

```bash
curl -X DELETE http://localhost:5000/api/cache/<tournId>
```

---

## Requirements

- Python 3.10+
- Network access to `pdga.com`
- A browser on the display machine (Chrome or Firefox recommended for fullscreen)
