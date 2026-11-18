#!/usr/bin/env python3
"""Assemble a lowl boot-sector .asm into a 512-byte boot image.

`nasm` is not required: instructions are assembled with keystone in 16-bit mode
and the `org`/`times`/data directives are handled here. Labels are resolved with
a two-pass loop that repeats until instruction sizes stop changing.

    python3 tools/build_boot_image.py boot.asm -o boot.img
"""
import argparse
import re
import sys

from keystone import Ks, KS_ARCH_X86, KS_MODE_16

ORIGIN = 0x7C00
LIMIT = 510

DIRECTIVE = re.compile(r'^\s*(bits|org|section|global|align)\b', re.I)
DATA = re.compile(r'^\s*(db|dw|dd|dq|resb|resw|resd|resq|times)\b', re.I)
SIGNATURE = re.compile(r'^\s*dw\s+0xAA55\s*$', re.I)
LABEL = re.compile(r'^\s*([.\w$@]+)\s*:\s*(.*)$')
BRANCH = re.compile(r'^(jmp|jz|jnz|je|jne|jb|jbe|ja|jae|jl|jle|jg|jge|jc|jnc|loop|call)\s+([.\w$@]+)$', re.I)
JCC8 = {'jz': 0x74, 'je': 0x74, 'jnz': 0x75, 'jne': 0x75, 'jb': 0x72, 'jc': 0x72,
        'jnc': 0x73, 'jae': 0x73, 'jbe': 0x76, 'ja': 0x77, 'jl': 0x7C,
        'jge': 0x7D, 'jle': 0x7E, 'jg': 0x7F}
JCC16 = {'jz': 0x84, 'je': 0x84, 'jnz': 0x85, 'jne': 0x85, 'jb': 0x82, 'jc': 0x82,
         'jnc': 0x83, 'jae': 0x83, 'jbe': 0x86, 'ja': 0x87, 'jl': 0x8C,
         'jge': 0x8D, 'jle': 0x8E, 'jg': 0x8F}


def load(path):
    """Split the source into ordered lines: ('label', name) / ('insn', text) / ('data', text)."""
    items = []
    with open(path) as fh:
        for raw in fh:
            line = raw.split(';')[0].strip()
            if not line or DIRECTIVE.match(line) or SIGNATURE.match(line):
                continue
            if line.startswith('times'):
                continue
            match = LABEL.match(line)
            if match and not DATA.match(line):
                name, rest = match.group(1), match.group(2).strip()
                items.append(('label', name))
                if rest:
                    kind = 'data' if DATA.match(rest) else 'insn'
                    items.append((kind, rest))
                continue
            if DATA.match(line):
                items.append(('data', line))
                continue
            items.append(('insn', line))
    return items


def assemble(items, addresses):
    """Assemble with the given label addresses; returns (bytes, label offsets)."""
    ks = Ks(KS_ARCH_X86, KS_MODE_16)

    here = {'ip': ORIGIN}

    def resolver(symbol, value):
        name = symbol.decode()
        # unknown symbols resolve to the current instruction, which keeps
        # relative displacements in range on the first pass; later passes
        # feed the real label addresses back in
        value[0] = addresses.get(name, here['ip'])
        return True

    ks.sym_resolver = resolver

    out = bytearray()
    labels = {}
    for kind, text in items:
        if kind == 'label':
            labels[text] = ORIGIN + len(out)
            continue
        if kind == 'data':
            out.extend(encode_data(text))
            continue
        here['ip'] = ORIGIN + len(out)
        # keystone's relative branches in 16-bit mode are unreliable (it sizes
        # calls as rel32 while computing a rel16 displacement), so every
        # label-relative branch is encoded here instead
        match = BRANCH.match(text)
        if match:
            out.extend(encode_branch(match.group(1).lower(), match.group(2),
                                     here['ip'], addresses))
            continue
        encoding, _ = ks.asm(text, addr=ORIGIN + len(out))
        if encoding is None:
            raise SystemExit(f"cannot assemble: {text}")
        out.extend(encoding)
    return bytes(out), labels


def encode_branch(mnemonic, symbol, ip, addresses):
    """Encode one label-relative branch; picks the shortest form that fits."""
    target = addresses.get(symbol, ip)

    if mnemonic == 'call':
        disp = (target - (ip + 3)) & 0xFFFF
        return b'\xE8' + disp.to_bytes(2, 'little')

    if mnemonic == 'jmp':
        disp = target - (ip + 2)
        if -128 <= disp <= 127:
            return bytes([0xEB, disp & 0xFF])
        disp = (target - (ip + 3)) & 0xFFFF
        return b'\xE9' + disp.to_bytes(2, 'little')

    if mnemonic == 'loop':
        disp = target - (ip + 2)
        if not -128 <= disp <= 127:
            raise SystemExit(f"loop target out of range: {symbol}")
        return bytes([0xE2, disp & 0xFF])

    disp = target - (ip + 2)
    if -128 <= disp <= 127:
        return bytes([JCC8[mnemonic], disp & 0xFF])
    disp = (target - (ip + 4)) & 0xFFFF
    return bytes([0x0F, JCC16[mnemonic]]) + disp.to_bytes(2, 'little')


def encode_data(text):
    out = bytearray()
    kind, _, operands = text.partition(' ')
    kind = kind.lower()
    if kind == 'db':
        for item in operands.split(','):
            item = item.strip()
            if not item:
                continue
            if item.startswith('"') and item.endswith('"'):
                out.extend(item[1:-1].encode('latin-1'))
            else:
                out.append(int(item, 0) & 0xFF)
    elif kind == 'dw':
        for item in operands.split(','):
            out.extend((int(item.strip(), 0) & 0xFFFF).to_bytes(2, 'little'))
    elif kind == 'resw':
        out.extend(b'\x00\x00' * int(operands.strip(), 0))
    elif kind == 'resb':
        out.extend(b'\x00' * int(operands.strip(), 0))
    return bytes(out)


def build(path):
    items = load(path)
    addresses = {}
    image = b''
    for _ in range(8):
        image, labels = assemble(items, addresses)
        if labels == addresses:
            break
        addresses = labels
    else:
        print("note: label addresses did not settle after 8 passes")
    return image, labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('asm_file')
    parser.add_argument('-o', '--output', default='boot.img')
    args = parser.parse_args()

    image, labels = build(args.asm_file)
    if len(image) > LIMIT:
        print(f"boot sector overflow: {len(image)} bytes of code+data, limit is {LIMIT}")
        return 1

    sector = bytearray(image) + b'\x00' * (LIMIT - len(image))
    sector += b'\x55\xAA'
    with open(args.output, 'wb') as fh:
        fh.write(sector)

    print(f"{args.asm_file}: {len(image)} bytes of code+data, {len(labels)} labels")
    print(f"{args.output}: {len(sector)} bytes, signature {sector[510]:02X}{sector[511]:02X}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
