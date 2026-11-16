"""Check every compact Mach-O registry symbol against a SPIR-V inventory."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import struct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('generated_cpp', type=Path)
    parser.add_argument('object_file', type=Path)
    parser.add_argument('inventory', type=Path)
    args = parser.parse_args()
    entries = re.findall(r'\{"([^"]+)", ss_blob(\d+), (\d+)\}', args.generated_cpp.read_text())
    nm = subprocess.check_output(['nm', '-n', str(args.object_file)], text=True)
    symbols = {int(index): int(address, 16) for address, index in re.findall(r'^([0-9a-f]+) S _ss_blob(\d+)$', nm, re.M)}
    sections = subprocess.check_output(['otool', '-l', str(args.object_file)], text=True)
    match = re.search(r'sectname __const\s+segname __TEXT\s+addr (0x[0-9a-f]+)\s+size (0x[0-9a-f]+)\s+offset (\d+)', sections)
    if not match or not entries or len(entries) != len(symbols) or len({name for name, _, _ in entries}) != len(entries):
        raise ValueError('Invalid section, symbol or registry inventory')
    address, offset = int(match[1], 16), int(match[3])
    items = json.loads(args.inventory.read_text())['blobs']
    inventory = {Path(item['path']).name.removesuffix('.spv'): item for item in items}
    def has_int64(item):
        with Path(item['path']).open('rb') as blob:
            header = blob.read(20)
            if len(header) != 20 or struct.unpack_from('<I', header)[0] != 0x07230203:
                raise ValueError(f"Invalid SPIR-V header: {item['path']}")
            while True:
                word = blob.read(4)
                if len(word) != 4:
                    return False
                opcode, count = struct.unpack('<I', word)[0] & 0xffff, struct.unpack('<I', word)[0] >> 16
                if opcode != 17 or count < 2:
                    return False
                operands = blob.read((count - 1) * 4)
                if len(operands) != (count - 1) * 4:
                    raise ValueError('Truncated SPIR-V capability')
                if struct.unpack_from('<I', operands)[0] == 11:
                    return True

    expected = set(inventory)
    for name in inventory:
        if name.endswith('.noint64'):
            base = name
            while True:
                suffix = next((part for part in ('.noint64', '.int8', '.atomicadd') if base.endswith(part)), None)
                if not suffix:
                    break
                base = base[:-len(suffix)]
            if base not in inventory or not has_int64(inventory[base]):
                expected.remove(name)
    actual = {name for name, _, _ in entries}
    if actual != expected:
        raise ValueError(f'Registry selection mismatch: missing={sorted(expected - actual)} extra={sorted(actual - expected)}')
    with args.object_file.open('rb') as obj:
        for name, index, size in entries:
            item = inventory[name]
            if int(size) != item['bytes']:
                raise ValueError(f'Size mismatch: {name}')
            obj.seek(offset + symbols[int(index)] - address)
            if hashlib.sha256(obj.read(int(size))).hexdigest() != item['sha256']:
                raise ValueError(f'Embedded byte mismatch: {name}')
    print(f'Verified {len(entries)} unique registry entries against blob sizes and SHA-256 hashes')


if __name__ == '__main__':
    main()
