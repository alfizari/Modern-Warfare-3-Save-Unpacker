import struct
import sys
import os
import re
import zlib

PRINTABLE = set(range(0x20, 0x7F))

ENTRY_SIZE = 0x28
NAME_SIZE  = 0x20

DIR_START   = 0x8
DIR_END     = 0x1408
FAT_START   = 0x1408
DATA_START  = 0x1BFC
SECTOR_SIZE = 0x400

TARGET_FILES = {"mpdata", "npdata"}

# ── Header we embed in every extracted file ──────────────────────────────────
# Magic: 4 bytes  "MWFS"
# Version: 2 bytes
# Entry offset in dir: 4 bytes  (so we know exactly where to patch file_size)
# Original file_size: 4 bytes
# Start sector: 2 bytes
# Num sectors: 2 bytes
# FAT chain: num_sectors * 6 bytes each  (sector u16, fat_offset u32, next u16)
# ─────────────────────────────────────────────────────────────────────────────
MAGIC   = b'MWFS'
VERSION = 1
HDR_FIXED_SIZE = 4 + 2 + 4 + 4 + 2 + 2   # = 18 bytes


def is_valid_name(raw):
    if not raw or raw[0] not in PRINTABLE:
        return False
    name_bytes = raw.split(b'\x00')[0]
    return len(name_bytes) > 0 and all(b in PRINTABLE for b in name_bytes)


# ── FAT ──────────────────────────────────────────────────────────────────────

def get_fat_chain(start_sector, full_data):
    chain = []
    current = start_sector
    while current not in (0xFFFF, 0x0000):
        if current in chain:
            print(f"[!] Circular FAT chain at sector 0x{current:04X}")
            break
        chain.append(current)
        fat_offset = FAT_START + (current * 2)
        current = struct.unpack_from("<H", full_data, fat_offset)[0]
    return chain


def build_fat_chain_info(chain, full_data):
    """Returns list of (sector, fat_offset, next_sector) for every link."""
    info = []
    for i, sector in enumerate(chain):
        fat_offset  = FAT_START + (sector * 2)
        next_val    = struct.unpack_from("<H", full_data, fat_offset)[0]
        info.append((sector, fat_offset, next_val))
    return info


# ── Custom header encode / decode ─────────────────────────────────────────────

def encode_header(entry_offset, orig_size, start_sector, chain_info):
    """
    Pack our custom header in front of the raw file data.
    chain_info: list of (sector u16, fat_offset u32, next u16)
    """
    num_sectors = len(chain_info)
    hdr = bytearray()
    hdr += MAGIC
    hdr += struct.pack("<H", VERSION)
    hdr += struct.pack("<I", entry_offset)   # dir entry offset → for patching
    hdr += struct.pack("<I", orig_size)
    hdr += struct.pack("<H", start_sector)
    hdr += struct.pack("<H", num_sectors)
    for (sec, fat_off, nxt) in chain_info:
        hdr += struct.pack("<H", sec)
        hdr += struct.pack("<I", fat_off)
        hdr += struct.pack("<H", nxt)
    return bytes(hdr)


def decode_header(data):
    """
    Parse our custom header.
    Returns (header_size, entry_offset, orig_size, start_sector, chain_info, payload)
    """
    if data[:4] != MAGIC:
        raise ValueError("Not a MWFS file — missing magic")

    version      = struct.unpack_from("<H", data, 4)[0]
    entry_offset = struct.unpack_from("<I", data, 6)[0]
    orig_size    = struct.unpack_from("<I", data, 10)[0]
    start_sector = struct.unpack_from("<H", data, 14)[0]
    num_sectors  = struct.unpack_from("<H", data, 16)[0]

    pos = 18
    chain_info = []
    for _ in range(num_sectors):
        sec     = struct.unpack_from("<H", data, pos)[0];     pos += 2
        fat_off = struct.unpack_from("<I", data, pos)[0];     pos += 4
        nxt     = struct.unpack_from("<H", data, pos)[0];     pos += 2
        chain_info.append((sec, fat_off, nxt))

    header_size = pos
    payload = data[header_size:]
    return header_size, entry_offset, orig_size, start_sector, chain_info, payload


# ── Parse directory ───────────────────────────────────────────────────────────

def parse_entries(full_data):
    dir_data = full_data[DIR_START:DIR_END]
    entries  = []
    i = 0
    while i <= len(dir_data) - ENTRY_SIZE:
        raw_name = dir_data[i:i + NAME_SIZE]
        if is_valid_name(raw_name):
            chunk     = dir_data[i:i + ENTRY_SIZE]
            name      = raw_name.split(b'\x00')[0].decode("ascii", errors="replace")
            file_size = struct.unpack_from("<I", chunk, 0x20)[0]
            sector    = struct.unpack_from("<H", chunk, 0x24)[0]
            flags     = struct.unpack_from("<H", chunk, 0x26)[0]
            entries.append({
                "offset":    i,
                "name":      name,
                "file_size": file_size,
                "sector":    sector,
                "flags":     flags,
            })
            i += ENTRY_SIZE
        else:
            i += 1
    return entries


