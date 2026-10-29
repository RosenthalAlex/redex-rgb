#!/usr/bin/env python3
"""
Trust GXT 926 Redex II - feature report dump.

Default mode only READS (HIDIOCGFEATURE) and sends nothing to the mouse.

--config sends the read commands the Trust software (OemDrv.exe, CDev24G) uses,
and nothing else (see PROTOCOL.md):
    05 80 00 00 00 00 00 00   status query      (SendCmd, then GetCmd)
    05 21 00 00 00 00 00 00   read config, mode 2 = 2.4 GHz (11 = mode 1, 31 = mode 3),
                              then GET_FEATURE report 8 (520 bytes)
These do not change the configuration. No write command (report 8 SET) is ever sent.

Usage:
    python3 redex_dump.py                     # passive dump, prints to screen
    python3 redex_dump.py piros               # also saves dump_piros.txt
    python3 redex_dump.py --config piros      # read config block (mode 2, 05 21)
    python3 redex_dump.py --config --mode 1 piros   # the 05 11 block read so far
"""
import argparse, fcntl, glob, os, sys, time

VID, PID = "0000145F", "00000320"
# Vendor feature reports from the interface 1 HID descriptor: (report ID, length incl. ID byte)
REPORTS = [(5, 8), (6, 8), (8, 520)]

# Read-only command bytes taken from OemDrv.exe. Nothing outside this table is ever sent.
CMD_STATUS = 0x80
CMD_READ_CONFIG = {1: 0x11, 2: 0x21, 3: 0x31}

BLOCK_LEN = 0x94      # general config block size the software copies (last 2 bytes are zero)
BLOCK_DEV_LEN = 0x92  # bytes the mouse actually returns; also the length byte in the write header
BLOCK_OFFSET = 8      # GetData returns the block starting at report byte 8
RETRIES = 3           # the software retries 3 times with 200 ms pauses
CMD_DELAY = 0.1       # pause between command and answer (software: per-device value)


def _ioc(nr, length):
    # _IOC(_IOC_READ|_IOC_WRITE, 'H', nr, len)
    return (3 << 30) | (length << 16) | (ord("H") << 8) | nr


def get_feature(fd, rid, length):
    buf = bytearray(length)
    buf[0] = rid
    n = fcntl.ioctl(fd, _ioc(0x07, length), buf, True)
    return bytes(buf[:n])


def set_feature(fd, data):
    buf = bytearray(data)
    fcntl.ioctl(fd, _ioc(0x06, len(buf)), buf, True)


def retry(fn, *args):
    for attempt in range(RETRIES):
        try:
            return fn(*args)
        except OSError:
            if attempt == RETRIES - 1:
                raise
            time.sleep(0.2)


def send_read_cmd(fd, cmd):
    """SendCmd with a verified read-only command byte: 05 <cmd> 00 00 00 00 00 00."""
    assert cmd == CMD_STATUS or cmd in CMD_READ_CONFIG.values(), "not a verified read command"
    retry(set_feature, fd, bytes([5, cmd, 0, 0, 0, 0, 0, 0]))
    time.sleep(CMD_DELAY)


def get_block(rep):
    """General block from a report-8 reply, zero-padded to BLOCK_LEN like the software's buffer."""
    raw = rep[BLOCK_OFFSET:BLOCK_OFFSET + BLOCK_LEN]
    if len(raw) < BLOCK_DEV_LEN:
        return None
    return bytes(raw) + bytes(BLOCK_LEN - len(raw))


def find_hidraw():
    found = []
    for path in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            uevent = open(os.path.join(path, "device", "uevent")).read()
        except OSError:
            continue
        if f"HID_ID=0003:{VID}:{PID}" in uevent:
            phys = next((l.split("=", 1)[1] for l in uevent.splitlines() if l.startswith("HID_PHYS=")), "")
            found.append(("/dev/" + os.path.basename(path), phys))
    return found


def hexdump(data, base=0):
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        lines.append(f"{base + i:04x}  " + " ".join(f"{b:02x}" for b in chunk))
    return "\n".join(lines)


