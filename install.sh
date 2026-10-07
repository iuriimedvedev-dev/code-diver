#!/bin/sh
set -eu

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
repo=${CODE_DIVER_REPOSITORY:-iuriimedvedev-dev/code-diver}
version=${CODE_DIVER_VERSION:-latest}
case "$repo" in *[!A-Za-z0-9_./-]*|*..*|/*|*/|'') fail 'Invalid release repository.' ;; esac
case "$version" in *[!A-Za-z0-9_.-]*|.|..|'') fail 'Invalid release version.' ;; esac
for tool in curl tar uname mktemp chmod mv mkdir cp rm; do
    command -v "$tool" >/dev/null 2>&1 || fail "Required command missing: $tool"
done
case "$(uname -s)" in
    Darwin) os=apple-darwin ;;
    Linux) os=unknown-linux-gnu ;;
    *) fail 'Supported platforms: macOS and Linux.' ;;
esac
case "$(uname -m)" in
    arm64|aarch64) arch=aarch64 ;;
    x86_64|amd64) arch=x86_64 ;;
    *) fail 'Supported architectures: arm64 and x86_64.' ;;
esac
if command -v sha256sum >/dev/null 2>&1; then
    hash_tool=sha256sum
elif command -v shasum >/dev/null 2>&1; then
    hash_tool=shasum
else
    fail 'Install sha256sum or shasum before retrying.'
fi
asset=code-diver-$arch-$os.tar.gz
base=https://github.com/$repo/releases
if [ "$version" = latest ]; then
    base=$base/latest/download
else
    base=$base/download/$version
fi
install_dir=${INSTALL_DIR:-${HOME:?HOME must be set}/.local/bin}
work=$(mktemp -d) || fail 'Cannot create download directory.'
stage=
cleanup() {
    rm -rf "$work"
    if [ -n "$stage" ]; then rm -f "$stage"; fi
}
trap cleanup 0
trap 'exit 1' HUP INT TERM
download() {
    curl --disable --fail --silent --show-error --location \
        --proto '=https' --proto-redir '=https' --connect-timeout 15 \
        --max-time 600 --output "$2" "$1" || fail 'Release download failed; check the release exists and retry.'
}
download "$base/$asset" "$work/archive.tar.gz"
download "$base/$asset.sha256" "$work/checksum"
IFS=' ' read -r expected _remainder < "$work/checksum" || fail 'Invalid checksum file.'
case "$expected" in *[!0-9a-fA-F]*|'') fail 'Invalid SHA256 checksum.' ;; esac
[ "${#expected}" -eq 64 ] || fail 'Invalid SHA256 checksum length.'
if [ "$hash_tool" = sha256sum ]; then
    actual=$(sha256sum "$work/archive.tar.gz") || fail 'SHA256 calculation failed.'
else
    actual=$(shasum -a 256 "$work/archive.tar.gz") || fail 'SHA256 calculation failed.'
fi
actual=${actual%% *}
[ "$actual" = "$expected" ] || fail 'SHA256 mismatch; nothing installed.'
tar -xzf "$work/archive.tar.gz" -C "$work" code-diver || fail 'Invalid release archive.'
[ -f "$work/code-diver" ] && [ ! -L "$work/code-diver" ] || fail 'Release executable missing or unsafe.'
mkdir -p "$install_dir" || fail 'Cannot create installation directory.'
stage=$(mktemp "$install_dir/.code-diver.XXXXXX") || fail 'Cannot stage executable.'
cp "$work/code-diver" "$stage" || fail 'Cannot copy executable.'
chmod 755 "$stage" || fail 'Cannot mark executable runnable.'
mv -f "$stage" "$install_dir/code-diver" || fail 'Cannot install executable.'
stage=
printf 'PASS: installed code-diver. Running setup.\n'
if ( : < /dev/tty ) 2>/dev/null; then
    "$install_dir/code-diver" setup < /dev/tty || fail 'Setup failed; rerun code-diver setup in a terminal.'
else
    "$install_dir/code-diver" setup < /dev/null || fail 'Setup failed; rerun code-diver setup in a terminal.'
fi
printf 'PASS: setup complete. Add %s to PATH if needed.\n' "$install_dir"