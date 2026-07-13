name: MLB Transactions Monitor

on:
  schedule:
    # Every 10 minutes. Transactions are posted less urgently than
    # in-game delays, so this doesn't need to be as tight as the
    # delay monitor's schedule.
    - cron: "*/10 * * * *"
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  check-transactions:
    runs-on: ubuntu-latest
    steps:
      - name: Get the code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install requirements
        run: pip install requests

      - name: Run the transactions check
        env:
          NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
        run: python3 mlb_transactions_monitor.py

      - name: Save updated memory file back to the repository
        run: |
          git config user.name "mlb-transactions-monitor-bot"
          git config user.email "actions@users.noreply.github.com"
          git add transactions_state.json
          git diff --quiet --cached || git commit -m "Update transactions monitor state"
          git push
