#!/usr/bin/env bash
# Build the plugin DLL and package as a Jellyfin-installable ZIP.
#
# Output: dist/Jellyfin.Plugin.SeerrLoadingScreen-<version>.zip
#         dist/meta.json (for hosting in a manifest)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VERSION="0.2.2"
DIST_DIR="$SCRIPT_DIR/dist"
PKG_NAME="Jellyfin.Plugin.SeerrLoadingScreen"
ZIP_NAME="${PKG_NAME}-${VERSION}.zip"

mkdir -p "$DIST_DIR"

dotnet restore
dotnet build -c Release -p:Version="${VERSION}" -p:AssemblyVersion="${VERSION}.0"

DLL="bin/Release/net9.0/${PKG_NAME}.dll"
if [[ ! -f "$DLL" ]]; then
    echo "build artifact missing: $DLL" >&2
    exit 1
fi

(cd "bin/Release/net9.0" && python3 -m zipfile -c "$DIST_DIR/$ZIP_NAME" "${PKG_NAME}.dll")

# Compute checksum (Jellyfin manifest requires md5)
CHECKSUM=$(md5sum "$DIST_DIR/$ZIP_NAME" | awk '{print $1}')

cat > "$DIST_DIR/meta.json" <<JSON
{
  "category": "Metadata",
  "guid": "4f2c0e3a-9b4d-4f7c-9a31-2d6e8f1b5c0a",
  "name": "Seerr Loading Screen",
  "description": "Show Sonarr/Radarr pending downloads as Jellyfin library items with live progress.",
  "owner": "Petr1t",
  "overview": "Surfaces Jellyseerr-requested media via Sonarr/Radarr queue as virtual Jellyfin library items with live progress overlay.",
  "targetAbi": "10.11.0.0",
  "version": "${VERSION}.0",
  "changelog": "v${VERSION}: robustness pass — Channel listing now bounded by a 5s timeout against a hung daemon, smarter cache-key (state-hash, not timestamp) so refreshes only happen when items change. Daemon refactored: shared httpx client, ~200 LOC reduction. Verified end-to-end on Jellyfin 10.11.8.",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%S.0000000Z)",
  "checksum": "${CHECKSUM}",
  "sourceUrl": "https://github.com/Petr1t/jellyfin_seerr_loading_screen/releases/download/v${VERSION}/${ZIP_NAME}"
}
JSON

echo ""
echo "Built ${ZIP_NAME} (md5: ${CHECKSUM})"
echo "Outputs in $DIST_DIR/"