# ── Unpack ────────────────────────────────────────────────────────────────────

def unpack(filepath, out_dir="unpacked"):
    with open(filepath, "rb") as f:
        full_data = bytearray(f.read())

    entries = parse_entries(full_data)
    os.makedirs(out_dir, exist_ok=True)

    for e in entries:
        if e["name"] not in TARGET_FILES:
            continue

        chain      = get_fat_chain(e["sector"], full_data)
        chain_info = build_fat_chain_info(chain, full_data)

        # Read raw sectors
        file_buffer = bytearray()
        for sector in chain:
            off = DATA_START + (sector * SECTOR_SIZE)
            file_buffer.extend(full_data[off:off + SECTOR_SIZE])

        raw_data = bytes(file_buffer[:e["file_size"]])

        # Build and prepend our header
        header  = encode_header(e["offset"], e["file_size"], e["sector"], chain_info)
        payload = header + raw_data

        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', e["name"]).strip()
        out_path  = os.path.join(out_dir, safe_name)
        with open(out_path, "wb") as f:
            f.write(payload)

        print(f"[+] Unpacked: {safe_name}")
        print(f"    entry_offset : 0x{e['offset']:06X}")
        print(f"    orig_size    : {e['file_size']} bytes")
        print(f"    start_sector : 0x{e['sector']:04X}")
        print(f"    sectors      : {len(chain)}")
        print(f"    header_size  : {len(header)} bytes")
        for sec, fat_off, nxt in chain_info:
            nxt_str = f"0x{nxt:04X}" if nxt not in (0xFFFF, 0x0000) else f"0x{nxt:04X} (END)"
            print(f"      sector=0x{sec:04X}  fat@0x{fat_off:04X}  next={nxt_str}")
        print()

    print(f"[+] Done. Unpacked to: {out_dir}/")


# ── Repack ────────────────────────────────────────────────────────────────────

def repack(dat_file, *edited_files):
    with open(dat_file, "rb") as f:
        full_data = bytearray(f.read())

    for edited_path in edited_files:
        with open(edited_path, "rb") as f:
            edited = f.read()

        hdr_size, entry_offset, orig_size, start_sector, chain_info, payload = decode_header(edited)

        new_size = len(payload)

        # Pad if smaller than original
        if new_size < orig_size:
            payload = payload + b'\x00' * (orig_size - new_size)
            new_size = orig_size
            print(f"[~] {os.path.basename(edited_path)}: padded to {new_size} bytes")

        chain         = [sec for (sec, _, _) in chain_info]
        total_capacity = len(chain) * SECTOR_SIZE

        if new_size > total_capacity:
            print(f"[!] {os.path.basename(edited_path)}: payload {new_size} bytes exceeds "
                  f"sector capacity {total_capacity} bytes — cannot repack without FAT reallocation")
            continue

        # Write data across sectors — preserve original bytes beyond payload in last sector
        written = 0
        remaining = new_size

        for i, sector in enumerate(chain):
            off = DATA_START + (sector * SECTOR_SIZE)
            is_last = (i == len(chain) - 1)

            if is_last:
                # Only overwrite the bytes we actually have — leave the rest untouched
                chunk = payload[written:written + remaining]
                full_data[off:off + len(chunk)] = chunk
            else:
                chunk = payload[written:written + SECTOR_SIZE]
                full_data[off:off + SECTOR_SIZE] = chunk

            written    += SECTOR_SIZE
            remaining  -= min(SECTOR_SIZE, remaining)

        # Patch file_size in directory entry
        dir_entry_abs = DIR_START + entry_offset + 0x20
        struct.pack_into("<I", full_data, dir_entry_abs, new_size)

        print(f"[+] Repacked: {os.path.basename(edited_path)}")
        print(f"    entry_offset : 0x{entry_offset:06X}")
        print(f"    new_size     : {new_size} bytes  (orig: {orig_size})")
        print(f"    sectors used : {len(chain)}")
        print(f"    last sector  : 0x{chain[-1]:04X} — wrote {new_size % SECTOR_SIZE or SECTOR_SIZE} bytes, "
              f"left {SECTOR_SIZE - (new_size % SECTOR_SIZE or SECTOR_SIZE)} bytes untouched")
        print()

    out_path = dat_file.replace(".dat", "_repacked.dat")
    with open(out_path, "wb") as f:
        f.write(full_data)
    print(f"[+] Written to: {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python unpack.py unpack <memory.dat>")
        print("  python unpack.py repack <memory.dat> <file1> [file2 ...]")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "unpack":
        unpack(sys.argv[2])

    elif mode == "repack":
        dat_file     = sys.argv[2]
        edited_files = sys.argv[3:]
        if not edited_files:
            print("[!] No edited files specified.")
            sys.exit(1)
        repack(dat_file, *edited_files)

    else:
        print(f"[!] Unknown mode: {mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()