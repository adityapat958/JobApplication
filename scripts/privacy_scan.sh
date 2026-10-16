#!/usr/bin/env bash
# Fails (exit 1) if the repo contains personal data or secrets.
# Scans every tracked + untracked (non-ignored) file. Works on macOS and Linux.
set -u
cd "$(dirname "$0")/.."

# Patterns are split so this file doesn't match itself.
P1="Patward""han"; P2="apatward""han"; P3="adi""tyapat"; P4="gh""p_"; P5="/ho""me/"
# Real first/last names and handles of the owner and test users (never in git; docs say "test user A/B/C").
N1="Kshi""tij"; N2="Hase""eb"; N3="Adi""tya"; N4="Chaud""hary"; N5="Kha""lid"; N6="kshi""tijc"; N7="hase""ebkh""alid"
WORDS="$P1|$P2|$P3|$P4|$P5|/Us""ers/[a-z]|$N1|$N2|$N3|$N4|$N5|$N6|$N7"
PHONE='(\+[0-9]{1,3}[ .-]?)?\(?[0-9]{3}\)?[ .-][0-9]{3}[ .-][0-9]{4}([^0-9]|$)|\+47[ ]?[0-9]{2}[ ]?[0-9]{2}[ ]?[0-9]{2}[ ]?[0-9]{2}([^0-9]|$)|\+[0-9]{1,3}[ ]?\([0-9]{3}\)'
# The scanner itself is the only file allowed to hold the (split) patterns.
ALLOW='^scripts/privacy_scan\.sh$'

fail=0
files=$(git ls-files -co --exclude-standard | grep -Ev "$ALLOW" || true)
[ -z "$files" ] && { echo "privacy scan: no files"; exit 0; }
while IFS= read -r f; do
  [ -f "$f" ] || continue
  if grep -IEn -i "$WORDS" "$f" >/dev/null 2>&1; then
    grep -IEn -i "$WORDS" "$f" | head -5 | sed "s|^|$f:|"; fail=1
  fi
  if grep -IEn "$PHONE" "$f" >/dev/null 2>&1; then
    grep -IEn "$PHONE" "$f" | head -5 | sed "s|^|$f: phone? |"; fail=1
  fi
done <<< "$files"

if [ $fail -ne 0 ]; then echo "privacy scan: FAILED"; exit 1; fi
echo "privacy scan: clean"
