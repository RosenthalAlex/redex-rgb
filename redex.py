#!/usr/bin/env python3
"""
redex - RGB control for the Trust GXT 926 Redex II wireless mouse (USB 145F:0320).

  redex                           open the window (GTK app)
  redex --background              follow the GNOME accent color (redex-accent.service)
  redex status                    show the current lighting settings
  redex top purple                top LED: one static color (all DPI levels)
  redex top ff8000 --level 3      top LED color of DPI level 3 only
  redex bottom 0000ff             bottom LED: static color
  redex effect rainbow-wave       bottom LED effect (name or number, see "redex effects")
  redex effects                   list the effects
  redex restore                   write the saved original configuration back

Colors: RRGGBB hex (e.g. ff00ff) or a name: red green blue yellow cyan purple
orange pink white off.

Every write is read-modify-write, like the Trust software: the config block is read
(05 21, then report 8), checked, only the requested bytes are changed, and it is written
back with the header 08 21 00 92 00 00 00 00, then read back and compared.
The first run saves the original block to ~/.local/share/redex/backup_mode2.bin.
Protocol details: PROTOCOL.md.
"""
import argparse, fcntl, glob, os, sys, time

VID, PID = "0000145F", "00000320"

# Read commands and write format verified from OemDrv.exe and on the real mouse.
CMD_STATUS = 0x80
CMD_CONFIG = {1: 0x11, 2: 0x21, 3: 0x31}   # mode 2 = 2.4 GHz, the one that takes effect
REPORT8_LEN = 520
HEADER_LEN = 8
BLOCK_LEN = 0x94          # what the software copies (last 2 bytes zero)
BLOCK_DEV_LEN = 0x92      # what the mouse returns; also the length byte in the write header
RETRIES, CMD_DELAY, AFTER_WRITE = 3, 0.1, 0.05

# Block layout (offsets inside the block, verified live)
DPI_LEVEL = 0x03          # high nibble: active level (1-based), low nibble: number of levels
DPI_COLORS = 0x25         # 8 x RGB, the top LED shows the active level's color
EFFECT = 0x3d             # bottom LED effect
STATIC_COLOR = 0x41       # RGB color of the static effect
MAGIC = 0x90              # always 0xa5

EFFECTS = {               # bottom LED, mapped live with effectscan
    "off": 0, "rainbow-wave": 1, "static": 2, "breathing": 3, "rainbow-cycle": 4,
    "fade": 5, "multi-static": 6, "flicker": 7, "random": 8, "random-wave": 9,
}
EFFECT_NAMES = {v: k for k, v in EFFECTS.items()}
EFFECT_NAMES[10] = "unknown-10"   # nothing visible in the test (maybe brightness too low)

COLORS = {
    "red": "ff0000", "green": "00ff00", "blue": "0000ff", "yellow": "ffff00",
    "cyan": "00ffff", "purple": "ff00ff", "magenta": "ff00ff", "orange": "ff8000",
    "pink": "ff4080", "white": "ffffff", "off": "000000", "black": "000000",
}

BACKUP_DIR = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "redex")


class RedexError(Exception):
    """Anything that stops an operation; the message is meant for the user."""


# ---------- HID access ----------

def _ioc(nr, length):
    # _IOC(_IOC_READ|_IOC_WRITE, 'H', nr, len): 0x06 = HIDIOCSFEATURE, 0x07 = HIDIOCGFEATURE
    return (3 << 30) | (length << 16) | (ord("H") << 8) | nr


def get_feature(fd, rid, length):
    buf = bytearray(length)
    buf[0] = rid
    n = fcntl.ioctl(fd, _ioc(0x07, length), buf, True)
    return bytes(buf[:n])


def set_feature(fd, data):
    fcntl.ioctl(fd, _ioc(0x06, len(data)), bytearray(data), True)


def retry(fn, *args):
    for attempt in range(RETRIES):
        try:
            return fn(*args)
        except OSError:
            if attempt == RETRIES - 1:
                raise
            time.sleep(0.2)


