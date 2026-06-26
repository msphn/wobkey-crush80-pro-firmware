# Crush 80 Firmware fix for macOS mode
## Abstract
I'm running this keyboard on macOS and linux. This keyboard hardcodes for macOS media keys. I hate this. And I hate wobkey. They support. And everything around them.

But I've paid 200 bucks for this filthy stinking keyboard and it's firmware so I won't accept that.

So, with heavy use of claude, and many hours of tinkering, I've reverse engineered the firmware and have a working understanding of how it works, including the firmware patching tool.

I NOP those jumps and now it's going for macOS also to the configurable table that are settable with VIA.

Also a word about the "QMK compatibility", it's a lie. It's the filthiest piece of shit implementation that works only for bunch of keys and has literally only one set of layers, that's probably why they hacked in that macOS that dirty.

I've included here the original firmware as crush80_telink_fw.bin and the patched firmware as crush80_telink_fw_patched.bin.

Also this repository contains the firmware patching tool used to modify the firmware which is reverse engineered from the .net/c# based firmware tool they provided.

A disclaimer: If you brick your keyboard, you're on your own. I'm not responsible for any damage or data loss. Though I promise that this repository doesn't contain any malicious code or backdoors. You gotta trust me on that I guess.

Love, Misha.

## Hardware
- **MCU**: Telink **TLSR9511** (RISC-V RV32IMC — NOT TC32/TLSR8258 as the chip packaging suggests)
  - TLSR9511 confirmed from USB string descriptor at firmware offset 0x1d7c0
  - CPU: RISC-V RV32IMC (compressed instruction set, multiply/divide extensions)
  - Flash at 0x20000000 (also aliased at 0x0), SRAM at 0x80000–0x8FFFF
  - Peripherals at 0x80100000+
- **Firmware size**: 121,332 bytes (extracted from code_2M.bin at offset 256)
- **OEM platform**: HFD (Hefei Dashen) — used in Wobkey, Epomaker, Sinohope keyboards

## USB / HID
- **VID**: 0x320F  (from param_128K, overrides OTA tool UI default of 0x248A)
- **PID**: 0x5055 (USB wired), 0x5088 (2.4G dongle)
- **OTA UsagePage**: 0xFFEF, ReportID: 0x05

### HID Report Descriptors (embedded at 0x1c940)
| Report ID | Type | Description |
|-----------|------|-------------|
| 1 | Keyboard | 8 modifiers + 6 keycodes (boot protocol) |
| 2 | Consumer | Single 16-bit consumer usage (media keys) |
| 3 | System | System power/sleep |
| 4 | Mouse | Standard mouse |
| 5 | Vendor | VIA config (4 bytes feature) |
| 6 | NKRO | Full 120-key bitmap keyboard |

## Key Data Regions
| Address | Contents |
|---------|----------|
| 0x1c940 | HID Report Descriptor |
| 0x1ca60 | Key matrix scan layout |
| 0x1cb34 | Profile names: "Crush 80-1", "Crush 80-2", "Crush 80-3" |
| 0x1d083 | Keycode table (profile 1) — uint16 HID codes, 8×16 matrix |
| 0x1d283 | Keycode table (profile 2) |
| 0x1d483 | Keycode table (profile 3) |
| 0x1d583 | Keycode table (profile 4) |
| 0x1d7c0 | USB string "TLSR9511" (confirms chip) |
| 0x2001B518 | F-key jump table (macOS mode, 12 entries) |
| 0x2001B548 | F-key jump table (Windows mode, 12 entries) |
| 0x2001B578 | F-key jump table (third mode/Fn layer, 12 entries) |

All four keycode tables have F1-F12 as standard HID codes (0x3A–0x45).
**The macOS media key remapping is NOT in the VIA keycode tables** — it is a
runtime translation layer in the RISC-V firmware.

## VIA Custom Keycodes (from VIA JSON, base 0x7E00)
| Code | Index | Name | Function |
|------|-------|------|----------|
| 0x7E00 | 0 | — | |
| 0x7E04 | 4 | THREEMODE | Switch BLE/2.4G/USB |
| 0x7E05 | 5 | WINLOCK | Lock Win key |
| 0x7E06 | 6 | WINMAC | Toggle Windows/macOS mode |

VIA supports 3 user keymaps ("Crush 80-1/2/3"). Customization works normally
in Windows mode; macOS mode ignores VIA keymap for F1-F12 (hardcodes media keys).

## macOS F-Key Remapping — Code Structure

The macOS F-key → media key translation lives in RISC-V code, not in tables.

### Flow
1. Key press detected → keycode looked up in VIA table → F1–F12 found
2. Firmware dispatches to per-F-key handler via jump table at `0x2001B518`
3. Each handler contains a Telink custom instruction (`0x00XX545B` series) that
   checks the macOS mode flag and either:
   - (macOS mode) jumps past `j 0x2001293c` → consumer key path
   - (Windows mode) falls through → `j 0x2001293c` → normal F-key path

