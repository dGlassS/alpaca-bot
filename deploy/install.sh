#!/usr/bin/env bash
# Installe ou met à jour le bot sur un serveur Ubuntu. À lancer avec : sudo bash install.sh
set -euo pipefail
REPO="${REPO:-https://github.com/dGlassS/alpaca-bot.git}"
DIR=/opt/alpaca-bot

apt-get update -qq
apt-get install -y -qq git python3-venv tzdata
id alpacabot >/dev/null 2>&1 || useradd --system --home "$DIR" --shell /usr/sbin/nologin alpacabot
git config --global --add safe.directory "$DIR"

if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  git clone "$REPO" "$DIR"
fi
python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
mkdir -p "$DIR/logs"
chown -R alpacabot:alpacabot "$DIR"

if [ ! -f /etc/alpaca-bot.env ]; then
  echo "Colle tes clés Alpaca PAPER (elles ne s'affichent pas quand tu les colles) :"
  read -rsp "API Key ID : " KEY; echo
  read -rsp "Secret Key : " SECRET; echo
  umask 077
  printf 'ALPACA_API_KEY=%s\nALPACA_SECRET_KEY=%s\n' "$KEY" "$SECRET" > /etc/alpaca-bot.env
  chmod 600 /etc/alpaca-bot.env
fi

cp "$DIR/deploy/alpaca-bot.service" /etc/systemd/system/alpaca-bot.service
systemctl daemon-reload
systemctl enable --now alpaca-bot
systemctl restart alpaca-bot
sleep 5
systemctl --no-pager status alpaca-bot | head -5
echo "OK. Journal en direct : sudo journalctl -u alpaca-bot -f"
