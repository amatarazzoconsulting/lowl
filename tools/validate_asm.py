#!/usr/bin/env python3
"""Validate lowl-generated NASM output without nasm installed.

Every instruction line is assembled with keystone (Intel syntax). Directives,
labels and data definitions are skipped, and symbol operands are substituted so
only the instruction encoding is checked. This catches syntactically invalid
instruction text; it is not a full assembler or linker.
"""
import re
import sys

from keystone import Ks, KS_ARCH_X86, KS_MODE_64

DIRECTIVE = re.compile(r'^\s*(bits|section|global|extern|align|org|times)\b', re.I)
DATA = re.compile(r'^\s*(db|dw|dd|dq|resb|resw|resd|resq)\b', re.I)
LABEL_LINE = re.compile(r'^\s*([.\w$@]+)\s*:\s*$')
SYMBOLISH = re.compile(r'(?<![A-Za-z0-9_$@.])([A-Za-z_.$@][\w.$@]*)')

REGISTERS = set('''rax rbx rcx rdx rsi rdi rbp rsp r8 r9 r10 r11 r12 r13 r14 r15
eax ebx ecx edx esi edi ebp esp r8d r9d r10d r11d
ax bx cx dx si di bp sp al bl cl dl ah bh ch dh
xmm0 xmm1 xmm2 xmm3 xmm4 xmm5 xmm6 xmm7 xmm8 xmm9 xmm10 xmm11 xmm12 xmm13 xmm14 xmm15 ymm0 ymm1 ymm2 ymm3 zmm0 zmm1 zmm2 zmm3
cl cs ds es ss byte word dword qword ptr xmmword ymmword zmmword'''.split())

MNEMONICS = set('''mov movzx movsx lea add sub imul mul idiv div and or xor not neg inc dec
cmp test jmp je jne jz jnz jg jge jl jle ja jae jb jbe jns js call ret push pop
sete setne setl setle setg setge seta setae setb setbe shl shr sar sal syscall
int iretq pushfq popfq nop cdq cqo mfence lfence sfence xchg
movq movd movsd addsd subsd mulsd divsd sqrtsd ucomisd comisd cvtsi2sd cvttsd2si
pxor xorps andps orps
rep repe repne cld std stosb stosd stosq movsb movsd_ movsq lodsb in out'''.split())


def collect_labels(path):
    labels = set()
    with open(path) as fh:
        for raw in fh:
            match = LABEL_LINE.match(raw.split(';')[0])
            if match:
                labels.add(match.group(1))
    return labels


def normalize(line, labels):
    def repl(match):
        word = match.group(1)
        low = word.lower()
        if low in REGISTERS or low in MNEMONICS:
            return word
        if re.fullmatch(r'[0-9].*', word):
            return word
        return 'target'

    line = re.sub(r'\b(byte|word|dword|qword)\s*\[', r'\1 ptr [', line)
    line = re.sub(r'\[[^\]]*\]', '[rax]', line)
    line = line.replace('movzx rax,', 'movzx eax,').replace('movzx rbx,', 'movzx ebx,')
    return SYMBOLISH.sub(repl, line)


def check(path):
    ks = Ks(KS_ARCH_X86, KS_MODE_64)
    labels = collect_labels(path)
    bad = []
    count = 0
    with open(path) as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.split(';')[0].strip()
            if not line or DIRECTIVE.match(line) or DATA.match(line) or LABEL_LINE.match(line):
                continue
            if line.endswith(':'):
                continue
            if ':' in line:
                head, _, tail = line.partition(':')
                if re.fullmatch(r'[.\w$@]+', head.strip()):
                    line = tail.strip()
                    if not line or DIRECTIVE.match(line) or DATA.match(line):
                        continue
            line = normalize(line, labels)
            count += 1
            try:
                ks.asm('target:\n' + line)
            except Exception as exc:  # noqa: BLE001
                bad.append((lineno, raw.rstrip(), str(exc).split('\n')[0]))
    return count, bad


def main():
    total_bad = 0
    for path in sys.argv[1:]:
        count, bad = check(path)
        status = "OK" if not bad else f"{len(bad)} invalid"
        print(f"{path}: {count} instructions, {status}")
        for lineno, line, err in bad[:6]:
            print(f"  line {lineno}: {line}\n    -> {err}")
        total_bad += len(bad)
    sys.exit(1 if total_bad else 0)


if __name__ == '__main__':
    main()
