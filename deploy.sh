#!/bin/sh
# Ship the committed code to the live Invoice Tracker on the Sotto VPS (see CLAUDE.md).
set -e
cd "$(dirname "$0")"
git diff --quiet HEAD || { echo "Commit your changes first: only committed code is deployed."; exit 1; }
git archive --format=tar HEAD | ssh subtag 'cd /opt/invoice-tracker && tar xf - && venv/bin/pip install -q -r requirements.txt'
ssh subtag 'sudo -n systemctl restart invoice-tracker && sleep 8 && curl -s -m 20 http://127.0.0.1:8095/health'
echo
