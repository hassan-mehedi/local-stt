#!/bin/sh
# Linker for cargo on Xcode command line tools 27.0 (ld-27037): links with
# cc, then moves the string table to an 8-byte boundary, which that ld
# misses when the indirect symbol table has an odd number of entries. dyld
# refuses such dylibs ("mis-aligned LINKEDIT string pool"), which breaks
# proc macros. Use with CARGO_PROFILE_*_STRIP=none: strip redoes the layout.
cc "$@" || exit $?
out=""
prev=""
for a in "$@"; do
    [ "$prev" = "-o" ] && out="$a"
    prev="$a"
done
[ -n "$out" ] && [ -f "$out" ] && python3 "$(dirname "$0")/align_strtab.py" "$out"
exit 0
