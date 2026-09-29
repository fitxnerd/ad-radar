#!/bin/bash
# Fallback: run Ad Radar from your own Mac every Monday 08:00 (if Meta ever blocks
# GitHub's servers). Your Mac must be awake. Uses your logged-in Claude Code.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.adradar.weekly.plist"
python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
read -r -p "Gmail address to send from: " SMTP_USER
read -r -s -p "Gmail app password (16 chars): " SMTP_PASSWORD; echo
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.adradar.weekly</string>
  <key>ProgramArguments</key><array>
    <string>$DIR/.venv/bin/python</string><string>$DIR/run.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>SMTP_USER</key><string>$SMTP_USER</string>
    <key>SMTP_PASSWORD</key><string>$SMTP_PASSWORD</string></dict>
  <key>StartCalendarInterval</key><dict>
    <key>Weekday</key><integer>1</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$DIR/radar.log</string>
  <key>StandardErrorPath</key><string>$DIR/radar.log</string>
</dict></plist>
PL
chmod 600 "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Scheduled: Mondays 08:00. Log: $DIR/radar.log. Remove with: launchctl unload $PLIST && rm $PLIST"
