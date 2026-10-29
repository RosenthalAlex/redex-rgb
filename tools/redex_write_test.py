#!/usr/bin/env python3
"""
Trust GXT 926 Redex II - first write test: write the config block back UNCHANGED.

Steps (all bytes as OemDrv.exe sends them, see PROTOCOL.md):
  1. read:   SET_FEATURE 05 21 00 00 00 00 00 00 (mode 2), then GET_FEATURE report 8
  2. check:  reply header 08 21, block[0x00] == 0x64, block[0x90] == 0xa5
  3. backup: block saved to redex_backup_mode<N>.bin
  4. write:  SET_FEATURE report 8 (520 bytes):
             08 21 00 92 00 00 00 00 + <the same 148-byte block> + zeros
             (only after you type "yes")
  5. verify: read again and compare with the original

Usage:
    python3 redex_write_test.py              # mode 2 (2.4 GHz)
    python3 redex_write_test.py --mode 1   # the 05 11 block
"""
import argparse, os, sys, time

import redex_dump as rd

WRITE_LEN = 520
WRITE_FLAG = 0x92     # header byte the software uses for report-8 devices = block length (0x9f only on the report-6 variant)
WRITE_CMD = {1: 0x11, 2: 0x21, 3: 0x31}
AFTER_WRITE_DELAY = 0.05   # the software sleeps 50 ms after the write


def read_block(fd, mode):
    rd.send_read_cmd(fd, rd.CMD_READ_CONFIG[mode])
    rep = rd.retry(rd.get_feature, fd, 8, WRITE_LEN)
    return rep, rd.get_block(rep)


def check_block(rep, block, mode):
    problems = []
    if block is None:
        problems.append(f"reply is {len(rep)} bytes, expected at least {rd.BLOCK_OFFSET + rd.BLOCK_DEV_LEN}")
    if rep[:2] != bytes([8, rd.CMD_READ_CONFIG[mode]]):
        problems.append(f"reply header is {rep[:2].hex(' ')}, expected 08 {rd.CMD_READ_CONFIG[mode]:02x}")
    if block is not None:
        if any(block[rd.BLOCK_DEV_LEN:]):
            problems.append("bytes after the 146-byte block are not zero")
        if block[0x00] != 0x64:
            problems.append(f"block[0x00] = 0x{block[0]:02x}, expected 0x64")
        if block[0x90] != 0xA5:
            problems.append(f"block[0x90] = 0x{block[0x90]:02x}, expected 0xa5")
    return problems


def build_write(block, mode):
    buf = bytearray(WRITE_LEN)
    buf[0:4] = bytes([8, WRITE_CMD[mode], 0x00, WRITE_FLAG])
    buf[rd.BLOCK_OFFSET:rd.BLOCK_OFFSET + rd.BLOCK_LEN] = block
    return bytes(buf)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", type=int, choices=(1, 2, 3), default=2,
                    help="config mode: 2 = 2.4 GHz (what the software uses for PID 0320), 1 = the other one")
    args = ap.parse_args()

    nodes = [n for n, phys in rd.find_hidraw() if phys.endswith("input1")]
    if len(nodes) != 1:
        sys.exit(f"Expected exactly one Redex interface-1 hidraw node, found: {nodes}")
    node = nodes[0]
    try:
        fd = os.open(node, os.O_RDWR)
    except PermissionError:
        sys.exit(f"No permission for {node}: sudo chmod a+rw {node}")

    try:
        # 1-2: read and check
        rd.send_read_cmd(fd, rd.CMD_STATUS)
        st = rd.retry(rd.get_feature, fd, 5, 8)
        if not (st[2] == 1 and st[3] == 1):
            sys.exit(f"Mouse does not report online (status {st.hex(' ')}). Move it / wake it up and retry.")
        rep, block = read_block(fd, args.mode)
        problems = check_block(rep, block, args.mode)
        if problems:
            sys.exit("Block failed the checks, nothing was written:\n  " + "\n  ".join(problems))

        # 3: backup
        backup = f"redex_backup_mode{args.mode}.bin"
        if not os.path.exists(backup):
            open(backup, "wb").write(block)
            print(f"Backup saved: {backup}")
        else:
            print(f"Backup already exists, kept: {backup}")

        # 4: show and confirm
        out = build_write(block, args.mode)
        print(f"\nWill send SET_FEATURE report 8 ({len(out)} bytes) to {node}:")
        print(rd.hexdump(out[:rd.BLOCK_OFFSET + rd.BLOCK_LEN]))
        print(f"...      (bytes 0x{rd.BLOCK_OFFSET + rd.BLOCK_LEN:03x}-0x{WRITE_LEN - 1:03x} are all 00)")
        print("\nThe block is exactly what the mouse just returned; no field is changed.")
        if input('Type "yes" to send it: ').strip() != "yes":
            sys.exit("Cancelled, nothing was written.")

        rd.retry(rd.set_feature, fd, out)
        print("Write sent.")
        time.sleep(AFTER_WRITE_DELAY)

        # 5: verify
        rep2, block2 = read_block(fd, args.mode)
        if block2 == block:
            print("OK: no error and the block read back is identical (this alone does not prove the write is applied).")
        else:
            print("WARNING: block read back differs from the original:")
            for i, (a, b) in enumerate(zip(block, block2)):
                if a != b:
                    print(f"  block[0x{i:02x}]: 0x{a:02x} -> 0x{b:02x}")
            if len(block2) != len(block):
                print(f"  length {len(block)} -> {len(block2)}")
            print(f"The original is in {backup}. Do not write again; send this output first.")
    except OSError as e:
        sys.exit(f"HID error: {e}")
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
