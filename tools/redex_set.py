#!/usr/bin/env python3
"""
Trust GXT 926 Redex II - change one setting, or restore the backup.

Every write is read-modify-write, like the Trust software: the block is read from the
mouse, only the requested bytes are changed, and it is written back with the verified
header 08 <21 (mode 2) | 11 | 31> 00 92 00 00 00 00 (see PROTOCOL.md). Before writing, the changed
bytes are shown and you have to type "yes". After writing, the block is read back.

Usage:
    python3 redex_set.py topcolor ff0000            # top LED: one static color (all DPI levels)
    python3 redex_set.py dpicolor 0000ff --level 3  # top LED color of DPI level 3 only
    python3 redex_set.py bottomcolor 00ff00         # bottom LED: static color (effect 2)
    python3 redex_set.py effect 1                   # bottom LED effect (0-10, see effect_map.txt)
    python3 redex_set.py effectscan                 # try bottom LED effects 0-10
    python3 redex_set.py x8b-restore                # bytes 0x8b-0x8f back to the backup
    python3 redex_set.py restore                    # write redex_backup_mode2.bin back

The top LED always shows the color of the active DPI level; the bottom LED runs the effect.
"""
import argparse, os, sys, time

import redex_dump as rd
import redex_write_test as wt

DPI_COLOR_BASE = 0x25  # 8 levels x 3 bytes, see PROTOCOL.md
EFFECT_ID = 0x3d       # bottom LED effect (live-mapped, effect_map.txt)
EFFECT_MAX = 10        # OemDrv.exe handles effect types 0-10 (0x414da0)
STATIC_EFFECT = 2      # bottom LED "static color" effect (live-mapped)
STATIC_COLOR = 0x41    # its color, RGB
MAIN_MODE = 0x8b       # [0x8b] mode, [0x8c] param, [0x8d..0x8f] color (0x41508e); no visible effect so far
MAIN_COLOR = 0x8d
MAIN_SCAN_MAX = 7


def parse_color(s):
    s = s.lstrip("#")
    if len(s) != 6:
        raise argparse.ArgumentTypeError("color must be RRGGBB, e.g. 0000ff")
    try:
        return bytes.fromhex(s)
    except ValueError:
        raise argparse.ArgumentTypeError("color must be hex RRGGBB, e.g. 0000ff")


def open_mouse():
    nodes = [n for n, phys in rd.find_hidraw() if phys.endswith("input1")]
    if len(nodes) != 1:
        sys.exit(f"Expected exactly one Redex interface-1 hidraw node, found: {nodes}")
    try:
        return nodes[0], os.open(nodes[0], os.O_RDWR)
    except PermissionError:
        sys.exit(f"No permission for {nodes[0]}: sudo chmod a+rw {nodes[0]}")


def read_checked(fd, mode):
    rd.send_read_cmd(fd, rd.CMD_STATUS)
    st = rd.retry(rd.get_feature, fd, 5, 8)
    if not (st[2] == 1 and st[3] == 1):
        sys.exit(f"Mouse does not report online (status {st.hex(' ')}). Move it / wake it up and retry.")
    rep, block = wt.read_block(fd, mode)
    problems = wt.check_block(rep, block, mode)
    if problems:
        sys.exit("Block failed the checks, nothing was written:\n  " + "\n  ".join(problems))
    return block


def ensure_backup(block, mode):
    path = f"redex_backup_mode{mode}.bin"
    if not os.path.exists(path):
        open(path, "wb").write(block)
        print(f"Backup saved: {path}")
    return path


def write_confirmed(fd, old, new, mode):
    changes = [(i, a, b) for i, (a, b) in enumerate(zip(old, new)) if a != b]
    if not changes:
        print("Nothing to change, the mouse already has these values.")
        return True
    print("Bytes to change (offsets inside the block):")
    for i, a, b in changes:
        print(f"  block[0x{i:02x}]: 0x{a:02x} -> 0x{b:02x}")
    if input('Type "yes" to write: ').strip() != "yes":
        sys.exit("Cancelled, nothing was written.")
    if write_verified(fd, new, mode):
        print("OK: the mouse now returns the new values.")
        return True
    return False


def write_verified(fd, new, mode):
    """Write the block, read it back, report differences. No prompt."""
    rd.retry(rd.set_feature, fd, wt.build_write(new, mode))
    time.sleep(wt.AFTER_WRITE_DELAY)
    _, back = wt.read_block(fd, mode)
    if back == new:
        return True
    print("WARNING: read-back differs from what was written:")
    for i, (a, b) in enumerate(zip(new, back or b"")):
        if a != b:
            print(f"  block[0x{i:02x}]: wrote 0x{a:02x}, read 0x{b:02x}")
    print("Do not write again; send this output first.")
    return False


