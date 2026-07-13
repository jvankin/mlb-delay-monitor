#!/usr/bin/env python3
"""
MLB Transactions Monitor
-------------------------
Checks MLB's official Stats API for new player transactions -- trades,
free agent signings, releases, injured list moves, callups/optionings,
designations for assignment, and more -- for teams you choose, and
sends you a push notification the moment a new one is posted.

HOW IT WORKS
- Looks up the team ID(s) for the team names you list below (so you can
  just type "Dodgers" instead of hunting down a number).
- Pulls the last few days of transactions for those teams from MLB's
  public Stats API.
- Compares each transaction's unique ID against what it's already seen
  (stored in transactions_state.json) so you're only alerted on NEW
  transactions, never repeats.
- Sends the alert via ntfy.sh (same setup as the delay monitor -- reuses
  the same NTFY_TOPIC).

SETUP
Same as the delay monitor: requests library installed, NTFY_TOPIC set
(either hardcoded below or via environment variable for cloud use).
Just edit the TEAMS list below to the teams you want to follow.
"""

import json
import os
import sys
from datetime import datetime, timedelta

import requests

# ---------------------------------------------------------------------
# CONFIG -- edit this
# ---------------------------------------------------------------------

# Team names to follow. Partial, case-insensitive matches are fine --
# "Dodgers", "Yankees", "Red Sox", "Angels", etc. Leave empty [] to
# follow every MLB team (this will be noisy -- dozens of moves a day
# league-wide, especially near the trade deadline).
TEAMS = ["Dodgers", "Red Sox", "Yankees", "Tigers", "Phillies", "Astros", "Cubs", "Mets", "Braves"]

# Your private ntfy.sh topic name -- same one used for the delay
# monitor, unless you want transaction alerts on a separate topic.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "REPLACE_WITH_YOUR_TOPIC_NAME")

# How many days back to check each run. A small window (e.g. 3) plus
# frequent runs (every 10-15 min) is enough to catch everything without
# re-scanning MLB's whole season each time.
LOOKBACK_DAYS = 3

STATE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "transactions_state.json"
)

# ---------------------------------------------------------------------

TEAMS_URL = "https://statsapi.mlb.com/api/v1/teams"
TRANSACTIONS_URL = "https://statsapi.mlb.com/api/v1/transactions"


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"seen_transaction_ids": []}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def resolve_team_ids(team_names):
    if not team_names:
        return []  # empty means "all teams" -- transactions endpoint allows no teamId filter
    resp = requests.get(TEAMS_URL, params={"sportId": 1}, timeout=15)
    resp.raise_for_status()
    all_teams = resp.json().get("teams", [])

    resolved = []
    for name in team_names:
        match = next(
            (t for t in all_teams if name.lower() in t.get("name", "").lower()),
            None,
        )
        if match:
            resolved.append((match["id"], match["name"]))
        else:
            print(f"WARNING: couldn't find a team matching '{name}'", file=sys.stderr)
    return resolved


def fetch_transactions(team_id=None, start_date=None, end_date=None):
    params = {"startDate": start_date, "endDate": end_date}
    if team_id:
        params["teamId"] = team_id
    resp = requests.get(TRANSACTIONS_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("transactions", [])


def send_alert(message, title="MLB Transaction Alert"):
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": "default",
                "Tags": "baseball,arrows_counterclockwise",
            },
            timeout=15,
        )
        print(f"ALERT SENT: {message}")
    except requests.RequestException as e:
        print(f"Failed to send alert (will retry next run): {e}", file=sys.stderr)


def main():
    if NTFY_TOPIC == "REPLACE_WITH_YOUR_TOPIC_NAME":
        print(
            "You still need to set NTFY_TOPIC (either edit the script or set "
            "the environment variable). See the setup instructions in the "
            "file header.",
            file=sys.stderr,
        )
        sys.exit(1)

    state = load_state()
    seen_ids = set(state.get("seen_transaction_ids", []))

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    team_matches = resolve_team_ids(TEAMS)
    if TEAMS and not team_matches:
        print("No teams resolved from TEAMS list -- check spelling.", file=sys.stderr)
        return

    all_transactions = []
    if team_matches:
        for team_id, team_name in team_matches:
            txns = fetch_transactions(team_id=team_id, start_date=start_date, end_date=end_date)
            all_transactions.extend(txns)
    else:
        all_transactions = fetch_transactions(start_date=start_date, end_date=end_date)

    new_count = 0
    for txn in all_transactions:
        txn_id = str(txn.get("id"))
        if not txn_id or txn_id in seen_ids:
            continue

        seen_ids.add(txn_id)
        new_count += 1

        person = txn.get("person", {}).get("fullName", "Unknown player")
        description = txn.get("description", txn.get("typeDesc", "Transaction"))
        team_name = txn.get("toTeam", {}).get("name") or txn.get("fromTeam", {}).get("name", "")

        msg = f"{person} ({team_name}): {description}" if team_name else f"{person}: {description}"
        send_alert(msg)

    # Keep the seen-IDs list from growing forever -- trim to the most
    # recent 2000 entries, which is far more than a few days' worth.
    state["seen_transaction_ids"] = list(seen_ids)[-2000:]
    save_state(state)

    print(f"Checked {len(all_transactions)} transaction(s), {new_count} new, at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.")


if __name__ == "__main__":
    main()
