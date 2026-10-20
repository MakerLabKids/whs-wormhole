#!/usr/bin/env bash
# prep-card.sh: the two boot-volume edits for a freshly imaged Burrow card,
# with a check before and after. Run on the laptop with the card in the reader,
# after Raspberry Pi Imager says "Write Successful" and the card is re-inserted.
#
#   edge/burrow/prep-card.sh            # find the bootfs volume, check, edit, re-check
#   edge/burrow/prep-card.sh --check    # only report, change nothing
#   edge/burrow/prep-card.sh /path/to/bootfs [--check]
#
# Edits (see docs/design/burrow.html, step 2):
#   cmdline.txt : drop the `resize` token (or the old firstboot init=) so the
#                 root partition is not grown on first boot
#   user-data   : append growpart off + resize_rootfs false, once
# Checks: cmdline is one line without the token; user-data starts with
# #cloud-config, parses as YAML (if PyYAML is present), still carries the
# hostname, user and SSH key Imager wrote, and has no duplicate top-level keys.
set -uo pipefail

CHECK=0; BOOT=""
for a in "$@"; do
  case "$a" in --check) CHECK=1;; *) BOOT="$a";; esac
done

if [ -z "$BOOT" ]; then
  for d in /run/media/"$USER"/bootfs /media/"$USER"/bootfs /run/media/*/bootfs /media/*/bootfs /Volumes/bootfs; do
    [ -f "$d/cmdline.txt" ] && { BOOT="$d"; break; }
  done
fi
[ -n "$BOOT" ] && [ -f "$BOOT/cmdline.txt" ] || {
  echo "!! cannot find a mounted bootfs volume (looked under /run/media and /media)."
  echo "   Re-insert the card, or pass the path: $0 /path/to/bootfs"; exit 2; }

CMD="$BOOT/cmdline.txt"; UD="$BOOT/user-data"
[ -f "$UD" ] || { echo "!! $UD is missing: Imager's customisation was not applied to this card."
  echo "   Re-write it and answer YES to 'apply OS customisation settings'."; exit 2; }

ok=1
pass() { printf '  ok   %s\n' "$*"; }
fail() { printf '  FAIL %s\n' "$*"; ok=0; }

check() {
  ok=1
  echo "cmdline.txt:"
  local lines; lines=$(grep -c '' "$CMD")
  [ "$lines" -le 1 ] && pass "one line" || fail "$lines lines (must be one)"
  if grep -qw resize "$CMD"; then fail "still has the 'resize' token"
  elif grep -q 'firstboot' "$CMD"; then fail "still has the firstboot init= token"
  else pass "no resize token"; fi
  grep -q 'root=' "$CMD" && pass "root= present" || fail "root= missing (file damaged?)"

  echo "user-data:"
  head -c 14 "$UD" | grep -q '^#cloud-config' && pass "starts with #cloud-config" || fail "first line must be #cloud-config"
  if grep -q $'\r' "$UD"; then fail "has Windows line endings (CR); fix with: sed -i 's/\\r\$//' $UD"; fi
  grep -q $'\t' "$UD" && fail "contains a TAB; YAML needs spaces" || true
  grep -q '^hostname:' "$UD" && pass "hostname: $(sed -n 's/^hostname: *//p' "$UD" | head -1)" || fail "no hostname: line"
  grep -qE '^users:|^ *- name:' "$UD" && pass "user: $(sed -n 's/^ *- name: *//p' "$UD" | head -1)" || fail "no users: block"
  grep -q 'ssh-ed25519\|ssh-rsa\|ssh_pwauth' "$UD" && pass "ssh configured" || fail "no ssh key or ssh_pwauth"
  grep -q '^growpart:' "$UD" && pass "growpart block present" || fail "growpart block missing"
  grep -q '^resize_rootfs: *false' "$UD" && pass "resize_rootfs: false" || fail "resize_rootfs: false missing"
  local dups; dups=$(grep -oE '^[A-Za-z_]+:' "$UD" | sort | uniq -d | tr -d ':' | tr '\n' ' ')
  [ -z "$dups" ] && pass "no duplicate top-level keys" || fail "duplicate top-level keys: $dups"
  if python3 -c 'import yaml' 2>/dev/null; then
    if python3 -c 'import sys,yaml; d=yaml.safe_load(open(sys.argv[1])); assert isinstance(d,dict)' "$UD" 2>/tmp/prep-card-yaml.err; then
      pass "YAML parses"
    else fail "YAML does not parse: $(tail -1 /tmp/prep-card-yaml.err)"; fi
  else
    echo "  note PyYAML not installed, structural checks only (pip install pyyaml for the full check)"
  fi
}

echo "== $BOOT (before)"; check
before_ok=$ok
if [ "$CHECK" = 1 ]; then [ "$before_ok" = 1 ] && echo "== ready" || echo "== not ready"; exit $((1-before_ok)); fi
if [ "$before_ok" = 1 ]; then echo "== already prepared, nothing to do"; exit 0; fi

echo "== editing"
if grep -qw resize "$CMD"; then
  sed -i -E 's/ +resize\b//; s/\bresize +//' "$CMD"; echo "  removed 'resize' from cmdline.txt"
elif grep -q 'init=/usr/lib/raspberrypi-sys-mods/firstboot' "$CMD"; then
  sed -i -E 's# +init=/usr/lib/raspberrypi-sys-mods/firstboot##' "$CMD"; echo "  removed firstboot init= from cmdline.txt"
fi
# keep it one line, no trailing newline surprises
tr -d '\n' < "$CMD" > "$CMD.tmp" && printf '\n' >> "$CMD.tmp" && mv "$CMD.tmp" "$CMD"

if grep -q $'\r' "$UD"; then sed -i 's/\r$//' "$UD"; echo "  stripped CR line endings from user-data"; fi
if ! grep -q '^growpart:' "$UD"; then
  [ -n "$(tail -c1 "$UD")" ] && printf '\n' >> "$UD"      # file did not end with a newline
  printf '\ngrowpart:\n  mode: "off"\nresize_rootfs: false\n' >> "$UD"
  echo "  appended growpart/resize_rootfs to user-data"
elif ! grep -q '^resize_rootfs: *false' "$UD"; then
  [ -n "$(tail -c1 "$UD")" ] && printf '\n' >> "$UD"
  printf 'resize_rootfs: false\n' >> "$UD"; echo "  appended resize_rootfs: false"
fi
sync

echo "== $BOOT (after)"; check
if [ "$ok" = 1 ]; then
  echo "== ready: eject the card (umount \"$BOOT\") and boot it"
else
  echo "== NOT ready: fix the FAIL lines above (or re-image the card) before booting"; exit 1
fi
