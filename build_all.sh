#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

VERSION="0.3.1"
LINUX_BIN="dist/baton-${VERSION}-linux-x86_64"
VSIX="vscode/baton-${VERSION}.vsix"

echo "==> Building baton ${VERSION}"
echo "==> Cleaning dist/"
rm -rf dist build
mkdir -p dist

echo "==> Building Linux binary with Nuitka"
python3 -m nuitka \
  --onefile \
  --assume-yes-for-downloads \
  --output-dir=dist \
  --output-filename="baton-${VERSION}-linux-x86_64" \
  --include-data-files=baton-spec.md=baton-spec.md \
  baton_main.py

echo "==> Binary: ${LINUX_BIN}"

echo "==> Building VS Code extension"
pushd vscode >/dev/null
npm install --no-audit --no-fund >/dev/null 2>&1 || true
npx --yes @vscode/vsce package --out "baton-${VERSION}.vsix"
popd >/dev/null

echo "==> VSIX: ${VSIX}"
echo "==> Done"
ls -lh "$LINUX_BIN" "$VSIX"