### macOS F-key mapping
| Key | Handler addr | Internal code | HID consumer code | Mac function |
|-----|-------------|---------------|-------------------|--------------|
| F1  | 0x20012D3C  | 0xBE | 0x70 | Brightness- |
| F2  | 0x20012CFC  | 0xBD | 0x6F | Brightness+ |
| F3  | 0x20012D0C  | — (special) | 0x52 | Mission Control (keyboard key) |
| F4  | 0x20012D78  | — (special) | 0x09 | Launchpad |
| F5  | 0x20012D24  | 0xCF | 0xCF | Keyboard Brightness- |
| F6  | 0x20012D4C  | — (special) | 0x21 | Keyboard Brightness+ |
| F7  | 0x20012CBC  | 0xAC | 0xB6 | Previous Track |
| F8  | 0x20012CCC  | 0xAE | 0xCD | Play/Pause |
| F9  | 0x20012CDC  | 0xAB | 0xB5 | Next Track |
| F10 | 0x20012CEC  | 0xA8 | 0xE2 | Mute |
| F11 | 0x200129A0  | 0xAA | 0xEA | Volume- |
| F12 | 0x20012D64  | 0xA9 | 0xE9 | Volume+ |

Consumer→HID conversion is in function at 0x20008AE4.

## Firmware Format

### code_2M.bin outer container (256-byte header)
| Offset | Field | Value |
|--------|-------|-------|
| [2:6] | Firmware version (LE uint32) | 0x56565656 |
| [48:52] | Firmware size (BE uint32) | 121332 (0x1D9F4) |
| [256:] | Raw firmware body | 121332 bytes |

### Inner firmware layout
| Offset | Contents |
|--------|----------|
| [0:2] | Unknown (0xA025) |
| [2:4] | Unknown (0x0000) |
| [18:22] | Firmware size (LE uint32) |
| [0x20:0x24] | "KNLT" Telink OTA magic |
| [0x28:] | RISC-V code (entry: `auipc gp, 0xe0080` at 0x28) |
| [last 4] | CRC-32 (no final XOR: `~zlib.crc32(fw[:-4]) & 0xFFFFFFFF`) |

## OTA Protocol (fully understood from decompiled C# tool)
- **Transport**: HID WRITE (raw file stream write, NOT SetFeatureReport/SetOutputReport)
- **Packet structure**: `[0x05, payload[0], payload[1], ..., 0xFF...]` (64 bytes total)
- **Encryption**: None — `enc_key` (11 22 33 44...) is loaded but never used in OTA
- **Chunk size**: 16 bytes of firmware per index, 3 chunks per HID packet
- **Per-chunk CRC**: CRC-16/ARC (poly 0xA001, init 0xFFFF) over `[idx_lo, idx_hi, 16 bytes]`
- **Start command**: `[0x02, 0x02, 0x00, 0x01]` in payload field
- **Data packet**: `[0x02, total_len, 0x00, <chunk0_20b>, <chunk1_20b>, <chunk2_20b>]`
  - Each chunk = 2 bytes index + 16 bytes data + 2 bytes CRC
  - First byte MUST be 0x02 (OTA_CMD type — same as start/end; C# always sets sen[0]=2)
- **End command**: `[0x02, 0x06, 0x00, 0x02, 0xFF, last_idx_lo, last_idx_hi, ~last_idx_lo, ~last_idx_hi]`
- **Success response**: `[0x05, 0x02, 0x03, 0x00, 0x06, 0xFF, 0x00, ...]`
- **Fw version query**: send `[0x01, 0x00, 0x00, 0xFF, ...]`; response: `[0x05, 0x01, 0x08, 0x00, version_4b, crc_4b]`
- **Flow control**: device sends an input report after every write; tool must read it before sending next packet (error 10 = OTA_STATE_ERR if you skip this)

## The Patch (crush80_telink_fw_patched.bin)

**Problem**: In macOS mode, F1-F12 always send hardcoded media keys, ignoring VIA keymap.

**Fix**: Replace the 12 Telink custom branch instructions (one per F-key handler) with NOPs
(for F1-F10, F12) or an unconditional jump to the Windows-mode path (for F11). This
makes F-keys always use the normal VIA keymap path regardless of OS mode.

| Key | Offset | Original (Telink branch) | Patched |
|-----|--------|--------------------------|---------|
| F1  | 0x12D3C | 0x0014545B | 0x00000013 (NOP) |
| F2  | 0x12CFC | 0x0024545B | 0x00000013 (NOP) |
| F3  | 0x12D0C | 0x0034545B | 0x00000013 (NOP) |
| F4  | 0x12D78 | 0x0044545B | 0x00000013 (NOP) |
| F5  | 0x12D24 | 0x0054545B | 0x00000013 (NOP) |
| F6  | 0x12D4C | 0x0064545B | 0x00000013 (NOP) |
| F7  | 0x12CBC | 0x0074545B | 0x00000013 (NOP) |
| F8  | 0x12CCC | 0x0084545B | 0x00000013 (NOP) |
| F9  | 0x12CDC | 0x0094545B | 0x00000013 (NOP) |
| F10 | 0x12CEC | 0x00A4545B | 0x00000013 (NOP) |
| F11 | 0x129A0 | 0xB8B46E5B | 0xF9DFF06F (j 0x2001293c) |
| F12 | 0x12D64 | 0x00C4545B | 0x00000013 (NOP) |

CRC updated: 0xA7DA1601 → 0xA411C7EC

To flash:
```
python3 flash.py                        # uses crush80_telink_fw_patched.bin
python3 flash.py some_other.bin         # custom firmware file
python3 flash.py --list                 # list HID devices with VID=0x320F
```

May need `sudo` if udev rules don't allow user access to the OTA HID interface.

## Via Linux

To use via under linux, you need to chmod/chown the device to your user.
E.g.

```
sudo chmod 666 /dev/hidraw<device number>
sudo chown <user>:<group> /dev/hidraw<device number>
```