def find_node():
    for path in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            uevent = open(os.path.join(path, "device", "uevent")).read()
        except OSError:
            continue
        phys = next((l.split("=", 1)[1] for l in uevent.splitlines() if l.startswith("HID_PHYS=")), "")
        if f"HID_ID=0003:{VID}:{PID}" in uevent and phys.endswith("input1"):
            return "/dev/" + os.path.basename(path)
    return None


def open_mouse():
    node = find_node()
    if not node:
        raise RedexError("mouse dongle not found (145F:0320)")
    try:
        return os.open(node, os.O_RDWR)
    except PermissionError:
        raise RedexError(f"no permission for {node}. Install the udev rule (70-redex.rules), "
                         f"or for now: sudo chmod a+rw {node}")


def query(fd, cmd):
    """Verified read command on report 5 (05 <cmd> 00 ...), then the answer."""
    retry(set_feature, fd, bytes([5, cmd, 0, 0, 0, 0, 0, 0]))
    time.sleep(CMD_DELAY)


def read_block(fd, mode):
    query(fd, CMD_CONFIG[mode])
    rep = retry(get_feature, fd, 8, REPORT8_LEN)
    raw = rep[HEADER_LEN:HEADER_LEN + BLOCK_LEN]
    problems = []
    if rep[:2] != bytes([8, CMD_CONFIG[mode]]):
        problems.append(f"reply header {rep[:2].hex(' ')}")
    if len(raw) < BLOCK_DEV_LEN:
        problems.append(f"reply only {len(rep)} bytes")
    else:
        raw = bytes(raw) + bytes(BLOCK_LEN - len(raw))
        if raw[0] != 0x64 or raw[MAGIC] != 0xA5 or any(raw[BLOCK_DEV_LEN:]):
            problems.append("block content check failed")
    return raw, problems


def read_checked(fd, mode):
    query(fd, CMD_STATUS)
    st = retry(get_feature, fd, 5, 8)
    if not (len(st) >= 4 and st[2] == 1 and st[3] == 1):
        raise RedexError("the mouse is not online (move it to wake it up)")
    block, problems = read_block(fd, mode)
    if problems:
        raise RedexError("unexpected answer from the mouse, nothing written: " + ", ".join(problems))
    return block


def write_block(fd, block, mode):
    out = bytearray(REPORT8_LEN)
    out[0:4] = bytes([8, CMD_CONFIG[mode], 0x00, BLOCK_DEV_LEN])
    out[HEADER_LEN:HEADER_LEN + BLOCK_LEN] = block
    retry(set_feature, fd, bytes(out))
    time.sleep(AFTER_WRITE)
    back, problems = read_block(fd, mode)
    return not problems and back == block


# ---------- helpers ----------

def parse_color(s):
    h = COLORS.get(s.lower(), s.lstrip("#"))
    try:
        if len(h) == 6:
            return bytes.fromhex(h)
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(f"not a color: {s} (use RRGGBB or a name: {', '.join(COLORS)})")


def parse_effect(s):
    if s.isdigit() and 0 <= int(s) <= 10:
        return int(s)
    if s.lower() in EFFECTS:
        return EFFECTS[s.lower()]
    raise argparse.ArgumentTypeError(f"unknown effect: {s} (see: redex effects)")


def ensure_backup(block, mode):
    path = os.path.join(BACKUP_DIR, f"backup_mode{mode}.bin")
    if not os.path.exists(path):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        open(path, "wb").write(block)
        print(f"Original configuration saved: {path}")
    return path


def hexcolor(b):
    return b.hex()


def load_backup(mode=2):
    path = os.path.join(BACKUP_DIR, f"backup_mode{mode}.bin")
    saved = open(path, "rb").read()
    if len(saved) != BLOCK_LEN or saved[0] != 0x64 or saved[MAGIC] != 0xA5:
        raise RedexError(f"{path} does not look like a valid backup")
    return saved


# ---------- library API (used by the GUI) ----------

def read_state(mode=2):
    """Open the mouse, read and check the block, make the first backup. Returns the block."""
    fd = open_mouse()
    try:
        block = read_checked(fd, mode)
        ensure_backup(block, mode)
        return block
    except OSError as e:
        raise RedexError(f"HID error: {e}")
    finally:
        os.close(fd)