def decode_block(b):
    """Human-readable view of the fields known from static analysis (see PROTOCOL.md)."""
    rgb = lambda o: " ".join(f"{x:02x}" for x in b[o:o + 3])
    polling = {1: "125 Hz", 2: "250 Hz", 3: "500 Hz", 4: "1000 Hz"}.get(b[2] & 0x0F, f"? ({b[2] & 0x0F})")
    out = [
        f"[00] first byte     = 0x{b[0]:02x} (software writes 0x64)",
        f"[02] polling        = {polling}, separate X/Y DPI = {bool(b[2] & 0x80)}",
        f"[03] active DPI lvl = {b[3] >> 4} of {b[3] & 0x0F} levels",
        "[05] DPI X (raw)    = " + " ".join(str(b[5 + 2 * i] | b[6 + 2 * i] << 8) for i in range(8)),
        "[15] DPI Y (raw)    = " + " ".join(str(b[0x15 + 2 * i] | b[0x16 + 2 * i] << 8) for i in range(8)),
        "[25] DPI colors     = " + " | ".join(rgb(0x25 + 3 * i) for i in range(8)),
        f"[3d] bottom effect  = {b[0x3d]}",
        f"[3e] effect 1       = param 0x{b[0x3e]:02x}, direction 0x{b[0x3f]:02x}",
        f"[40] effect 2       = param 0x{b[0x40]:02x}, color {rgb(0x41)}",
        f"[44] effect 3       = param 0x{b[0x44]:02x}, count {b[0x45]}, colors "
        + " | ".join(rgb(0x46 + 3 * i) for i in range(min(b[0x45], 7))),
        f"[5b..5d] eff 4/5/6  = 0x{b[0x5b]:02x} 0x{b[0x5c]:02x} 0x{b[0x5d]:02x}, eff 6 color0 {rgb(0x5e)}",
        f"[7c] effect 7       = param 0x{b[0x7c]:02x}, colors {rgb(0x7d)} | {rgb(0x80)}",
        f"[83..85] eff 8/9/10 = 0x{b[0x83]:02x} 0x{b[0x84]:02x} 0x{b[0x85]:02x}",
        f"[8b] main LED       = mode {b[0x8b]}, param 0x{b[0x8c]:02x}, color {rgb(0x8d)}",
        f"[90] magic          = 0x{b[0x90]:02x} (software writes 0xa5)",
        f"[91] flags          = 0x{b[0x91]:02x}",
    ]
    return "\n".join(out)


def passive_dump(fd):
    out = []
    for rid, length in REPORTS:
        try:
            data = get_feature(fd, rid, length)
            out.append(f"-- feature report {rid} ({len(data)} byte)\n{hexdump(data)}")
        except OSError as e:
            out.append(f"-- feature report {rid}: error ({e})")
    return out


def config_dump(fd, mode):
    out = []
    try:
        send_read_cmd(fd, CMD_STATUS)
        st = retry(get_feature, fd, 5, 8)
        # reply echoes the command at [1]; the software checks the next two bytes
        online = st[2] == 1 and st[3] == 1
        out.append(f"-- status (05 80): {st.hex(' ')}  -> online={online}")
    except OSError as e:
        out.append(f"-- status (05 80): error ({e})")

    cmd = CMD_READ_CONFIG[mode]
    try:
        send_read_cmd(fd, cmd)
        rep = retry(get_feature, fd, 8, 520)
    except OSError as e:
        out.append(f"-- read config (05 {cmd:02x}): error ({e})")
        return out
    out.append(f"-- report 8 after 05 {cmd:02x} ({len(rep)} byte)\n{hexdump(rep)}")
    block = get_block(rep)
    if block is not None:
        out.append(f"-- general block, mode {mode} (offsets inside the block)\n{hexdump(block)}")
        out.append(f"-- decoded\n{decode_block(block)}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("label", nargs="?", help="save output to dump_<label>.txt")
    ap.add_argument("--config", action="store_true",
                    help="send the verified read command and dump the config block")
    ap.add_argument("--mode", type=int, choices=(1, 2, 3), default=2,
                    help="config mode: 2 = 2.4 GHz (what the software uses for PID 0320), 1 = the other one")
    args = ap.parse_args()

    devices = find_hidraw()
    if not devices:
        sys.exit("No Redex hidraw device found (is the dongle plugged in?)")

    out = []
    for node, phys in devices:
        if not phys.endswith("input1"):
            continue  # the vendor reports live on interface 1
        out.append(f"== {node} ({phys})")
        try:
            fd = os.open(node, os.O_RDWR)
        except PermissionError:
            sys.exit(f"No permission for {node}: sudo chmod a+rw {node}")
        try:
            out += config_dump(fd, args.mode) if args.config else passive_dump(fd)
        finally:
            os.close(fd)

    text = "\n".join(out)
    print(text)
    if args.label:
        fname = f"dump_{args.label}.txt"
        open(fname, "w").write(text + "\n")
        print(f"\nSaved: {fname}")


if __name__ == "__main__":
    main()
