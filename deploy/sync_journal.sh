#!/usr/bin/env bash
# Sauvegarde le journal (dossier jr, branche journal) sur GitHub. Sans effet s'il n'y a rien de nouveau.
cd "$(dirname "$0")/../jr" || exit 0
git add -A
git -c user.name="alpaca-bot" -c user.email="alpaca-bot@users.noreply.github.com" \
  commit -qm "journal $(date -u +%F_%H%M)" || exit 0
git push -q origin journal || true