def modify(edit, mode=2):
    """Read-modify-write: edit(bytearray) changes the block in place. Returns the new block."""
    fd = open_mouse()
    try:
        old = read_checked(fd, mode)
        ensure_backup(old, mode)
        new = bytearray(old)
        edit(new)
        new = bytes(new)
        if new != old and not write_block(fd, new, mode):
            raise RedexError("the mouse did not return the new values after writing")
        return new
    except OSError as e:
        raise RedexError(f"HID error: {e}")
    finally:
        os.close(fd)


def set_top(block, color, level=None):
    count = max(block[DPI_LEVEL] & 0x0F, 1)
    if level and level > count:
        raise RedexError(f"the mouse uses only {count} DPI levels")
    for lvl in ([level - 1] if level else range(count)):
        block[DPI_COLORS + 3 * lvl:DPI_COLORS + 3 * lvl + 3] = color


def set_bottom(block, color):
    block[STATIC_COLOR:STATIC_COLOR + 3] = color
    block[EFFECT] = EFFECTS["static"]


def show_status(b):
    active, count = b[DPI_LEVEL] >> 4, b[DPI_LEVEL] & 0x0F
    colors = [hexcolor(b[DPI_COLORS + 3 * i:DPI_COLORS + 3 * i + 3]) for i in range(count)]
    eff = b[EFFECT]
    print(f"Top LED     : {colors[active - 1] if 1 <= active <= count else '?'} "
          f"(DPI level {active} of {count}; levels: {' '.join(colors)})")
    line = f"Bottom LED  : effect {eff} ({EFFECT_NAMES.get(eff, '?')})"
    if eff == EFFECTS["static"]:
        line += f", color {hexcolor(b[STATIC_COLOR:STATIC_COLOR + 3])}"
    print(line)


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(prog="redex", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", type=int, choices=(1, 2, 3), default=2, help=argparse.SUPPRESS)
    ap.add_argument("-n", "--dry-run", action="store_true", help="show the changes, write nothing")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show the current lighting settings")
    p = sub.add_parser("top", help="top LED color")
    p.add_argument("color", type=parse_color)
    p.add_argument("--level", type=int, choices=range(1, 9), metavar="1-8",
                   help="only this DPI level (default: all levels)")
    p = sub.add_parser("bottom", help="bottom LED static color")
    p.add_argument("color", type=parse_color)
    p = sub.add_parser("effect", help="bottom LED effect")
    p.add_argument("effect", type=parse_effect)
    sub.add_parser("effects", help="list the bottom LED effects")
    sub.add_parser("restore", help="write the saved original configuration back")
    args = ap.parse_args()

    if args.cmd == "effects":
        for name, num in EFFECTS.items():
            print(f"{num:2}  {name}")
        return

    try:
        fd = open_mouse()
    except RedexError as e:
        sys.exit(f"redex: {e}")
    try:
        old = read_checked(fd, args.mode)
        ensure_backup(old, args.mode)
        if args.cmd == "status":
            show_status(old)
            return

        new = bytearray(old)
        if args.cmd == "top":
            set_top(new, args.color, args.level)
        elif args.cmd == "bottom":
            set_bottom(new, args.color)
        elif args.cmd == "effect":
            new[EFFECT] = args.effect
        elif args.cmd == "restore":
            new[:] = load_backup(args.mode)

        new = bytes(new)
        changes = [(i, a, b) for i, (a, b) in enumerate(zip(old, new)) if a != b]
        if not changes:
            print("Already set, nothing to write.")
            return
        print("Changes: " + ", ".join(f"[0x{i:02x}] {a:02x}->{b:02x}" for i, a, b in changes))
        if args.dry_run:
            print("Dry run, nothing written.")
            return
        if not write_block(fd, new, args.mode):
            sys.exit("redex: the mouse did not return the new values after writing. "
                     "Do not retry; check with 'redex status'.")
        show_status(new)
    except RedexError as e:
        sys.exit(f"redex: {e}")
    except OSError as e:
        sys.exit(f"redex: HID error: {e}")
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
