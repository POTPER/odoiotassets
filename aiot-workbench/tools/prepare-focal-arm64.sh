#!/usr/bin/env bash
# Collect a complete signed-index dependency closure without installing anything.
set -euo pipefail
output=${1:?Specify a new output directory}
[[ ! -e "$output" ]] || { echo 'Output must not exist' >&2; exit 2; }
work=$(mktemp -d /tmp/workbench-apt.XXXXXXXX)
trap 'rm -rf -- "$work"' EXIT
mkdir -p "$work/lists/partial" "$work/archives/partial" "$work/empty"
touch "$work/status"
cat > "$work/sources.list" <<'SOURCES'
deb [arch=arm64 signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] https://ports.ubuntu.com/ubuntu-ports focal main
deb [arch=arm64 signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] https://ports.ubuntu.com/ubuntu-ports focal-updates main
deb [arch=arm64 signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] https://ports.ubuntu.com/ubuntu-ports focal-security main
SOURCES
options=(-o "Dir::Etc::sourcelist=$work/sources.list" -o "Dir::Etc::sourceparts=$work/empty"
  -o "Dir::State::status=$work/status" -o "Dir::State::lists=$work/lists"
  -o "Dir::Cache::archives=$work/archives" -o Dir::Cache::pkgcache= -o Dir::Cache::srcpkgcache=
  -o APT::Architecture=arm64 -o APT::Architectures::=arm64 -o Debug::NoLocking=true
  -o APT::Sandbox::User=root -o APT::Get::List-Cleanup=false)
apt-get "${options[@]}" update
apt-get "${options[@]}" --download-only --no-install-recommends --no-remove -y install \
  python3 python3-tk python3-pil python3-pil.imagetk policykit-1
mkdir -p "$output"
cp -- "$work/archives/"*.deb "$output/"
cp -- "$work/sources.list" "$output/SOURCES.list"
printf 'ubuntu 20.04 arm64\n' > "$output/PLATFORM"
(cd -- "$output" && sha256sum -- *.deb > SHA256SUMS)
for file in "$output/"*.deb; do dpkg-deb -W --showformat='${Package}\t${Version}\t${Architecture}\n' "$file"; done > "$output/PACKAGES.tsv"
echo "Collected $(find "$output" -maxdepth 1 -name '*.deb' | wc -l) packages"
