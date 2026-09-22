#!/usr/bin/env bash
set -euo pipefail
openclaw config validate
openclaw agents list
for a in opsswarm-incident-manager opsswarm-observability-investigator opsswarm-application-investigator opsswarm-infrastructure-investigator opsswarm-database-investigator opsswarm-recovery-responder opsswarm-communications-postmortem; do
  echo "Checking $a"
  openclaw agent --agent "$a" --message "Return only OK" --json >/dev/null
done
