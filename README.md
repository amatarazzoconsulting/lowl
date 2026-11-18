# lowl

**LOWL System Language Static Compiler** — compiles the LOWL systems language to
x86-64 assembly.

By Anthony Matarazzo (c) 2026 · MIT License

LOWL is a statically typed systems programming language aimed at Intel x86-64:
bare-metal kernels, protected-mode bootloaders and freestanding user code. The
compiler is a single self-contained Python 3 file with no third-party
dependencies.

```lowl
fn main() -> u32:
    let mut total: u64 = 0
    for i in 0..10:
        total = total + i
    return 0
```

## Requirements

* Python 3.8+
* [NASM](https://www.nasm.us/) to assemble the generated output (optional; the
  compiler emits text)

## Quick start

```sh
python3 lowlc.py test1.lowl -o output.asm
nasm -f elf64 output.asm -o output.o
ld output.o -o output
```

### Command line

```
python3 lowlc.py <input.lowl> [options]

  -o, --output FILE     Output assembly file (default: output.asm)
      --backend NAME    nasm | intel            (default: nasm)
  -O, --optimize N      0 | 1 | 2 | 3           (default: 2)
  -f, --format NAME     elf | flat | kernel | coff | boot   (default: elf)
  -v, --verbose         Verbose output
      --version         Print version
```

## Language overview

The full language reference is [`manual.txt`](manual.txt) (LOWL Language
Reference Manual v2.1.0, twenty chapters). Highlights:

* **Types** — `u8`–`u128`, `i8`–`i128`, `f32`/`f64`/`f80`, `bool`, `char`,
  `bit`, `string`, plus `array<T, N>`, `ptr<T>`, `ptr_mut<T>`, `mmio_ptr<T>`,
  `Option<T>`, tuples, function types and SIMD vectors (`vec4_f32`, `vec8_f32`,
  `vec16_f32`, `vec2_f64`, `vec4_f64`, `vec8_f64`).
* **Declarations** — `let`, `let mut`, `const`, `static`, `struct`, `class`
  with `private:`/`protected:`/`public:` sections, `extends`, `abstract`,
  `impl`, `virtual`/`override`, `template<class T>` with specialisations.
* **Control flow** — `if`/`elif`/`else`, `while`, `for k in a..b step s`,
  `for ch in string`, C-style `for (init; cond; step)`, `switch` with `case`,
  `case when (cond)` and `default`, `break`, `continue`.
* **Expressions** — `and`/`or`/`not`, bitwise operators, `as` casts with
  `saturating()`/`wrapping()`/`checked()` rounding modes, `**`, ranges,
  array/struct literals, lambdas (`fn(x: u64) -> u64: ...`), tuple
  destructuring.
* **Systems features** — inline `asm(...)`, `#[interrupt]`/`#[kernel]` handlers,
  `data_section`, BlockArray, SIMD pragmas, `port_read8`/`port_write8`,
  MSR/CR access, cache and prefetch builtins, ACPI/PCI/APIC/VM helpers.

## Boot sector demo

`-f boot` targets a 512-byte BIOS boot sector: 16-bit real mode, loaded at
`0x7C00`, closed with the `0xAA55` signature. [`boot_demo.lowl`](boot_demo.lowl)
boots, paints a bar straight into VGA text memory, prints text through the BIOS,
computes squares, counts down, reads a keystroke and halts.

```sh
python3 lowlc.py boot_demo.lowl -f boot -o boot.asm
python3 tools/build_boot_image.py boot.asm -o boot.img     # no nasm needed
qemu-system-x86_64 -drive format=raw,file=boot.img
```

Or with nasm, which also works because the output is ordinary NASM source:

```sh
nasm -f bin boot.asm -o boot.img
```

The boot back end compiles a real subset of the language rather than emitting a
fixed stub: `u8`/`u16` locals and globals, integer arithmetic and comparisons,
`if`/`elif`/`else`, `while`, `for i in a..b`, functions with up to three
parameters, string literals (with `\n`, `\r`, `\t`, `\0` and `\xNN` escapes),
inline `asm("...")`, and these builtins:

| Builtin | Effect |
| --- | --- |
| `print(s)` | Write a NUL-terminated string through BIOS teletype |
| `putc(c)` | Write one character |
| `newline()` | Carriage return and line feed |
| `clear_screen()` | BIOS video mode 3 |
| `read_key()` | Blocking BIOS keyboard read, returns the scan code in `ax` |
| `print_u16(n)` / `print_hex(n)` | Decimal and four-digit hex output |
| `delay(n)` | Busy-wait loop |
| `halt()` | `cli; hlt` |

Anything outside that subset (structs, arrays, floats, `switch`) is reported as
a compiler note instead of being silently miscompiled. Inline `asm` is the
escape hatch for segment:offset work such as the VGA text buffer.

`tools/build_boot_image.py` assembles the image without nasm: it encodes
label-relative branches itself (keystone sizes 16-bit calls as `rel32` while
computing a `rel16` displacement), pads to 510 bytes and writes the signature.

## Repository layout

| Path | Purpose |
| --- | --- |
| `lowlc.py` | The compiler: lexer, parser, semantic checks, optimiser, x86-64 code generator, CLI |
| `manual.txt` | Language reference manual (prose only) |
| `test1.lowl` … `test7.lowl` | Feature test programs (syntax, control flow, functions, OOP, conversions, SIMD, templates) |
| `tools/validate_asm.py` | Assembles every emitted instruction with Keystone to catch invalid output |
| `tools/build_boot_image.py` | Turns `-f boot` output into a 512-byte bootable image (no nasm required) |
| `boot_demo.lowl` | Boot sector demo: VGA bar, BIOS text, arithmetic, keyboard, halt |
| `LOWL System Language Static Compiler Part 1/2 - Proton Docs.pdf` | Original language design documents |

## Testing

Compile every test program and validate the generated instructions:

```sh
for f in test*.lowl; do python3 lowlc.py "$f" -o "out/${f%.lowl}.asm"; done
python3 tools/validate_asm.py out/*.asm
```

`tools/validate_asm.py` requires `keystone-engine` (`pip install keystone-engine`).
It skips directives and data definitions and substitutes symbol operands, so it
checks instruction encoding only — it is not a linker.

## Implementation status

The front end implements the documented grammar: all seven test programs parse
and compile with no diagnostics.

The code generator covers the core of the language:

* SysV AMD64 calling convention, stack frames, locals sized by type
* arrays, structs and classes with computed field offsets and layout
* indexing, member access, address-of, dereference, pointer arithmetic
* arithmetic, bitwise and comparison operators, including SSE scalar `f64`
* `if`/`elif`/`else`, all three `for` forms, `while`, `switch` with guards,
  `break`/`continue`
* function and method calls, overload selection, default parameters, implicit
  `self` receivers, `super.new(...)`
* `as` conversions between integer widths and between integer and `f64`
* string and float literals in `.rodata`, static data in `.data`/`.bss`

Not yet implemented, and reported in the generated assembly as comments rather
than silently miscompiled:

* SIMD vector arithmetic and the `vec*` builtin methods (`iota`, `broadcast`,
  `dot`, `fma`, horizontal reductions)
* `Option<T>` construction and pattern handling (`Option.some`/`Option.none`)
* virtual dispatch — `virtual`/`override` methods currently resolve statically
* `**` on integers, template specialisation selection, `BlockArray` operations
* returning structs by value (constructors return a pointer to scratch storage)
* more than six arguments per call

## License

MIT License. Copyright (c) 2026 Anthony Matarazzo.
