#!/bin/sh
# Copy the Alloy Route addon into a WoW Forever client.
#   companion/install_addon.sh ["/Volumes/T7/Blizzard/World of Warcraft/_forever_"]
set -eu
client=${1:-"/Volumes/T7/Blizzard/World of Warcraft/_forever_"}
source_dir=$(cd "$(dirname "$0")/../app/addon/AlloyRoute" && pwd)
if [ ! -d "$client" ]; then
    echo "No WoW Forever client at $client. Is the drive mounted?" >&2
    exit 1
fi
target="$client/Interface/AddOns/AlloyRoute"
mkdir -p "$target"
cp "$source_dir/AlloyRoute.toc" "$source_dir/AlloyRoute.lua" "$target/"
# Copies onto exFAT drives leave ._ AppleDouble files beside the addon.
if command -v dot_clean >/dev/null 2>&1; then dot_clean -m "$target" || true; fi
echo "Installed Alloy Route $(sed -n 's/^## Version: //p' "$target/AlloyRoute.toc") to $target"
