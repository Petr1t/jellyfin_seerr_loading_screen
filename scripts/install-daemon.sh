#!/usr/bin/env bash
# Interactive installer for the jslsd daemon (user-systemd).
#
# Installs to ~/.local/share/jslsd/, writes ~/.config/jslsd/config.yaml,
# enables and starts jslsd.service as a user-systemd unit.

set -euo pipefail

# Colour helpers
G="\033[1;32m"; Y="\033[1;33m"; R="\033[1;31m"; N="\033[0m"
ok()   { echo -e "${G}✓${N} $*"; }
warn() { echo -e "${Y}!${N} $*"; }
err()  { echo -e "${R}✗${N} $*" >&2; }

# Locations
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${HOME}/.local/share/jslsd"
CONFIG_DIR="${HOME}/.config/jslsd"
CACHE_DIR="${HOME}/.cache/jslsd/posters"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

# 1. Sanity checks
if ! command -v python3 >/dev/null; then
    err "python3 not found. Install Python 3.11+."
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if [[ "$PY_MAJOR" -lt 3 || ( "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 11 ) ]]; then
    err "Python ${PY_VERSION} found; need 3.11+."
    exit 1
fi
ok "Python ${PY_VERSION} OK"

# 2. Prompt for config
echo ""
echo "We'll need your Sonarr and/or Radarr API keys."
echo "Find them at: <Sonarr/Radarr> → Settings → General → Security → API Key."
echo ""

read -rp "Sonarr URL (e.g. http://localhost:8989) [skip if none]: " SONARR_URL
SONARR_URL="${SONARR_URL:-}"
if [[ -n "$SONARR_URL" ]]; then
    read -rp "Sonarr API Key: " SONARR_KEY
fi

read -rp "Radarr URL (e.g. http://localhost:7878) [skip if none]: " RADARR_URL
RADARR_URL="${RADARR_URL:-}"
if [[ -n "$RADARR_URL" ]]; then
    read -rp "Radarr API Key: " RADARR_KEY
fi

if [[ -z "$SONARR_URL" && -z "$RADARR_URL" ]]; then
    err "Need at least one of Sonarr/Radarr."
    exit 2
fi

read -rp "Jellyseerr URL [skip if none]: " SEERR_URL
SEERR_URL="${SEERR_URL:-}"
if [[ -n "$SEERR_URL" ]]; then
    read -rp "Jellyseerr API Key: " SEERR_KEY
fi

read -rp "Daemon listening port [7000]: " PORT
PORT="${PORT:-7000}"

# 3. Install
echo ""
ok "Creating venv at $INSTALL_DIR/.venv"
mkdir -p "$INSTALL_DIR"
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install --quiet "$SRC_DIR/jslsd"

ok "Creating config at $CONFIG_DIR/config.yaml"
mkdir -p "$CONFIG_DIR" "$CACHE_DIR"

cat > "$CONFIG_DIR/config.yaml" <<EOF
# jslsd config — auto-generated $(date -Iseconds)

EOF

if [[ -n "$SONARR_URL" ]]; then
    cat >> "$CONFIG_DIR/config.yaml" <<EOF
sonarr:
  url: "$SONARR_URL"
  api_key: "$SONARR_KEY"

EOF
fi

if [[ -n "$RADARR_URL" ]]; then
    cat >> "$CONFIG_DIR/config.yaml" <<EOF
radarr:
  url: "$RADARR_URL"
  api_key: "$RADARR_KEY"

EOF
fi

if [[ -n "$SEERR_URL" ]]; then
    cat >> "$CONFIG_DIR/config.yaml" <<EOF
jellyseerr:
  url: "$SEERR_URL"
  api_key: "$SEERR_KEY"

EOF
fi

cat >> "$CONFIG_DIR/config.yaml" <<EOF
poll_interval_seconds: 30
poster_cache_dir: $CACHE_DIR
poster_size: [400, 600]
api_listen_host: "0.0.0.0"
api_listen_port: $PORT
EOF

chmod 600 "$CONFIG_DIR/config.yaml"
ok "Config written (chmod 600)"

# 4. systemd user unit
ok "Installing systemd user unit"
mkdir -p "$SYSTEMD_USER_DIR"
cp "$SRC_DIR/scripts/jslsd.service" "$SYSTEMD_USER_DIR/jslsd.service"

systemctl --user daemon-reload
systemctl --user enable --now jslsd.service

# 5. Enable user-services-on-boot
loginctl enable-linger "$USER" 2>/dev/null || warn "Could not enable lingering — daemon may not survive logout. Run: sudo loginctl enable-linger $USER"

# 6. Verify
sleep 2
if systemctl --user is-active --quiet jslsd.service; then
    ok "jslsd.service is running"
    echo ""
    echo "  Test: curl http://localhost:$PORT/healthz"
    echo "  Logs: journalctl --user -u jslsd.service -f"
    echo ""
else
    err "jslsd.service failed to start. Check: journalctl --user -u jslsd.service -n 50"
    exit 3
fi
