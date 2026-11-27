#!/bin/sh
# List each character's Azeroth Chronicle save, newest first.
#   companion/find_saves.sh ["/Volumes/T7/Blizzard/World of Warcraft/_forever_"]
set -eu
client=${1:-"/Volumes/T7/Blizzard/World of Warcraft/_forever_"}
root="$client/WTF/Account"
# Per-character saves are exactly <account>/<realm>/<character>/SavedVariables/AlloyRoute.lua.
# The account-wide SavedVariables folder sits two levels higher and is skipped.
found=$(find "$root" -mindepth 5 -maxdepth 5 -path '*/SavedVariables/AlloyRoute.lua' -type f 2>/dev/null || true)
if [ -z "$found" ]; then
    echo "No Azeroth Chronicle saves under $root yet. Record, then Save & Reload." >&2
    exit 1
fi
printf '%s\n' "$found" | while IFS= read -r path; do
    printf '%s\t%s\n' "$(date -r "$path" '+%Y-%m-%d %H:%M')" "$path"
done | sort -r
