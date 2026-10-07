"""ld-27037 (Xcode CLT 27.0) does not pad the indirect symbol table when it
has an odd number of entries, so the string table starts 4-byte aligned and
dyld refuses the file. Pads 4 bytes in front of the string table and
re-signs. Handles thin 64-bit Mach-O files only."""

import struct
import subprocess
import sys

MH_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64, LC_SYMTAB, LC_CODE_SIGNATURE = 0x19, 0x2, 0x1D


def _drop_load_command(data: bytearray, at: int) -> None:
    ncmds, sizeofcmds = struct.unpack_from("<II", data, 16)
    size = struct.unpack_from("<I", data, at + 4)[0]
    end = 32 + sizeofcmds
    data[at:end] = data[at + size : end] + b"\0" * size
    struct.pack_into("<II", data, 16, ncmds - 1, sizeofcmds - size)


def fix(path: str) -> bool:
    data = bytearray(open(path, "rb").read())
    if len(data) < 32 or struct.unpack_from("<I", data)[0] != MH_MAGIC_64:
        return False
    ncmds = struct.unpack_from("<I", data, 16)[0]
    off, symtab, linkedit, codesig = 32, None, None, None
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, off)
        if cmd == LC_SYMTAB:
            symtab = off
        elif cmd == LC_CODE_SIGNATURE:
            codesig = off
        elif cmd == LC_SEGMENT_64 and data[off + 8 : off + 24].rstrip(b"\0") == b"__LINKEDIT":
            linkedit = off
        off += size
    if symtab is None or linkedit is None:
        return False
    stroff, strsize = struct.unpack_from("<II", data, symtab + 16)
    if stroff % 8 == 0:
        return False
    if codesig is not None:
        sig_off, _ = struct.unpack_from("<II", data, codesig + 8)
        if sig_off < stroff + strsize:
            raise SystemExit(f"{path}: something follows the string table, not fixing")
    del data[stroff + strsize :]  # codesign writes a new signature
    data[stroff:stroff] = b"\0" * 4
    struct.pack_into("<I", data, symtab + 16, stroff + 4)
    fileoff, filesize = struct.unpack_from("<QQ", data, linkedit + 40)
    vmsize = struct.unpack_from("<Q", data, linkedit + 32)[0]
    new_filesize = len(data) - fileoff
    struct.pack_into("<Q", data, linkedit + 48, new_filesize)
    if vmsize < new_filesize:
        struct.pack_into("<Q", data, linkedit + 32, (new_filesize + 0x3FFF) & ~0x3FFF)
    if codesig is not None:
        _drop_load_command(data, codesig)  # last: later commands move up
    open(path, "wb").write(data)
    if codesig is not None:
        subprocess.run(["codesign", "-f", "-s", "-", path], check=True, capture_output=True)
    return True


if __name__ == "__main__":
    for p in sys.argv[1:]:
        if fix(p):
            print(f"align_strtab: fixed {p}", file=sys.stderr)
