#!/usr/bin/env python3
"""
Wobkey Crush 80 OTA flasher (Linux, no extra deps — uses system libhidapi-hidraw)

Usage:
    python3 flash.py [firmware.bin]
    python3 flash.py --list       # enumerate matching HID devices

Defaults to crush80_telink_fw_patched.bin in the same directory.
"""

import ctypes, ctypes.util, struct, sys, time, os, zlib

# ── libhidapi via ctypes ──────────────────────────────────────────────────────

lib = ctypes.CDLL("/usr/lib/libhidapi-hidraw.so.0")

lib.hid_init.restype = ctypes.c_int
lib.hid_exit.restype = ctypes.c_int
lib.hid_open.restype  = ctypes.c_void_p
lib.hid_open.argtypes = [ctypes.c_ushort, ctypes.c_ushort, ctypes.c_wchar_p]
lib.hid_open_path.restype  = ctypes.c_void_p
lib.hid_open_path.argtypes = [ctypes.c_char_p]
lib.hid_close.argtypes = [ctypes.c_void_p]
lib.hid_write.restype  = ctypes.c_int
lib.hid_write.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_size_t]
lib.hid_read_timeout.restype  = ctypes.c_int
lib.hid_read_timeout.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_size_t, ctypes.c_int]
lib.hid_error.restype  = ctypes.c_wchar_p
lib.hid_error.argtypes = [ctypes.c_void_p]

class HidDeviceInfo(ctypes.Structure):
    pass
HidDeviceInfo._fields_ = [
    ("path",            ctypes.c_char_p),
    ("vendor_id",       ctypes.c_ushort),
    ("product_id",      ctypes.c_ushort),
    ("serial_number",   ctypes.c_wchar_p),
    ("release_number",  ctypes.c_ushort),
    ("manufacturer",    ctypes.c_wchar_p),
    ("product",         ctypes.c_wchar_p),
    ("usage_page",      ctypes.c_ushort),
    ("usage",           ctypes.c_ushort),
    ("interface_number",ctypes.c_int),
    ("next",            ctypes.POINTER(HidDeviceInfo)),
]
lib.hid_enumerate.restype  = ctypes.POINTER(HidDeviceInfo)
lib.hid_enumerate.argtypes = [ctypes.c_ushort, ctypes.c_ushort]
lib.hid_free_enumeration.argtypes = [ctypes.POINTER(HidDeviceInfo)]

# ── Crush 80 HID identifiers ─────────────────────────────────────────────────

VID           = 0x320F
PID_USB       = 0x5055
OTA_USAGE_PAGE = 0xFFEF
REPORT_ID     = 0x05
PKT_LEN       = 64          # hidraw packet size (report id + 63 payload bytes)

# ── CRC-16/ARC (Telink OTA per-chunk CRC) ────────────────────────────────────

