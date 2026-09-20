#!/usr/bin/env python3
import struct
import os
import sys
import math

def align(size, page_size=4096):
    return math.ceil(size / page_size) * page_size

def swap_recovery_ramdisk(stock_vendor_boot, built_recovery_ramdisk, output_vendor_boot):
    print(f"[*] Reading stock vendor_boot: {stock_vendor_boot}")
    with open(stock_vendor_boot, "rb") as f:
        data = f.read()

    # Verify header
    magic = data[:8]
    if magic != b"VNDRBOOT":
        raise ValueError("Invalid vendor_boot magic!")

    header_version = struct.unpack("<I", data[8:12])[0]
    page_size = struct.unpack("<I", data[12:16])[0]
    kernel_addr = struct.unpack("<I", data[16:20])[0]
    ramdisk_addr = struct.unpack("<I", data[20:24])[0]
    old_vendor_ramdisk_size = struct.unpack("<I", data[24:28])[0]
    cmdline = data[28:2076]
    tags_addr = struct.unpack("<I", data[2076:2080])[0]
    name = data[2080:2096]
    header_size = struct.unpack("<I", data[2096:2100])[0]
    dtb_size = struct.unpack("<I", data[2100:2104])[0]
    dtb_addr = struct.unpack("<Q", data[2104:2112])[0]

    if header_version < 4:
        raise ValueError(f"Expected header v4, got v{header_version}")

    table_size = struct.unpack("<I", data[2112:2116])[0]
    entry_num = struct.unpack("<I", data[2116:2120])[0]
    entry_size = struct.unpack("<I", data[2120:2124])[0]
    bootconfig_size = struct.unpack("<I", data[2124:2128])[0]

    print(f"[+] Header v{header_version}, DTB size: {dtb_size}, Ramdisk table entries: {entry_num}")

    ramdisk_offset = page_size
    ramdisk_data = data[ramdisk_offset:ramdisk_offset + old_vendor_ramdisk_size]

    dtb_offset = ramdisk_offset + align(old_vendor_ramdisk_size, page_size)
    dtb_data = data[dtb_offset:dtb_offset + dtb_size]

    table_offset = dtb_offset + align(dtb_size, page_size)
    table_data = bytearray(data[table_offset:table_offset + table_size])

    bootconfig_offset = table_offset + align(table_size, page_size)
    bootconfig_data = data[bootconfig_offset:bootconfig_offset + bootconfig_size]

    entries = []
    for i in range(entry_num):
        off = i * entry_size
        e = table_data[off:off + entry_size]
        r_size, r_offset, r_type = struct.unpack("<III", e[:12])
        r_name = e[12:12+32].split(b"\x00")[0].decode("utf-8", errors="ignore")
        entries.append({
            "idx": i,
            "size": r_size,
            "offset": r_offset,
            "type": r_type,
            "name": r_name,
            "data": ramdisk_data[r_offset:r_offset + r_size]
        })
        print(f"  - Entry {i}: name='{r_name}', type={r_type}, size={r_size}")

    with open(built_recovery_ramdisk, "rb") as rf:
        new_rec_data = rf.read()
    print(f"[*] Loaded new recovery ramdisk: {len(new_rec_data)} bytes")

    replaced = False
    new_ramdisk_combined = bytearray()
    new_table_data = bytearray()

    for entry in entries:
        if entry["type"] == 2 or entry["name"] == "recovery":
            print(f"[+] Replacing Entry {entry['idx']} (recovery ramdisk) with new OrangeFox ramdisk...")
            new_offset = len(new_ramdisk_combined)
            new_size = len(new_rec_data)
            new_ramdisk_combined.extend(new_rec_data)

            updated_entry = bytearray(table_data[entry['idx']*entry_size : (entry['idx']+1)*entry_size])
            updated_entry[0:4] = struct.pack("<I", new_size)
            updated_entry[4:8] = struct.pack("<I", new_offset)
            new_table_data.extend(updated_entry)
            replaced = True
        else:
            new_offset = len(new_ramdisk_combined)
            new_size = len(entry["data"])
            new_ramdisk_combined.extend(entry["data"])

            updated_entry = bytearray(table_data[entry['idx']*entry_size : (entry['idx']+1)*entry_size])
            updated_entry[0:4] = struct.pack("<I", new_size)
            updated_entry[4:8] = struct.pack("<I", new_offset)
            new_table_data.extend(updated_entry)

    if not replaced:
        raise ValueError("Could not find recovery ramdisk entry in vendor_boot table!")

    new_vendor_ramdisk_size = len(new_ramdisk_combined)
    print(f"[*] New combined vendor ramdisk size: {new_vendor_ramdisk_size} bytes")

    header = bytearray(data[:page_size])
    header[24:28] = struct.pack("<I", new_vendor_ramdisk_size)

    out_img = bytearray()
    out_img.extend(header)
    out_img.extend(new_ramdisk_combined)
    out_img.extend(b"\x00" * (align(new_vendor_ramdisk_size, page_size) - new_vendor_ramdisk_size))
    out_img.extend(dtb_data)
    out_img.extend(b"\x00" * (align(dtb_size, page_size) - dtb_size))
    out_img.extend(new_table_data)
    out_img.extend(b"\x00" * (align(len(new_table_data), page_size) - len(new_table_data)))
    out_img.extend(bootconfig_data)
    out_img.extend(b"\x00" * (align(bootconfig_size, page_size) - bootconfig_size))

    PARTITION_SIZE = 67108864
    if len(out_img) > PARTITION_SIZE:
        raise ValueError(f"ERROR: Image size ({len(out_img)}) exceeds 64MB partition size ({PARTITION_SIZE})!")

    remaining_padding = PARTITION_SIZE - len(out_img)
    out_img.extend(b"\x00" * remaining_padding)

    with open(output_vendor_boot, "wb") as out_f:
        out_f.write(out_img)

    print(f"[SUCCESS] Wrote swapped image to {output_vendor_boot} ({len(out_img)} bytes, exactly 64MB).")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python swap_vendor_boot.py <stock_vendor_boot.img> <recovery_ramdisk.bin> <output_vendor_boot.img>")
        sys.exit(1)
    swap_recovery_ramdisk(sys.argv[1], sys.argv[2], sys.argv[3])
