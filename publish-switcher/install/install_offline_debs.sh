#!/usr/bin/env bash
# Install the requested dependencies using only a temporary local APT source.
set -euo pipefail

deb_dir=$1
shift
shopt -s nullglob
debs=("$deb_dir"/*.deb)
if ((${#debs[@]} == 0)); then
  printf '缺少离线依赖（%s），且未在以下目录找到 .deb：%s\n' "$*" "$deb_dir" >&2
  echo '请准备与目标机 Ubuntu 版本及架构匹配的 .deb 和依赖，再用 --offline --deb-dir 目录 重试。' >&2
  exit 1
fi

for command in apt-get dpkg dpkg-deb sha256sum; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "安装本地 .deb 需要系统命令 $command。" >&2
    exit 1
  fi
done
architecture=$(dpkg --print-architecture)
if [[ -f "$deb_dir/PLATFORM" ]]; then
  bundle_platform=$(<"$deb_dir/PLATFORM")
  system_platform=$(
    . /etc/os-release
    printf '%s %s %s' "${ID:-unknown}" "${VERSION_ID:-unknown}" "$architecture"
  )
  if [[ "$bundle_platform" != "$system_platform" ]]; then
    printf '离线依赖适用于 %s，当前系统为 %s。请用 --deb-dir 指定匹配的依赖目录。\n' \
      "$bundle_platform" "$system_platform" >&2
    exit 1
  fi
fi
stage=$(mktemp -d /tmp/publish-switcher-debs.XXXXXXXX)
trap 'rm -rf -- "$stage"' EXIT
mkdir -p "$stage/repo" "$stage/lists" "$stage/empty"
chmod 755 "$stage" "$stage/repo" "$stage/lists"
index="$stage/repo/Packages"
: > "$index"
count=0
has_pkexec=false
has_policykit=false
for deb in "${debs[@]}"; do
  [[ -f "$deb" ]] || continue
  file="package-$count.deb"
  # Stage under a safe name so paths with spaces or removable media work.
  cp -- "$deb" "$stage/repo/$file"
  package="$stage/repo/$file"
  if ! package_arch=$(dpkg-deb -f "$package" Architecture) || [[ -z "$package_arch" ]]; then
    echo "无效的 .deb：$deb" >&2
    exit 1
  fi
  if [[ "$package_arch" != all && "$package_arch" != "$architecture" ]]; then
    printf '跳过架构为 %s 的包：%s\n' "$package_arch" "${deb##*/}"
    continue
  fi
  chmod 644 "$package"
  name=$(dpkg-deb -f "$package" Package)
  case "$name" in
    pkexec) has_pkexec=true ;;
    policykit-1) has_policykit=true ;;
  esac
  size=$(stat -c '%s' "$package")
  checksum=$(sha256sum "$package")
  {
    dpkg-deb -f "$package"
    printf 'Filename: ./%s\nSize: %s\nSHA256: %s\n\n' "$file" "$size" "${checksum%% *}"
  } >> "$index"
  count=$((count + 1))
done
if ((count == 0)); then
  echo "目录内没有适用于 $architecture 的离线包：$deb_dir" >&2
  exit 1
fi

required=()
for name in "$@"; do
  if [[ "$name" != polkit ]]; then
    required+=("$name")
  elif "$has_pkexec"; then
    required+=(pkexec)
  elif "$has_policykit"; then
    required+=(policykit-1)
  else
    echo '离线目录缺少管理员授权组件的 .deb（pkexec 或 policykit-1）。' >&2
    exit 1
  fi
done

printf 'deb [trusted=yes] file:%s/repo ./\n' "$stage" > "$stage/sources.list"
# APT_CONFIG is read before the system fragments. Only the local file: source
# is loaded, with fresh lists and without any system APT download hooks.
config="$stage/apt.conf"
cat > "$config" <<EOF
Dir::Etc::Parts "$stage/empty";
Dir::Etc::main "/dev/null";
Dir::Etc::SourceList "$stage/sources.list";
Dir::Etc::SourceParts "$stage/empty";
Dir::Etc::preferences "/dev/null";
Dir::Etc::preferencesparts "$stage/empty";
Dir::State::lists "$stage/lists";
Dir::Cache::pkgcache "";
Dir::Cache::srcpkgcache "";
Acquire::Languages "none";
Acquire::CompressionTypes::Order:: "uncompressed";
EOF
APT_CONFIG="$config" apt-get -q update
if ! APT_CONFIG="$config" apt-get -s --no-remove --no-install-recommends install "${required[@]}"; then
  echo '本地包无法满足依赖。请按上面的 APT 提示补齐与目标系统匹配的 .deb。' >&2
  exit 1
fi
if ((EUID == 0)); then
  APT_CONFIG="$config" apt-get -y --no-remove --no-install-recommends install "${required[@]}"
else
  sudo env APT_CONFIG="$config" apt-get -y --no-remove --no-install-recommends install "${required[@]}"
fi