def scan(fd, old, mode, offset, maxval, what, outfile):
    """Step through values 0..maxval of one byte (only block[offset] changes), ask what the
    mouse shows, then put the original value back."""
    orig = old[offset]
    print(f"Current {what}: {orig}")
    print(f"Will write {what} 0, 1, ... {maxval} one after another. Only block[0x{offset:02x}] changes;")
    print(f"at the end (also on Ctrl+C or q) it is set back to {orig}.")
    if input('Type "yes" to start: ').strip() != "yes":
        sys.exit("Cancelled, nothing was written.")

    results, cur, written = {}, bytearray(old), False
    try:
        for val in range(maxval + 1):
            cur[offset] = val
            written = True
            if not write_verified(fd, bytes(cur), mode):
                break
            ans = input(f"{what} {val:2}: what does the mouse show? (Enter = nothing visible, q = stop) > ").strip()
            if ans.lower() == "q":
                break
            results[val] = ans or "(nothing visible / off?)"
    finally:
        if written:
            cur[offset] = orig
            ok = write_verified(fd, bytes(cur), mode)
            print(f"\n{what} set back to {orig}." if ok else
                  "\nCould not set it back; run: python3 redex_set.py restore")

    if results:
        lines = [f"{val:2}  {desc}" for val, desc in results.items()]
        open(outfile, "w").write(f"{what} -> what the mouse showed\n" + "\n".join(lines) + "\n")
        print("\n".join(lines) + f"\nSaved: {outfile}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", type=int, choices=(1, 2, 3), default=2,
                    help="config mode: 2 = 2.4 GHz (what the software uses for PID 0320), 1 = the other one")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("topcolor", help="top LED: one static color (all DPI levels get it)")
    p.add_argument("color", type=parse_color, help="RRGGBB")
    p = sub.add_parser("dpicolor", help="top LED color of one DPI level")
    p.add_argument("color", type=parse_color, help="RRGGBB")
    p.add_argument("--level", type=int, choices=range(1, 9), metavar="1-8",
                   help="DPI level (default: the active one)")
    p = sub.add_parser("bottomcolor", help="bottom LED: static color (switches to effect 2)")
    p.add_argument("color", type=parse_color, help="RRGGBB")
    p = sub.add_parser("effect", help="bottom LED effect ID (see effect_map.txt)")
    p.add_argument("id", type=int, choices=range(EFFECT_MAX + 1), metavar=f"0-{EFFECT_MAX}")
    sub.add_parser("effectscan", help="step through bottom LED effects 0-10")
    p = sub.add_parser("x8b-mode", help="byte 0x8b (purpose unknown, no visible effect so far)")
    p.add_argument("id", type=int, choices=range(MAIN_SCAN_MAX + 1), metavar=f"0-{MAIN_SCAN_MAX}")
    p = sub.add_parser("x8b-color", help="bytes 0x8d-0x8f (purpose unknown)")
    p.add_argument("color", type=parse_color, help="RRGGBB")
    sub.add_parser("x8b-restore", help="put bytes 0x8b-0x8f back to the backup values")
    sub.add_parser("restore", help="write the whole backup block back")
    args = ap.parse_args()

    node, fd = open_mouse()
    try:
        old = read_checked(fd, args.mode)
        backup = ensure_backup(old, args.mode)
        new = bytearray(old)

        if args.cmd == "topcolor":
            count = max(old[3] & 0x0F, 1)
            for lvl in range(count):
                o = DPI_COLOR_BASE + 3 * lvl
                new[o:o + 3] = args.color
            print(f"Top LED: all {count} DPI levels -> {args.color.hex(' ')}")
        elif args.cmd == "bottomcolor":
            new[STATIC_COLOR:STATIC_COLOR + 3] = args.color
            new[EFFECT_ID] = STATIC_EFFECT
            print(f"Bottom LED: effect {old[EFFECT_ID]} -> {STATIC_EFFECT} (static), "
                  f"color {old[STATIC_COLOR:STATIC_COLOR + 3].hex(' ')} -> {args.color.hex(' ')}")
        elif args.cmd == "x8b-restore":
            saved = open(backup, "rb").read()
            new[MAIN_MODE:MAIN_COLOR + 3] = saved[MAIN_MODE:MAIN_COLOR + 3]
            print(f"Bytes 0x8b-0x8f back to the values in {backup}")
        elif args.cmd == "dpicolor":
            active, count = old[3] >> 4, old[3] & 0x0F
            level = args.level or active
            if not 1 <= level <= max(count, 1):
                sys.exit(f"Level {level} is not in use (the mouse has {count} levels).")
            o = DPI_COLOR_BASE + 3 * (level - 1)
            new[o:o + 3] = args.color
            print(f"DPI level {level} (active: {active}): {old[o:o + 3].hex(' ')} -> {args.color.hex(' ')}")
        elif args.cmd == "x8b-color":
            o = MAIN_COLOR
            new[o:o + 3] = args.color
            print(f"Bytes 0x8d-0x8f: {old[o:o + 3].hex(' ')} -> {args.color.hex(' ')}")
        elif args.cmd == "x8b-mode":
            new[MAIN_MODE] = args.id
            print(f"Byte 0x8b: {old[MAIN_MODE]} -> {args.id}")
        elif args.cmd == "effect":
            new[EFFECT_ID] = args.id
            print(f"Bottom LED effect: {old[EFFECT_ID]} -> {args.id}")
        elif args.cmd == "effectscan":
            scan(fd, old, args.mode, EFFECT_ID, EFFECT_MAX, "bottom LED effect", "effect_map.txt")
            return
        else:
            saved = open(backup, "rb").read()
            if len(saved) != rd.BLOCK_LEN or saved[0] != 0x64 or saved[0x90] != 0xA5:
                sys.exit(f"{backup} does not look like a valid block, not restoring.")
            new[:] = saved
            print(f"Restoring {backup}")

        write_confirmed(fd, old, bytes(new), args.mode)
    except OSError as e:
        sys.exit(f"HID error: {e}")
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
