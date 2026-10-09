#!/usr/bin/env bash
# Builds "YT Downloader.app" (no Python needed to run the result).
#
#   ./packaging/build_mac.sh            (run from anywhere)
#
# Bundled tools, looked up in this order:
#   ffmpeg/ffprobe  packaging/bin/  →  PATH
#   deno            packaging/bin/  →  PATH (only with BUNDLE_DENO=1; adds ~120 MB)
#
# Homebrew's ffmpeg is fine: PyInstaller copies the libraries it needs into the
# app and relinks them, so the result runs on Macs without Homebrew.
# The app is built for this Mac's CPU (Apple Silicon or Intel).

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
APP_NAME="YT Downloader"
VENV="build/venv"
BIN_DIR="packaging/bin"

say()  { printf "\n\033[1m%s\033[0m\n" "$*"; }
ok()   { printf "  ✔ %s\n" "$*"; }
warn() { printf "  \033[33m⚠ %s\033[0m\n" "$*"; }

say "YT Downloader: macOS build"

command -v python3 >/dev/null || { echo "python3 not found. Install it from https://python.org"; exit 1; }
ok "$(python3 --version)"

# 1. Isolated build environment
say "Installing dependencies…"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet ".[build]"
ok "Dependencies installed"

# 2. Tools to bundle
say "Looking for ffmpeg…"
EXTRA=()
find_tool() {   # prints the path of $1, preferring packaging/bin/
  if [ -x "$BIN_DIR/$1" ]; then echo "$ROOT/$BIN_DIR/$1"; else command -v "$1" || true; fi
}
for tool in ffmpeg ffprobe; do
  path="$(find_tool "$tool")"
  if [ -z "$path" ]; then
    warn "$tool not found. MP3 conversion and HD video won't work in the app."
    warn "Install with: brew install ffmpeg  (or put a static build in $BIN_DIR/)"
    continue
  fi
  real="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$path")"
  EXTRA+=(--add-binary "$real:.")
  ok "$tool: $real"
done

if [ "${BUNDLE_DENO:-0}" = "1" ]; then
  deno="$(find_tool deno)"
  if [ -n "$deno" ]; then
    EXTRA+=(--add-binary "$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$deno"):.")
    ok "deno: $deno"
  else
    warn "BUNDLE_DENO=1 but deno wasn't found (brew install deno)"
  fi
else
  ok "Not bundling deno (users with deno/node installed get full quality; BUNDLE_DENO=1 to bundle)"
fi

# 3. Build
say "Building the app (about a minute)…"
rm -rf "build/$APP_NAME" "dist/$APP_NAME" "dist/$APP_NAME.app"
"$VENV/bin/python" -m PyInstaller \
  --noconfirm --clean --log-level WARN \
  --windowed --onedir \
  --name "$APP_NAME" \
  --osx-bundle-identifier "org.ytdl.desktop" \
  --paths "$ROOT" \
  --add-data "$ROOT/ytdl/web/static:ytdl/web/static" \
  --collect-all yt_dlp \
  --collect-all yt_dlp_ejs \
  --collect-data certifi \
  --specpath build \
  ${EXTRA[@]+"${EXTRA[@]}"} \
  "$ROOT/packaging/app_entry.py"

rm -rf "dist/$APP_NAME"   # the bare onedir folder; the .app is what we ship
(cd dist && ditto -c -k --sequesterRsrc --keepParent "$APP_NAME.app" "$APP_NAME-macOS.zip")

say "✅ Done"
echo "  App: $ROOT/dist/$APP_NAME.app"
echo "  Zip: $ROOT/dist/$APP_NAME-macOS.zip  (for sharing / GitHub Releases)"
[ -n "${NO_OPEN:-}" ] || open dist/ 2>/dev/null || true