def crc16arc(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF

# ── HID helpers ───────────────────────────────────────────────────────────────

def make_pkt(payload):
    """Build a 64-byte HID packet: [REPORT_ID] + payload (padded with 0xFF)."""
    buf = bytearray(PKT_LEN)
    buf[0] = REPORT_ID
    for i, b in enumerate(payload[:PKT_LEN - 1]):
        buf[1 + i] = b
    for i in range(len(payload), PKT_LEN - 1):
        buf[1 + i] = 0xFF
    return buf

def hid_write(dev, pkt):
    arr = (ctypes.c_ubyte * len(pkt))(*pkt)
    n = lib.hid_write(dev, arr, len(pkt))
    if n < 0:
        raise IOError(f"hid_write failed: {lib.hid_error(dev)}")

def hid_read(dev, timeout_ms=3000):
    buf = (ctypes.c_ubyte * PKT_LEN)()
    n = lib.hid_read_timeout(dev, buf, PKT_LEN, timeout_ms)
    if n < 0:
        raise IOError(f"hid_read failed: {lib.hid_error(dev)}")
    return bytes(buf[:n]) if n > 0 else b""

# ── Firmware helpers ──────────────────────────────────────────────────────────

def validate_firmware(fw):
    if len(fw) < 8:
        raise ValueError("firmware too small")
    stored_crc = struct.unpack_from("<I", fw, len(fw) - 4)[0]
    expected = (~zlib.crc32(fw[:-4])) & 0xFFFFFFFF
    if stored_crc in (0, 0xFFFFFFFF):
        raise ValueError(f"firmware CRC field is 0x{stored_crc:08x} — looks erased or corrupt")
    if stored_crc != expected:
        raise ValueError(
            f"firmware CRC mismatch: stored 0x{stored_crc:08x} != computed 0x{expected:08x}\n"
            "This firmware may be corrupt. Patch it with flash.py before flashing."
        )
    print(f"Firmware validated: {len(fw)} bytes, CRC 0x{stored_crc:08x} OK")

# ── OTA protocol ──────────────────────────────────────────────────────────────

def ota_flash(dev, fw):
    fw_size = len(fw)
    total_chunks = (fw_size + 15) // 16   # each chunk = 16 bytes of firmware

    # Pad fw with 0xFF to make length a multiple of 16
    padded = fw + b"\xff" * (total_chunks * 16 - fw_size)

    # ── START command ────────────────────────────────────────────────────────
    start_payload = bytes([0x02, 0x02, 0x00, 0x01])
    hid_write(dev, make_pkt(start_payload))
    print("Sent OTA start command")
    time.sleep(0.05)

    # ── DATA packets ─────────────────────────────────────────────────────────
    idx = 0
    while idx < total_chunks:
        chunks_this_pkt = []
        for _ in range(3):
            if idx >= total_chunks:
                break
            chunk16 = padded[idx * 16 : idx * 16 + 16]
            crc_data = bytes([idx & 0xFF, (idx >> 8) & 0xFF]) + chunk16
            crc = crc16arc(crc_data)
            chunk_pkt = crc_data + bytes([crc & 0xFF, (crc >> 8) & 0xFF])  # 20 bytes
            chunks_this_pkt.append(chunk_pkt)
            idx += 1

        data = b"".join(chunks_this_pkt)
        payload = bytes([0x00, len(data), 0x00]) + data
        hid_write(dev, make_pkt(payload))

        pct = min(100, idx * 16 * 100 // fw_size)
        print(f"\r  Flashing... {pct}% ({idx}/{total_chunks} chunks)", end="", flush=True)

        # Small delay every packet to avoid overwhelming the device
        time.sleep(0.005)

        # Check for abort/error response (non-blocking)
        resp = hid_read(dev, timeout_ms=0)
        if resp and resp[0] == 5 and resp[1] == 2 and resp[4] == 6:
            if resp[6] != 0:
                print(f"\nDevice error response: {resp.hex()}")
                return False

    print()

    # ── END command ──────────────────────────────────────────────────────────
    last_idx = idx - 1
    complement = (0xFFFF - last_idx + 1) & 0xFFFF
    end_payload = bytes([
        0x02, 0x06, 0x00, 0x02, 0xFF,
        last_idx & 0xFF, (last_idx >> 8) & 0xFF,
        complement & 0xFF, (complement >> 8) & 0xFF,
    ])
    hid_write(dev, make_pkt(end_payload))
    print(f"Sent OTA end command (last_idx={last_idx}, complement=0x{complement:04x})")

    # ── Wait for result ───────────────────────────────────────────────────────
    print("Waiting for device response...")
    for _ in range(30):
        resp = hid_read(dev, timeout_ms=500)
        if not resp:
            continue
        # Success: [05 02 03 00 06 FF 00 ...]
        if (len(resp) >= 7 and resp[0] == 5 and resp[1] == 2 and
                resp[2] == 3 and resp[3] == 0 and resp[4] == 6 and resp[5] == 0xFF):
            if resp[6] == 0:
                print("OTA SUCCESS — device will reboot")
                return True
            else:
                print(f"OTA FAILED — device error code: {resp[6]}")
                return False
    print("No success response received (device may have rebooted anyway)")
    return None

# ── Entry point ───────────────────────────────────────────────────────────────

def list_devices():
    devs = lib.hid_enumerate(VID, 0)
    cur = devs
    found = 0
    while cur:
        d = cur.contents
        print(f"  {d.path.decode()}: VID={d.vendor_id:04x} PID={d.product_id:04x} "
              f"usage_page={d.usage_page:04x} usage={d.usage:04x} "
              f"iface={d.interface_number} product={d.product}")
        found += 1
        cur = d.next
    lib.hid_free_enumeration(devs)
    if not found:
        print(f"  No devices with VID=0x{VID:04x} found")

def find_ota_device():
    devs = lib.hid_enumerate(VID, PID_USB)
    cur = devs
    path = None
    while cur:
        d = cur.contents
        if d.usage_page == OTA_USAGE_PAGE:
            path = d.path
            break
        cur = d.next
    lib.hid_free_enumeration(devs)
    return path

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if "--list" in sys.argv:
        list_devices()
        return

    fw_path = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
    if fw_path is None:
        fw_path = os.path.join(script_dir, "crush80_telink_fw_patched.bin")

    print(f"Loading firmware: {fw_path}")
    with open(fw_path, "rb") as f:
        fw = f.read()
    validate_firmware(fw)

    lib.hid_init()
    try:
        path = find_ota_device()
        if path is None:
            print(f"Crush 80 OTA interface (VID={VID:04x} PID={PID_USB:04x} "
                  f"usagePage={OTA_USAGE_PAGE:04x}) not found.")
            print("Is the keyboard plugged in via USB? Try --list to see all matching devices.")
            sys.exit(1)

        print(f"Found OTA device at: {path.decode()}")
        dev = lib.hid_open_path(path)
        if not dev:
            print("Failed to open device — try running with sudo or check udev rules")
            sys.exit(1)

        try:
            print()
            print("WARNING: This will flash modified firmware to your keyboard.")
            print("The keyboard will reboot after flashing.")
            confirm = input("Type 'yes' to proceed: ")
            if confirm.strip().lower() != "yes":
                print("Aborted.")
                return

            ota_flash(dev, fw)
        finally:
            lib.hid_close(dev)
    finally:
        lib.hid_exit()

if __name__ == "__main__":
    main()
