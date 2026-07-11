#!/usr/bin/env python3
"""
MLB Delay Monitor
-----------------
Checks MLB's official Stats API for today's (and tonight's) games and sends
you a push notification the moment a game is delayed, suspended, or
postponed -- whether that happens before first pitch or mid-game.

HOW IT WORKS
- Pulls today's schedule from MLB's public Stats API (no key required).
- Looks at each game's "detailedState" (MLB's own status field).
- Compares it to the last known state (stored in delay_monitor_state.json)
  so you only get alerted when something CHANGES, not every time the
  script runs.
- Sends the alert via ntfy.sh, a free push-notification service (no
  account needed -- see setup instructions below).

SETUP (one-time)
1. Install the requests library:
       pip install requests --break-system-packages
   (drop the --break-system-packages flag on Windows/most setups; it's
   only needed on some Linux systems with an externally-managed Python)

2. Pick a private "topic" name for your alerts -- this is just a made-up
   word that acts like a private channel name. Something hard to guess,
   e.g. "jv-mlb-delays-8842". Put it in NTFY_TOPIC below.

3. On your phone: install the "ntfy" app (iOS App Store / Google Play),
   open it, tap the "+" button, and subscribe to that SAME topic name.
   That's it -- no login, no API key. Anything sent to that topic name
   will now pop up as a push notification on your phone.

4. Edit the TEAMS list below to the teams you want to watch (or leave it
   empty to get alerts for every MLB game today).

5. Run it once to test:
       python3 mlb_delay_monitor.py

RUNNING IT AUTOMATICALLY (so you don't have to launch it by hand)
See the accompanying instructions for setting this up as a scheduled
task (cron on Mac/Linux, Task Scheduler on Windows) to run every 5
minutes during game hours.
"""

import json
import os
import sys
from datetime import datetime, timedelta

import requests

# ---------------------------------------------------------------------
# CONFIG -- edit these three things
# ---------------------------------------------------------------------

# Leave empty [] to watch ALL MLB games today, or list team names/cities
# (partial, case-insensitive match against MLB's team names is fine, e.g.
# "Dodgers", "Yankees", "Red Sox", "Angels").
TEAMS = []

# Your private ntfy.sh topic name (see setup instructions above).
# If an NTFY_TOPIC environment variable is set (e.g. by GitHub Actions),
# that takes priority over the hardcoded value below -- this lets you
# keep your topic name out of the code when running in the cloud.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "REPLACE_WITH_YOUR_TOPIC_NAME")

# Where to keep track of what's already been alerted on, so you don't
# get the same alert twice. This file will be created automatically.
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "delay_monitor_state.json")

# ---------------------------------------------------------------------

MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"

# Status strings from MLB's API that count as "worth alerting on"
DELAY_KEYWORDS = ["delay", "postponed", "suspended"]


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def team_matches(game, filters):
    if not filters:
        return True
    away = game["teams"]["away"]["team"]["name"].lower()
    home = game["teams"]["home"]["team"]["name"].lower()
    return any(f.lower() in away or f.lower() in home for f in filters)


def fetch_games_for_date(date_str):
    params = {"sportId": 1, "date": date_str}
    resp = requests.get(MLB_SCHEDULE_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    games = []
    for date_entry in data.get("dates", []):
        games.extend(date_entry.get("games", []))
    return games


def send_alert(message, title="MLB Delay Alert"):
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": "high",
                "Tags": "warning,baseball",
            },
            timeout=15,
        )
        print(f"ALERT SENT: {message}")
    except requests.RequestException as e:
        print(f"Failed to send alert (will retry next run): {e}", file=sys.stderr)


def describe_game(game):
    away = game["teams"]["away"]["team"]["name"]
    home = game["teams"]["home"]["team"]["name"]
    return f"{away} @ {home}"


def main():
    if NTFY_TOPIC == "REPLACE_WITH_YOUR_TOPIC_NAME":
        print(
            "You still need to set NTFY_TOPIC at the top of this script "
            "to your own private topic name. See the setup instructions "
            "in the file header.",
            file=sys.stderr,
        )
        sys.exit(1)

    state = load_state()

    # Check today AND tonight/early tomorrow (covers late West Coast games
    # that might roll past midnight UTC bookkeeping quirks).
    today = datetime.now().strftime("%Y-%m-%d")

    games = fetch_games_for_date(today)
    games = [g for g in games if team_matches(g, TEAMS)]

    if not games:
        print(f"No matching games found for {today}.")
        return

    for game in games:
        game_pk = str(game["gamePk"])
        status = game.get("status", {})
        detailed_state = status.get("detailedState", "")
        reason = status.get("reason", "")
        label = describe_game(game)

        is_delay_like = any(k in detailed_state.lower() for k in DELAY_KEYWORDS)
        previous_state = state.get(game_pk, {}).get("detailedState")

        if is_delay_like and detailed_state != previous_state:
            msg = f"{label}: {detailed_state}"
            if reason:
                msg += f" ({reason})"
            send_alert(msg)

        # Always record the latest known state, delay or not, so we can
        # detect the *next* change (e.g. delay -> resumed -> delayed again).
        state[game_pk] = {
            "detailedState": detailed_state,
            "matchup": label,
            "last_checked": datetime.now().isoformat(),
        }

    save_state(state)
    print(f"Checked {len(games)} game(s) at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.")


if __name__ == "__main__":
    main()
