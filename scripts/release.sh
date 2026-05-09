#!/usr/bin/env bash
# Release pipeline: build the plugin ZIP, compute checksum, update manifest.json
# in-place with the new version entry, create a git tag, push, and create a
# GitHub release with the ZIP attached.
#
# Usage:  ./scripts/release.sh 0.2.0
#
# Requires: dotnet 9, gh CLI authenticated, jq.

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <version>" >&2
    exit 2
fi

VERSION="$1"
TAG="v${VERSION}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_DIR="$REPO_ROOT/plugin"
ZIP_NAME="Jellyfin.Plugin.SeerrLoadingScreen-${VERSION}.zip"

cd "$REPO_ROOT"

# Ensure clean tree
if ! git diff --quiet HEAD; then
    echo "Working tree has uncommitted changes. Aborting." >&2
    exit 3
fi

# Build the ZIP
cd "$PLUGIN_DIR"
rm -rf bin obj dist
VERSION="${VERSION}" bash build-zip.sh

ZIP="$PLUGIN_DIR/dist/${ZIP_NAME}"
if [[ ! -f "$ZIP" ]]; then
    echo "Built ZIP missing: $ZIP" >&2
    exit 4
fi

CHECKSUM=$(md5sum "$ZIP" | awk '{print $1}')
TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%S.0000000Z)"

# Update manifest.json with the new version entry (insert at top of versions[])
cd "$REPO_ROOT"
python3 - <<PY
import json
import sys
from pathlib import Path

path = Path("manifest.json")
data = json.loads(path.read_text())
plugin = data[0]
new_version = {
    "version": "${VERSION}.0",
    "changelog": "See CHANGELOG.md",
    "targetAbi": "10.11.0.0",
    "sourceUrl": f"https://github.com/Petr1t/jellyfin_seerr_loading_screen/releases/download/${TAG}/${ZIP_NAME}",
    "checksum": "${CHECKSUM}",
    "timestamp": "${TIMESTAMP}",
}
plugin["versions"].insert(0, new_version)
path.write_text(json.dumps(data, indent=2) + "\n")
print(f"manifest.json updated: ${VERSION}.0")
PY

# Commit, tag, push
git add manifest.json
git commit -q -m "release: ${TAG}"
git tag "${TAG}"
git push origin main
git push origin "${TAG}"

# Create GitHub release with the ZIP attached
gh release create "${TAG}" \
    --title "${TAG}" \
    --notes-file CHANGELOG.md \
    "$ZIP"

echo ""
echo "Released ${TAG}"
echo "  ZIP: $ZIP"
echo "  md5: ${CHECKSUM}"
echo "  Manifest URL: https://raw.githubusercontent.com/Petr1t/jellyfin_seerr_loading_screen/main/manifest.json"
