#!/usr/bin/env python3
"""
lowl Compiler v2.1.0 - Systems Programming Language
Complete implementation with BlockArray, SIMD operations, optimization levels,
module system, executable loader, and advanced memory management.

Copyright (c) 2026 Anthony Matarazzo
All rights reserved.

Licensed under the MIT License.
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import sys
import re
import struct
import argparse
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple, Set
from enum import Enum
import os
import hashlib
import json
import csv
import xml.etree.ElementTree as ET
from pathlib import Path

VERSION_MAJOR = 2
VERSION_MINOR = 1
VERSION_PATCH = 0

# ============================================================================
# Enumerations and Configuration
# ============================================================================

class OptimizationLevel(Enum):
    O0 = 0
    O1 = 1
    O2 = 2
    O3 = 3

class Backend(Enum):
    NASM = 1
    INTEL_ASM = 2

class SIMDLevel(Enum):
    NONE = 0
    SSE = 1
    AVX = 2
    AVX512 = 3

class OutputFormat(Enum):
    FLAT_BINARY = 1
    KERNEL_MODULE = 2
    ELF_EXECUTABLE = 3
    COFF_OBJECT = 4
    BOOT_IMAGE = 5

class ProtectionRing(Enum):
    RING0_KERNEL = 0
    RING1_DRIVER = 1
    RING2_SERVICE = 2
    RING3_USER = 3

@dataclass
class LanguageConfig:
    equality_operator: str = "=="
    assignment_operator: str = "="
    string_delimiter: str = '"'
    char_delimiter: str = "'"
    line_comment: str = "//"
    block_comment_start: str = "/*"
    block_comment_end: str = "*/"
    case_sensitive: bool = True
    implicit_semicolon: bool = True

# ============================================================================
# Data Types
# ============================================================================

class DataType(Enum):
    U8 = 1; U16 = 2; U32 = 3; U64 = 4; U128 = 5
    I8 = 6; I16 = 7; I32 = 8; I64 = 9; I128 = 10
    F32 = 11; F64 = 12; F80 = 13
    BIT = 14; BOOL = 15; CHAR = 16
    PTR = 17; PTR_MUT = 18; MMIO_PTR = 19
    ARRAY = 20
    VOID = 21
    VEC4_F32 = 22; VEC2_F64 = 23; VEC8_F32 = 24; VEC4_F64 = 25
    VEC16_F32 = 26; VEC8_F64 = 27
    MASK8 = 28; MASK16 = 29; MASK64 = 30
    BLOCK_ARRAY = 31
    RB_MAP = 32
    RECORD = 33
    TEMPLATE = 34
    OPTION = 35
    MODULE = 36
    EXECUTABLE = 37

@dataclass
class DataTypeInfo:
    type: DataType
    size: int
    alignment: int
    name: str
    asm_name: str
    register_name: str
    mov_prefix: str
    simd_alignment: int
    instruction_set: str = ""

DATA_TYPE_TABLE = [
    DataTypeInfo(DataType.U8, 1, 1, "u8", "db", "al", "byte", 1),
    DataTypeInfo(DataType.U16, 2, 2, "u16", "dw", "ax", "word", 2),
    DataTypeInfo(DataType.U32, 4, 4, "u32", "dd", "eax", "dword", 4),
    DataTypeInfo(DataType.U64, 8, 8, "u64", "dq", "rax", "qword", 8),
    DataTypeInfo(DataType.I8, 1, 1, "i8", "db", "al", "byte", 1),
    DataTypeInfo(DataType.I16, 2, 2, "i16", "dw", "ax", "word", 2),
    DataTypeInfo(DataType.I32, 4, 4, "i32", "dd", "eax", "dword", 4),
    DataTypeInfo(DataType.I64, 8, 8, "i64", "dq", "rax", "qword", 8),
    DataTypeInfo(DataType.BIT, 1, 1, "bit", "db", "al", "byte", 1),
    DataTypeInfo(DataType.BOOL, 1, 1, "bool", "db", "al", "byte", 1),
    DataTypeInfo(DataType.CHAR, 1, 1, "char", "db", "al", "byte", 1),
    DataTypeInfo(DataType.F32, 4, 4, "f32", "dd", "xmm0", "dword", 16),
    DataTypeInfo(DataType.F64, 8, 8, "f64", "dq", "xmm0", "qword", 32),
    DataTypeInfo(DataType.PTR, 8, 8, "ptr", "dq", "rax", "qword", 8),
]

# ============================================================================
# Token Types
# ============================================================================

class TokenType(Enum):
    TOK_EOF = 0; TOK_ERROR = 1
    TOK_IDENTIFIER = 2; TOK_NUMBER = 3; TOK_STRING = 4; TOK_HEX = 5; TOK_BINARY = 6
    KW_LET = 10; KW_IF = 11; KW_ELIF = 12; KW_ELSE = 13; KW_WHILE = 14
    KW_FOR = 15; KW_IN = 16; KW_RANGE = 17; KW_RETURN = 18; KW_FN = 19
    KW_WITH = 20; KW_TRUE = 21; KW_FALSE = 22; KW_NULL = 23; KW_CONST = 24
    KW_CLASS = 25; KW_STRUCT = 26; KW_ENUM = 27; KW_EXTENDS = 28
    KW_THIS = 29; KW_SUPER = 30; KW_NEW = 31; KW_DELETE = 32
    KW_INLINE = 33; KW_VIRTUAL = 34; KW_OVERRIDE = 35
    KW_PUBLIC = 36; KW_PRIVATE = 37; KW_PROTECTED = 38
    KW_FROM = 39; KW_DEF = 40; KW_METADATA = 41
    KW_SWITCH = 42; KW_CASE = 43; KW_WHEN = 44; KW_PRIORITY = 45
    KW_DATA_SECTION = 46; KW_RECORD = 47; KW_KEY = 48; KW_RB_MAP = 49
    KW_COLUMNAR = 50; KW_INDENTED = 51; KW_END = 52
    KW_TEMPLATE = 53; KW_OPTION = 54; KW_SOME = 55; KW_NONE = 56
    KW_PCIDRIVER = 57; KW_REGISTER_DRIVER = 58; KW_REGISTER_INTERRUPT = 59
    KW_BLOCK_ARRAY = 60; KW_RB_MAP_TYPE = 61
    KW_IMPORT = 62; KW_EXPORT = 63; KW_MODULE = 64; KW_LOADER = 65
    KW_U8 = 100; KW_U16 = 101; KW_U32 = 102; KW_U64 = 103
    KW_I8 = 104; KW_I16 = 105; KW_I32 = 106; KW_I64 = 107
    KW_F32 = 108; KW_F64 = 109; KW_BOOL = 110; KW_CHAR = 111
    KW_PTR = 112; KW_MMIO_PTR = 113; KW_BIT = 114
    KW_VEC4_F32 = 115; KW_VEC8_F32 = 116; KW_VEC16_F32 = 117
    OP_ASSIGN = 200; OP_PLUS = 201; OP_MINUS = 202; OP_MULTIPLY = 203
    OP_DIVIDE = 204; OP_MOD = 205; OP_EQ = 206; OP_NE = 207; OP_LT = 208
    OP_LE = 209; OP_GT = 210; OP_GE = 211; OP_AND = 212; OP_OR = 213
    OP_NOT = 214; OP_BIT_AND = 215; OP_BIT_OR = 216; OP_BIT_XOR = 217
    OP_BIT_NOT = 218; OP_SHL = 219; OP_SHR = 220
    OP_INC = 221; OP_DEC = 222
    OP_PLUS_ASSIGN = 223; OP_MINUS_ASSIGN = 224
    OP_MULTIPLY_ASSIGN = 225; OP_DIVIDE_ASSIGN = 226
    OP_LPAREN = 250; OP_RPAREN = 251; OP_LBRACE = 252; OP_RBRACE = 253
    OP_LBRACKET = 254; OP_RBRACKET = 255; OP_COMMA = 256; OP_SEMICOLON = 257
    OP_COLON = 258; OP_DOT = 259; OP_ARROW = 260
    OP_CONVERT = 261
    NEWLINE = 300; INDENT = 301; DEDENT = 302
    OP_TEMPLATE_LT = 303; OP_TEMPLATE_GT = 304
    PRAGMA_OPTIMIZE = 400; PRAGMA_SIMD = 401

@dataclass
class Token:
    type: TokenType
    value: str
    line: int
    column: int
    file: str = ""

# ============================================================================
# AST Nodes
# ============================================================================

class ASTType(Enum):
    PROGRAM = 1; MODULE = 2; FUNCTION = 3; CLASS = 4
    BINARY_OP = 5; UNARY_OP = 6; LITERAL = 7; VARIABLE = 8; ASSIGN = 9
    IF_STMT = 10; WHILE_STMT = 11; FOR_STMT = 12; RETURN_STMT = 13
    BLOCK = 14; CALL = 15; MEMBER_ACCESS = 16; WITH_STMT = 17
    SWITCH_STMT = 18; CASE_STMT = 19
    DATA_SECTION = 20; RECORD_DEF = 21; RB_MAP_DECL = 22
    BUILTIN_CALL = 23; TEMPLATE_DECL = 24; TEMPLATE_INST = 25
    OPTION_TYPE = 26; METHOD_CALL = 27; DRIVER_DECL = 28
    BLOCK_ARRAY_TYPE = 29; BLOCK_ARRAY_METHOD = 30
    SIMD_OPERATION = 31; PRAGMA = 32
    IMPORT_STMT = 33; EXPORT_STMT = 34
    TYPE_CONVERSION = 35

@dataclass
class ASTNode:
    type: ASTType
    value: str = ""
    line: int = 0
    column: int = 0
    children: List['ASTNode'] = field(default_factory=list)
    data_type: DataType = DataType.VOID
    target_type: DataType = DataType.VOID
    conversion_method: str = ""
    template_params: List[str] = field(default_factory=list)
    function_params: List[DataType] = field(default_factory=list)
    function_return: DataType = DataType.VOID
    function_param_names: List[str] = field(default_factory=list)
    function_frame_size: int = 32
    record_fields: List[Tuple[str, DataType]] = field(default_factory=list)
    record_data: List[List[str]] = field(default_factory=list)
    map_key_fields: List[str] = field(default_factory=list)
    block_size: int = 256
    simd_level: SIMDLevel = SIMDLevel.NONE
    simd_mask: int = 0
    optimization_level: OptimizationLevel = OptimizationLevel.O2
    block_array_type: Optional[DataType] = None
    import_path: str = ""
    export_name: str = ""
    protection_ring: ProtectionRing = ProtectionRing.RING3_USER
    output_format: OutputFormat = OutputFormat.ELF_EXECUTABLE
    external_file: str = ""
    data_format: str = ""
    
    def add_child(self, child: 'ASTNode') -> None:
        if child:
            self.children.append(child)

# ============================================================================
# Symbol Table
# ============================================================================

@dataclass
class Symbol:
    name: str
    type: DataType
    scope_level: int
    stack_offset: int
    is_global: bool
    line: int
    column: int
    is_template: bool = False
    template_params: List[str] = field(default_factory=list)
    is_block_array: bool = False
    block_array_type: Optional[DataType] = None
    is_exported: bool = False
    is_imported: bool = False
    module_name: str = ""

class SymbolTable:
    def __init__(self):
        self.scopes: List[Dict[str, Symbol]] = [{}]
        self.current_scope = 0
        self.next_stack_offset = -8
        self.imported_symbols: Dict[str, str] = {}
        self.exported_symbols: Set[str] = set()
        
    def enter_scope(self) -> None:
        self.scopes.append({})
        self.current_scope = len(self.scopes) - 1
        
    def exit_scope(self) -> None:
        if len(self.scopes) > 1:
            self.scopes.pop()
            self.current_scope = len(self.scopes) - 1
    
    def reset_frame(self) -> None:
        self.next_stack_offset = -8
    
    def get_frame_size(self) -> int:
        used = -self.next_stack_offset - 8
        return max(32, ((used + 15) & ~15))
    
    def get_type_info(self, dtype: DataType) -> DataTypeInfo:
        for info in DATA_TYPE_TABLE:
            if info.type == dtype:
                return info
        return DATA_TYPE_TABLE[0]
            
    def declare(self, name: str, dtype: DataType, line: int, column: int, 
                is_global: bool = False, is_block_array: bool = False, 
                block_array_type: Optional[DataType] = None,
                is_exported: bool = False) -> bool:
        if name in self.scopes[self.current_scope]:
            return False
        
        type_info = self.get_type_info(dtype)
        size = type_info.size
        
        sym = Symbol(name=name, type=dtype, scope_level=self.current_scope,
                     stack_offset=self.next_stack_offset, is_global=is_global, 
                     line=line, column=column,
                     is_block_array=is_block_array, block_array_type=block_array_type,
                     is_exported=is_exported)
        if not is_global:
            alloc_size = max(8, ((size + 7) & ~7))
            self.next_stack_offset -= alloc_size
        self.scopes[self.current_scope][name] = sym
        
        if is_exported:
            self.exported_symbols.add(name)
        return True
        
    def lookup(self, name: str) -> Optional[Symbol]:
        for i in range(self.current_scope, -1, -1):
            if name in self.scopes[i]:
                return self.scopes[i][name]
        
        if name in self.imported_symbols:
            import_path = self.imported_symbols[name]
            return Symbol(name=name, type=DataType.U64, scope_level=0,
                         stack_offset=0, is_global=True, line=0, column=0,
                         is_imported=True, module_name=import_path)
        return None
    
    def add_import(self, name: str, module_path: str) -> None:
        self.imported_symbols[name] = module_path

# ============================================================================
# Error Reporter with Highlighting
# ============================================================================

class ErrorCollector:
    def __init__(self, source_lines: List[str] = None, filename: str = "<input>"):
        self.errors: List[Dict] = []
        self.warnings: List[Dict] = []
        self.source_lines = source_lines or []
        self.filename = filename
        
    def set_source(self, source: str) -> None:
        self.source_lines = source.split('\n')
        
    def add_error(self, msg: str, line: int, col: int) -> None:
        self.errors.append({
            'msg': msg,
            'line': line,
            'col': col,
            'file': self.filename
        })
        
    def add_warning(self, msg: str, line: int, col: int) -> None:
        self.warnings.append({
            'msg': msg,
            'line': line,
            'col': col,
            'file': self.filename
        })
        
    def has_errors(self) -> bool:
        return len(self.errors) > 0
        
    def _highlight_line(self, line_num: int, col: int) -> str:
        if line_num < 1 or line_num > len(self.source_lines):
            return ""
        line = self.source_lines[line_num - 1]
        caret_line = " " * (col - 1) + "^" if col > 0 else "^"
        return f"{line}\n{caret_line}"
        
    def print_summary(self) -> None:
        for w in self.warnings:
            print(f"\033[93mWarning\033[0m at {w['file']}:{w['line']}:{w['col']}: {w['msg']}")
            print(self._highlight_line(w['line'], w['col']))
            
        for e in self.errors:
            print(f"\033[91mError\033[0m at {e['file']}:{e['line']}:{e['col']}: {e['msg']}")
            print(self._highlight_line(e['line'], e['col']))
            
        if self.errors:
            print(f"\n\033[91m{len(self.errors)} error(s)\033[0m")
        if self.warnings:
            print(f"\033[93m{len(self.warnings)} warning(s)\033[0m")

# ============================================================================
# Memory Allocator with Hierarchical Tree and Protection Visitor
# ============================================================================

class MemoryType(Enum):
    USABLE = 1
    RESERVED = 2
    ACPI = 3
    NVS = 4
    BAD = 5
    KERNEL = 6
    USER = 7
    SHARED = 8

class PageFlags(Enum):
    PRESENT = 1 << 0
    WRITABLE = 1 << 1
    USER = 1 << 2
    WRITE_THRU = 1 << 3
    CACHE_DISABLE = 1 << 4
    ACCESSED = 1 << 5
    DIRTY = 1 << 6
    HUGE = 1 << 7
    GLOBAL = 1 << 8
    NO_EXECUTE = 1 << 63

@dataclass
class MemoryTreeNode:
    base: int
    length: int
    mem_type: MemoryType
    left: Optional['MemoryTreeNode'] = None
    right: Optional['MemoryTreeNode'] = None
    color: bool = True
    protection_flags: int = PageFlags.PRESENT.value | PageFlags.WRITABLE.value

class MemoryViolationVisitor:
    def visit_read_violation(self, address: int, rip: int) -> bool:
        return False
    def visit_write_violation(self, address: int, rip: int) -> bool:
        return False
    def visit_exec_violation(self, address: int, rip: int) -> bool:
        return False
    def visit_user_violation(self, address: int, rip: int) -> bool:
        return False

class PhysicalAllocator:
    def __init__(self):
        self.root: Optional[MemoryTreeNode] = None
        self.page_size = 4096
        self.bitmap: Optional[bytes] = None
        self.total_pages = 0
        self.violation_handler: Optional[MemoryViolationVisitor] = None
        
    def init(self, memory_map: List[Tuple[int, int, MemoryType]]) -> bool:
        for base, length, mem_type in memory_map:
            self.register_region(base, length, mem_type)
        return True
        
    def register_region(self, base: int, length: int, mem_type: MemoryType) -> bool:
        node = MemoryTreeNode(base=base, length=length, mem_type=mem_type)
        self.root = self._insert(self.root, node)
        return True
        
    def _insert(self, root: Optional[MemoryTreeNode], node: MemoryTreeNode) -> MemoryTreeNode:
        if root is None:
            return node
        if node.base < root.base:
            root.left = self._insert(root.left, node)
        else:
            root.right = self._insert(root.right, node)
        return root
        
    def alloc_pages(self, count: int, flags: PageFlags) -> Optional[int]:
        return self._find_best_fit(self.root, count * self.page_size)
        
    def _find_best_fit(self, node: Optional[MemoryTreeNode], size: int) -> Optional[int]:
        if node is None:
            return None
        if node.length >= size and node.mem_type == MemoryType.USABLE:
            address = node.base
            node.base += size
            node.length -= size
            return address
        left_result = self._find_best_fit(node.left, size)
        if left_result:
            return left_result
        return self._find_best_fit(node.right, size)
        
    def free_pages(self, address: int, count: int) -> bool:
        node = MemoryTreeNode(base=address, length=count * self.page_size, mem_type=MemoryType.USABLE)
        self.root = self._insert(self.root, node)
        return True
        
    def set_violation_handler(self, handler: MemoryViolationVisitor) -> None:
        self.violation_handler = handler
        
    def handle_page_fault(self, address: int, rip: int, error_code: int) -> bool:
        if self.violation_handler is None:
            return False
            
        is_write = (error_code & 2) != 0
        is_user = (error_code & 4) != 0
        is_exec = (error_code & 16) != 0
        
        if is_exec:
            return self.violation_handler.visit_exec_violation(address, rip)
        elif is_write:
            return self.violation_handler.visit_write_violation(address, rip)
        elif is_user:
            return self.violation_handler.visit_user_violation(address, rip)
        else:
            return self.violation_handler.visit_read_violation(address, rip)

# ============================================================================
# Module System and Executable Loader
# ============================================================================

@dataclass
class ModuleHeader:
    magic: int = 0x4C4F574C
    version: int = (VERSION_MAJOR << 16) | (VERSION_MINOR << 8) | VERSION_PATCH
    entry_point: int = 0
    text_offset: int = 0
    text_size: int = 0
    data_offset: int = 0
    data_size: int = 0
    rodata_offset: int = 0
    rodata_size: int = 0
    bss_size: int = 0
    symbol_count: int = 0
    import_count: int = 0
    export_count: int = 0
    protection_ring: int = 3
    checksum: int = 0

class ExecutableLoader:
    def __init__(self, allocator: PhysicalAllocator):
        self.allocator = allocator
        self.loaded_modules: Dict[str, int] = {}
        
    def load_module(self, module_path: str, ring: ProtectionRing) -> Optional[int]:
        if not os.path.exists(module_path):
            return None
            
        with open(module_path, 'rb') as f:
            data = f.read()
            
        header = ModuleHeader()
        header_size = struct.calcsize('IIIIIIIIIIIII')
        header_data = data[:header_size]
        
        fields = struct.unpack('I I I I I I I I I I I I I', header_data)
        header.magic = fields[0]
        header.version = fields[1]
        header.entry_point = fields[2]
        header.text_offset = fields[3]
        header.text_size = fields[4]
        header.data_offset = fields[5]
        header.data_size = fields[6]
        header.rodata_offset = fields[7]
        header.rodata_size = fields[8]
        header.bss_size = fields[9]
        header.symbol_count = fields[10]
        header.import_count = fields[11]
        header.export_count = fields[12]
        header.protection_ring = fields[13] if len(fields) > 13 else ring.value
        header.checksum = fields[14] if len(fields) > 14 else 0
        
        if header.magic != 0x4C4F574C:
            return None
            
        text_pages = (header.text_size + 4095) // 4096
        data_pages = (header.data_size + 4095) // 4096
        rodata_pages = (header.rodata_size + 4095) // 4096
        bss_pages = (header.bss_size + 4095) // 4096
        
        flags = PageFlags.PRESENT
        if ring == ProtectionRing.RING0_KERNEL:
            flags |= PageFlags.WRITABLE
        elif ring == ProtectionRing.RING3_USER:
            flags |= PageFlags.USER
        
        text_addr = self.allocator.alloc_pages(text_pages, flags)
        data_addr = self.allocator.alloc_pages(data_pages, flags | PageFlags.WRITABLE)
        rodata_addr = self.allocator.alloc_pages(rodata_pages, flags)
        bss_addr = self.allocator.alloc_pages(bss_pages, flags | PageFlags.WRITABLE)
        
        if text_addr:
            self._copy_to_memory(text_addr, data[header.text_offset:header.text_offset + header.text_size])
        if data_addr:
            self._copy_to_memory(data_addr, data[header.data_offset:header.data_offset + header.data_size])
        if rodata_addr:
            self._copy_to_memory(rodata_addr, data[header.rodata_offset:header.rodata_offset + header.rodata_size])
        if bss_addr:
            self._zero_memory(bss_addr, header.bss_size)
            
        module_base = text_addr if text_addr else 0
        self.loaded_modules[module_path] = module_base
        return module_base + header.entry_point
        
    def _copy_to_memory(self, addr: int, data: bytes) -> None:
        import ctypes
        ctypes.memmove(addr, data, len(data))
        
    def _zero_memory(self, addr: int, size: int) -> None:
        import ctypes
        ctypes.memset(addr, 0, size)
        
    def resolve_import(self, module_path: str, symbol_name: str) -> Optional[int]:
        if module_path not in self.loaded_modules:
            return None
        return self.loaded_modules[module_path]
        
    def execute_module(self, module_path: str, ring: ProtectionRing, args: List[int] = None) -> int:
        entry = self.load_module(module_path, ring)
        if entry is None:
            return -1
            
        import ctypes
        
        if ring == ProtectionRing.RING0_KERNEL:
            ctypes.CFUNCTYPE(ctypes.c_int)(entry)()
        else:
            user_func = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p))
            argc = len(args) if args else 0
            argv = (ctypes.c_char_p * (argc + 1))()
            if args:
                for i, arg in enumerate(args):
                    argv[i] = ctypes.c_char_p(str(arg).encode())
            user_func(entry)(argc, argv)
            
        return 0

# ============================================================================
# Data Section with External File Support and Grid Traversal
# ============================================================================

class DataSection:
    def __init__(self, name: str):
        self.name = name
        self.grid: List[List[str]] = []
        self.column_names: List[str] = []
        self.records: Dict[str, Any] = {}
        
    def load_csv(self, path: str) -> bool:
        try:
            with open(path, 'r') as f:
                reader = csv.reader(f)
                rows = list(reader)
                if rows:
                    self.column_names = rows[0]
                    self.grid = rows[1:]
            return True
        except Exception:
            return False
            
    def load_json(self, path: str) -> bool:
        try:
            with open(path, 'r') as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    self.column_names = list(data[0].keys()) if data else []
                    self.grid = [[str(item.get(col, "")) for col in self.column_names] for item in data]
            return True
        except Exception:
            return False
            
    def load_xml(self, path: str, record_path: str = "") -> bool:
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            if record_path:
                elements = root.findall(record_path)
            else:
                elements = list(root)
            if elements:
                self.column_names = list(elements[0].attrib.keys())
                self.grid = [[elem.attrib.get(col, "") for col in self.column_names] for elem in elements]
            return True
        except Exception:
            return False
            
    def load_yaml(self, path: str) -> bool:
        try:
            import yaml
            with open(path, 'r') as f:
                data = yaml.safe_load(f)
                if isinstance(data, list) and data:
                    self.column_names = list(data[0].keys()) if data else []
                    self.grid = [[str(item.get(col, "")) for col in self.column_names] for item in data]
            return True
        except Exception:
            return False
            
    def load_toml(self, path: str) -> bool:
        try:
            import tomli
            with open(path, 'rb') as f:
                data = tomli.load(f)
                if isinstance(data, dict):
                    self.column_names = list(data.keys())
                    self.grid = [[str(data.get(col, ""))]] if self.column_names else []
            return True
        except Exception:
            return False
            
    def row_count(self) -> int:
        return len(self.grid)
        
    def column_count(self) -> int:
        return len(self.column_names) if self.grid else 0
        
    def cell(self, row: int, col: int) -> str:
        if 0 <= row < len(self.grid) and 0 <= col < len(self.column_names):
            return self.grid[row][col]
        return ""
        
    def cell_by_name(self, row: int, column_name: str) -> str:
        if column_name in self.column_names:
            col_idx = self.column_names.index(column_name)
            return self.cell(row, col_idx)
        return ""
        
    def column(self, name: str) -> List[str]:
        if name in self.column_names:
            col_idx = self.column_names.index(name)
            return [row[col_idx] for row in self.grid]
        return []
        
    def filter_rows(self, predicate) -> 'DataSection':
        result = DataSection(f"{self.name}_filtered")
        result.column_names = self.column_names
        result.grid = [row for i, row in enumerate(self.grid) if predicate(i, row)]
        return result
        
    def export_csv(self, path: str) -> bool:
        try:
            with open(path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(self.column_names)
                writer.writerows(self.grid)
            return True
        except Exception:
            return False

# ============================================================================
# Lexer
# ============================================================================

class Lexer:
    def __init__(self, source: str, filename: str, config: LanguageConfig, errors: ErrorCollector):
        self.source = source
        self.filename = filename
        self.config = config
        self.pos = 0
        self.line = 1
        self.column = 1
        self.errors = errors
        
    def current(self) -> str:
        return self.source[self.pos] if self.pos < len(self.source) else '\0'
        
    def peek(self) -> str:
        return self.source[self.pos + 1] if self.pos + 1 < len(self.source) else '\0'
        
    def advance(self) -> None:
        if self.current() == '\n':
            self.line += 1
            self.column = 0
        self.pos += 1
        self.column += 1
        
    def skip_whitespace(self) -> None:
        while self.current() in ' \t\r':
            self.advance()
            
    def read_number(self) -> Token:
        start_line, start_col = self.line, self.column
        num = ""
        if self.current() == '0' and self.peek() in 'xX':
            self.advance(); self.advance()
            while self.current().isdigit() or self.current().lower() in 'abcdef':
                num += self.current()
                self.advance()
            return Token(TokenType.TOK_HEX, num, start_line, start_col, self.filename)
        if self.current() == '0' and self.peek() in 'bB':
            self.advance(); self.advance()
            while self.current() in '01':
                num += self.current()
                self.advance()
            return Token(TokenType.TOK_BINARY, num, start_line, start_col, self.filename)
        while self.current().isdigit() or self.current() == '.':
            num += self.current()
            self.advance()
        return Token(TokenType.TOK_NUMBER, num, start_line, start_col, self.filename)
        
    def read_string(self) -> Token:
        start_line, start_col = self.line, self.column
        delim = self.current()
        self.advance()
        s = ""
        while self.current() != delim and self.current() != '\0':
            if self.current() == '\\':
                self.advance()
                if self.current() == 'n': s += '\n'
                elif self.current() == 't': s += '\t'
                elif self.current() == '\\': s += '\\'
                elif self.current() == '"': s += '"'
                elif self.current() == "'": s += "'"
                else: s += self.current()
            else:
                s += self.current()
            self.advance()
        if self.current() == delim:
            self.advance()
        return Token(TokenType.TOK_STRING, s, start_line, start_col, self.filename)
    
    def read_pragma(self) -> Token:
        start_line, start_col = self.line, self.column
        self.advance()
        pragma_text = ""
        while self.current() != '\n' and self.current() != '\0':
            pragma_text += self.current()
            self.advance()
        
        if "optimize" in pragma_text.lower():
            if "O0" in pragma_text:
                return Token(TokenType.PRAGMA_OPTIMIZE, "O0", start_line, start_col, self.filename)
            elif "O1" in pragma_text:
                return Token(TokenType.PRAGMA_OPTIMIZE, "O1", start_line, start_col, self.filename)
            elif "O2" in pragma_text:
                return Token(TokenType.PRAGMA_OPTIMIZE, "O2", start_line, start_col, self.filename)
            elif "O3" in pragma_text:
                return Token(TokenType.PRAGMA_OPTIMIZE, "O3", start_line, start_col, self.filename)
        elif "simd" in pragma_text.lower():
            if "sse" in pragma_text.lower():
                return Token(TokenType.PRAGMA_SIMD, "SSE", start_line, start_col, self.filename)
            elif "avx2" in pragma_text.lower() or "avx" in pragma_text.lower():
                return Token(TokenType.PRAGMA_SIMD, "AVX", start_line, start_col, self.filename)
            elif "avx512" in pragma_text.lower():
                return Token(TokenType.PRAGMA_SIMD, "AVX512", start_line, start_col, self.filename)
        
        return Token(TokenType.TOK_ERROR, pragma_text, start_line, start_col, self.filename)
    
    def read_conversion(self) -> Token:
        start_line, start_col = self.line, self.column
        self.advance()
        return Token(TokenType.OP_CONVERT, ":", start_line, start_col, self.filename)
        
    def read_identifier(self) -> Token:
        start_line, start_col = self.line, self.column
        ident = ""
        while self.current().isalnum() or self.current() == '_':
            ident += self.current()
            self.advance()
            
        kw_map = {
            'let': TokenType.KW_LET, 'if': TokenType.KW_IF, 'else': TokenType.KW_ELSE,
            'while': TokenType.KW_WHILE, 'for': TokenType.KW_FOR, 'return': TokenType.KW_RETURN,
            'fn': TokenType.KW_FN, 'def': TokenType.KW_DEF, 'true': TokenType.KW_TRUE,
            'false': TokenType.KW_FALSE, 'null': TokenType.KW_NULL, 'const': TokenType.KW_CONST,
            'class': TokenType.KW_CLASS, 'struct': TokenType.KW_STRUCT, 'enum': TokenType.KW_ENUM,
            'extends': TokenType.KW_EXTENDS, 'this': TokenType.KW_THIS, 'super': TokenType.KW_SUPER,
            'new': TokenType.KW_NEW, 'delete': TokenType.KW_DELETE, 'inline': TokenType.KW_INLINE,
            'virtual': TokenType.KW_VIRTUAL, 'override': TokenType.KW_OVERRIDE,
            'public': TokenType.KW_PUBLIC, 'private': TokenType.KW_PRIVATE, 'protected': TokenType.KW_PROTECTED,
            'from': TokenType.KW_FROM, 'metadata': TokenType.KW_METADATA,
            'switch': TokenType.KW_SWITCH, 'case': TokenType.KW_CASE, 'when': TokenType.KW_WHEN,
            'priority': TokenType.KW_PRIORITY, 'data_section': TokenType.KW_DATA_SECTION,
            'record': TokenType.KW_RECORD, 'key': TokenType.KW_KEY, 'rb_map': TokenType.KW_RB_MAP,
            'columnar': TokenType.KW_COLUMNAR, 'indented': TokenType.KW_INDENTED, 'end': TokenType.KW_END,
            'template': TokenType.KW_TEMPLATE, 'Option': TokenType.KW_OPTION, 'some': TokenType.KW_SOME,
            'none': TokenType.KW_NONE, 'pcidriver': TokenType.KW_PCIDRIVER,
            'register_driver': TokenType.KW_REGISTER_DRIVER, 'register_interrupt': TokenType.KW_REGISTER_INTERRUPT,
            'block_array': TokenType.KW_BLOCK_ARRAY, 'rb_map_type': TokenType.KW_RB_MAP_TYPE,
            'with': TokenType.KW_WITH, 'BlockArray': TokenType.KW_BLOCK_ARRAY,
            'import': TokenType.KW_IMPORT, 'export': TokenType.KW_EXPORT, 'module': TokenType.KW_MODULE,
            'u8': TokenType.KW_U8, 'u16': TokenType.KW_U16, 'u32': TokenType.KW_U32, 'u64': TokenType.KW_U64,
            'i8': TokenType.KW_I8, 'i16': TokenType.KW_I16, 'i32': TokenType.KW_I32, 'i64': TokenType.KW_I64,
            'f32': TokenType.KW_F32, 'f64': TokenType.KW_F64, 'bool': TokenType.KW_BOOL, 'char': TokenType.KW_CHAR,
            'ptr': TokenType.KW_PTR, 'mmio_ptr': TokenType.KW_MMIO_PTR, 'bit': TokenType.KW_BIT,
            'vec4_f32': TokenType.KW_VEC4_F32, 'vec8_f32': TokenType.KW_VEC8_F32, 'vec16_f32': TokenType.KW_VEC16_F32,
        }
        
        if ident in kw_map:
            return Token(kw_map[ident], ident, start_line, start_col, self.filename)
        return Token(TokenType.TOK_IDENTIFIER, ident, start_line, start_col, self.filename)
        
    def read_operator(self) -> Token:
        start_line, start_col = self.line, self.column
        c = self.current()
        self.advance()
        
        if c == '=' and self.current() == '=':
            self.advance()
            return Token(TokenType.OP_EQ, "==", start_line, start_col, self.filename)
        if c == '!' and self.current() == '=':
            self.advance()
            return Token(TokenType.OP_NE, "!=", start_line, start_col, self.filename)
        if c == '<' and self.current() == '=':
            self.advance()
            return Token(TokenType.OP_LE, "<=", start_line, start_col, self.filename)
        if c == '>' and self.current() == '=':
            self.advance()
            return Token(TokenType.OP_GE, ">=", start_line, start_col, self.filename)
        if c == '&' and self.current() == '&':
            self.advance()
            return Token(TokenType.OP_AND, "&&", start_line, start_col, self.filename)
        if c == '|' and self.current() == '|':
            self.advance()
            return Token(TokenType.OP_OR, "||", start_line, start_col, self.filename)
        if c == '+' and self.current() == '+':
            self.advance()
            return Token(TokenType.OP_INC, "++", start_line, start_col, self.filename)
        if c == '-' and self.current() == '>':
            self.advance()
            return Token(TokenType.OP_ARROW, "->", start_line, start_col, self.filename)
        if c == '-' and self.current() == '-':
            self.advance()
            return Token(TokenType.OP_DEC, "--", start_line, start_col, self.filename)
        if c == '<' and self.current() == '<':
            self.advance()
            return Token(TokenType.OP_SHL, "<<", start_line, start_col, self.filename)
        if c == '>' and self.current() == '>':
            self.advance()
            return Token(TokenType.OP_SHR, ">>", start_line, start_col, self.filename)
        if c == '+' and self.current() == '=':
            self.advance()
            return Token(TokenType.OP_PLUS_ASSIGN, "+=", start_line, start_col, self.filename)
        if c == '-' and self.current() == '=':
            self.advance()
            return Token(TokenType.OP_MINUS_ASSIGN, "-=", start_line, start_col, self.filename)
        if c == '*' and self.current() == '=':
            self.advance()
            return Token(TokenType.OP_MULTIPLY_ASSIGN, "*=", start_line, start_col, self.filename)
        if c == '/' and self.current() == '=':
            self.advance()
            return Token(TokenType.OP_DIVIDE_ASSIGN, "/=", start_line, start_col, self.filename)
            
        op_map = {
            '=': TokenType.OP_ASSIGN, '+': TokenType.OP_PLUS, '-': TokenType.OP_MINUS,
            '*': TokenType.OP_MULTIPLY, '/': TokenType.OP_DIVIDE, '%': TokenType.OP_MOD,
            '<': TokenType.OP_LT, '>': TokenType.OP_GT, '&': TokenType.OP_BIT_AND,
            '|': TokenType.OP_BIT_OR, '^': TokenType.OP_BIT_XOR, '!': TokenType.OP_NOT,
            '~': TokenType.OP_BIT_NOT, '(': TokenType.OP_LPAREN, ')': TokenType.OP_RPAREN,
            '{': TokenType.OP_LBRACE, '}': TokenType.OP_RBRACE, '[': TokenType.OP_LBRACKET,
            ']': TokenType.OP_RBRACKET, ',': TokenType.OP_COMMA, ';': TokenType.OP_SEMICOLON,
            ':': TokenType.OP_COLON, '.': TokenType.OP_DOT,
        }
        if c in op_map:
            return Token(op_map[c], c, start_line, start_col, self.filename)
            
        return Token(TokenType.TOK_ERROR, c, start_line, start_col, self.filename)
        
    def next_token(self) -> Token:
        self.skip_whitespace()
        if self.pos >= len(self.source):
            return Token(TokenType.TOK_EOF, "", self.line, self.column, self.filename)
            
        if self.current() == '\n':
            self.advance()
            return Token(TokenType.NEWLINE, ";", self.line - 1, self.column, self.filename)
            
        if self.current() == '/' and self.peek() == '/':
            while self.current() != '\n' and self.current() != '\0':
                self.advance()
            return self.next_token()
            
        if self.current() == '/' and self.peek() == '*':
            self.advance(); self.advance()
            while not (self.current() == '*' and self.peek() == '/'):
                self.advance()
            self.advance(); self.advance()
            return self.next_token()
            
        if self.current() == '#':
            return self.read_pragma()
            
        if self.current().isdigit():
            return self.read_number()
            
        if self.current() == '"' or self.current() == "'":
            return self.read_string()
            
        if self.current().isalpha() or self.current() == '_':
            return self.read_identifier()
            
        if self.current() == ':' and self.peek() not in '=:':
            return self.read_conversion()
            
        return self.read_operator()

# ============================================================================
# Indentation Injection
# ============================================================================

def build_line_indents(source: str) -> Dict[int, int]:
    result: Dict[int, int] = {}
    for lineno, raw in enumerate(source.split('\n'), 1):
        stripped = raw.lstrip(' \t')
        if not stripped or stripped.startswith('//'):
            continue
        indent = 0
        for ch in raw:
            if ch == ' ':
                indent += 1
            elif ch == '\t':
                indent += 4
            else:
                break
        result[lineno] = indent
    return result

def inject_indent_dedent(tokens: List[Token], source: str) -> List[Token]:
    line_indents = build_line_indents(source)
    result: List[Token] = []
    indent_stack = [0]
    i = 0
    n = len(tokens)

    while i < n:
        tok = tokens[i]
        if tok.type == TokenType.NEWLINE:
            result.append(tok)
            i += 1
            while i < n and tokens[i].type == TokenType.NEWLINE:
                i += 1
            if i < n and tokens[i].type != TokenType.TOK_EOF:
                next_tok = tokens[i]
                next_indent = line_indents.get(next_tok.line, indent_stack[-1])
                curr_indent = indent_stack[-1]
                if next_indent > curr_indent:
                    indent_stack.append(next_indent)
                    result.append(Token(TokenType.INDENT, "", next_tok.line, 0, next_tok.file))
                elif next_indent < curr_indent:
                    while len(indent_stack) > 1 and indent_stack[-1] > next_indent:
                        indent_stack.pop()
                        result.append(Token(TokenType.DEDENT, "", next_tok.line, 0, next_tok.file))
        else:
            result.append(tok)
            i += 1

    while len(indent_stack) > 1:
        indent_stack.pop()
        result.append(Token(TokenType.DEDENT, "", 0, 0, ""))

    return result

# ============================================================================
# Parser
# ============================================================================

class Parser:
    def __init__(self, tokens: List[Token], symbols: SymbolTable, errors: ErrorCollector, 
                 opt_level: OptimizationLevel = OptimizationLevel.O2):
        self.tokens = tokens
        self.pos = 0
        self.symbols = symbols
        self.errors = errors
        self.current_opt_level = opt_level
        self.current_simd_level = SIMDLevel.NONE
        
    def current(self) -> Token:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else Token(TokenType.TOK_EOF, "", 0, 0, "")
        
    def advance(self) -> None:
        if self.pos < len(self.tokens):
            self.pos += 1
            
    def match(self, tok_type: TokenType) -> bool:
        if self.current().type == tok_type:
            self.advance()
            return True
        return False
        
    def expect(self, tok_type: TokenType, msg: str) -> bool:
        if self.current().type != tok_type:
            self.errors.add_error(msg, self.current().line, self.current().column)
            return False
        self.advance()
        return True
        
    def parse(self) -> ASTNode:
        program = ASTNode(ASTType.PROGRAM, "", 0, 0)
        while self.current().type != TokenType.TOK_EOF:
            stmt = self.parse_statement()
            if stmt:
                program.add_child(stmt)
            else:
                break
        return program
        
    def parse_statement(self) -> Optional[ASTNode]:
        tok = self.current()
        
        if tok.type == TokenType.PRAGMA_OPTIMIZE:
            return self.parse_pragma_optimize()
        elif tok.type == TokenType.PRAGMA_SIMD:
            return self.parse_pragma_simd()
        elif tok.type == TokenType.KW_IMPORT:
            return self.parse_import()
        elif tok.type == TokenType.KW_EXPORT:
            return self.parse_export()
        elif tok.type == TokenType.KW_MODULE:
            return self.parse_module()
        elif tok.type == TokenType.KW_LET:
            return self.parse_let()
        elif tok.type == TokenType.KW_FN or tok.type == TokenType.KW_DEF:
            return self.parse_function()
        elif tok.type == TokenType.KW_CLASS:
            return self.parse_class()
        elif tok.type == TokenType.KW_TEMPLATE:
            return self.parse_template()
        elif tok.type == TokenType.KW_IF:
            return self.parse_if()
        elif tok.type == TokenType.KW_WHILE:
            return self.parse_while()
        elif tok.type == TokenType.KW_FOR:
            return self.parse_for()
        elif tok.type == TokenType.KW_RETURN:
            return self.parse_return()
        elif tok.type == TokenType.KW_SWITCH:
            return self.parse_switch()
        elif tok.type == TokenType.KW_DATA_SECTION:
            return self.parse_data_section()
        elif tok.type == TokenType.KW_WITH:
            return self.parse_with()
        elif tok.type == TokenType.KW_BLOCK_ARRAY:
            return self.parse_block_array()
        elif tok.type == TokenType.OP_LBRACE:
            return self.parse_block()
        elif tok.type == TokenType.NEWLINE:
            self.advance()
            return self.parse_statement()
        elif tok.type == TokenType.INDENT:
            self.advance()
            return self.parse_statement()
        elif tok.type == TokenType.DEDENT:
            return None
        else:
            expr = self.parse_expression()
            self.match(TokenType.OP_SEMICOLON)
            return expr
    
    def parse_import(self) -> Optional[ASTNode]:
        node = ASTNode(ASTType.IMPORT_STMT, line=self.current().line, column=self.current().column)
        self.advance()
        
        if self.current().type == TokenType.TOK_STRING:
            node.import_path = self.current().value
            self.advance()
            
        if self.match(TokenType.KW_FROM):
            if self.current().type == TokenType.TOK_STRING:
                node.import_path = self.current().value
                self.advance()
                
        self.match(TokenType.OP_SEMICOLON)
        return node
        
    def parse_export(self) -> Optional[ASTNode]:
        node = ASTNode(ASTType.EXPORT_STMT, line=self.current().line, column=self.current().column)
        self.advance()
        
        if self.current().type == TokenType.TOK_IDENTIFIER:
            node.export_name = self.current().value
            self.symbols.exported_symbols.add(node.export_name)
            self.advance()
            
        self.match(TokenType.OP_SEMICOLON)
        return node
        
    def parse_module(self) -> Optional[ASTNode]:
        node = ASTNode(ASTType.MODULE, line=self.current().line, column=self.current().column)
        self.advance()
        
        if self.current().type == TokenType.TOK_IDENTIFIER:
            node.value = self.current().value
            self.advance()
            
        self.parse_indented_block(node)
        return node
        
    def parse_pragma_optimize(self) -> Optional[ASTNode]:
        tok = self.current()
        self.advance()
        node = ASTNode(ASTType.PRAGMA, tok.value, tok.line, tok.column)
        node.optimization_level = {
            "O0": OptimizationLevel.O0,
            "O1": OptimizationLevel.O1,
            "O2": OptimizationLevel.O2,
            "O3": OptimizationLevel.O3
        }.get(tok.value, OptimizationLevel.O2)
        self.current_opt_level = node.optimization_level
        return node
        
    def parse_pragma_simd(self) -> Optional[ASTNode]:
        tok = self.current()
        self.advance()
        node = ASTNode(ASTType.PRAGMA, tok.value, tok.line, tok.column)
        node.simd_level = {
            "SSE": SIMDLevel.SSE,
            "AVX": SIMDLevel.AVX,
            "AVX512": SIMDLevel.AVX512
        }.get(tok.value, SIMDLevel.NONE)
        self.current_simd_level = node.simd_level
        return node
        
    def parse_block_array(self) -> Optional[ASTNode]:
        node = ASTNode(ASTType.BLOCK_ARRAY_TYPE, line=self.current().line, column=self.current().column)
        self.advance()
        
        if self.match(TokenType.OP_LPAREN):
            if self.current().type in [TokenType.KW_F32, TokenType.KW_F64]:
                dtype = self.parse_type()
                node.block_array_type = dtype
            if self.match(TokenType.OP_COMMA):
                if self.current().type == TokenType.TOK_NUMBER:
                    node.block_size = int(self.current().value)
                    self.advance()
            self.expect(TokenType.OP_RPAREN, "Expected ')'")
        
        if self.match(TokenType.OP_ASSIGN):
            node.add_child(self.parse_expression())
        
        self.match(TokenType.OP_SEMICOLON)
        return node
        
    def parse_indented_block(self, node: ASTNode) -> None:
        while self.current().type == TokenType.NEWLINE:
            self.advance()
        if self.current().type == TokenType.INDENT:
            self.advance()
            while self.current().type != TokenType.DEDENT and self.current().type != TokenType.TOK_EOF:
                stmt = self.parse_statement()
                if stmt:
                    node.add_child(stmt)
                else:
                    break
            self.match(TokenType.DEDENT)
        
    def parse_template(self) -> Optional[ASTNode]:
        node = ASTNode(ASTType.TEMPLATE_DECL, line=self.current().line, column=self.current().column)
        
        if not self.expect(TokenType.KW_TEMPLATE, "Expected 'template'"):
            return None
        if not self.expect(TokenType.OP_TEMPLATE_LT, "Expected '<'"):
            return None
            
        while self.current().type == TokenType.KW_CLASS or self.current().type == TokenType.TOK_IDENTIFIER:
            if self.current().type == TokenType.KW_CLASS:
                self.advance()
            param_name = self.current().value
            self.advance()
            node.template_params.append(param_name)
            if not self.match(TokenType.OP_COMMA):
                break
                
        if not self.expect(TokenType.OP_TEMPLATE_GT, "Expected '>'"):
            return None
            
        if self.current().type == TokenType.KW_CLASS:
            class_node = self.parse_class()
            class_node.template_params = node.template_params
            node.add_child(class_node)
            
        return node
        
    def parse_class(self) -> Optional[ASTNode]:
        node = ASTNode(ASTType.CLASS, line=self.current().line, column=self.current().column)
        
        if not self.expect(TokenType.KW_CLASS, "Expected 'class'"):
            return None
            
        class_name = self.current().value
        if not self.expect(TokenType.TOK_IDENTIFIER, "Expected class name"):
            return None
        node.value = class_name
        
        if self.current().type == TokenType.OP_TEMPLATE_LT:
            self.advance()
            while self.current().type == TokenType.TOK_IDENTIFIER:
                node.template_params.append(self.current().value)
                self.advance()
                if not self.match(TokenType.OP_COMMA):
                    break
            self.expect(TokenType.OP_TEMPLATE_GT, "Expected '>'")
            
        if self.current().type == TokenType.KW_EXTENDS:
            self.advance()
            base_name = self.current().value
            self.advance()
            node.add_child(ASTNode(ASTType.VARIABLE, base_name, node.line, node.column))
            
        if not self.expect(TokenType.OP_COLON, "Expected ':'"):
            return None
            
        self.symbols.enter_scope()
        self.parse_indented_block(node)
        self.symbols.exit_scope()
        
        self.symbols.declare(class_name, DataType.RECORD, node.line, node.column, True)
        return node
        
    def parse_function(self) -> Optional[ASTNode]:
        node = ASTNode(ASTType.FUNCTION, line=self.current().line, column=self.current().column)
        node.optimization_level = self.current_opt_level
        node.simd_level = self.current_simd_level
        
        if self.current().type == TokenType.KW_DEF:
            self.advance()
        else:
            self.expect(TokenType.KW_FN, "Expected 'fn'")
            
        func_name = self.current().value
        if not self.expect(TokenType.TOK_IDENTIFIER, "Expected function name"):
            return None
        node.value = func_name
        
        if self.current().type == TokenType.OP_TEMPLATE_LT:
            self.advance()
            while self.current().type == TokenType.TOK_IDENTIFIER:
                node.template_params.append(self.current().value)
                self.advance()
                if not self.match(TokenType.OP_COMMA):
                    break
            self.expect(TokenType.OP_TEMPLATE_GT, "Expected '>'")
            
        self.expect(TokenType.OP_LPAREN, "Expected '('")
        
        param_names = []
        param_types = []
        while self.current().type == TokenType.TOK_IDENTIFIER:
            param_name = self.current().value
            self.advance()
            param_names.append(param_name)
            if self.match(TokenType.OP_COLON):
                param_types.append(self.parse_type())
            else:
                param_types.append(DataType.U64)
            if not self.match(TokenType.OP_COMMA):
                break
                
        self.expect(TokenType.OP_RPAREN, "Expected ')'")
        
        node.function_params = param_types
        node.function_param_names = param_names
        
        if self.match(TokenType.OP_ARROW):
            node.function_return = self.parse_type()
            
        self.symbols.reset_frame()
        self.symbols.enter_scope()
        
        for i, (name, ptype) in enumerate(zip(param_names, param_types)):
            self.symbols.declare(name, ptype, node.line, node.column, False)
            
        if self.match(TokenType.OP_COLON):
            while self.current().type == TokenType.NEWLINE:
                self.advance()
            if self.current().type == TokenType.INDENT:
                self.advance()
                while self.current().type != TokenType.DEDENT and self.current().type != TokenType.TOK_EOF:
                    stmt = self.parse_statement()
                    if stmt:
                        node.add_child(stmt)
                    else:
                        break
                self.match(TokenType.DEDENT)
        
        node.function_frame_size = self.symbols.get_frame_size()
        self.symbols.exit_scope()
        return node
        
    def parse_type(self) -> DataType:
        tok = self.current()
        type_map = {
            'u8': DataType.U8, 'u16': DataType.U16, 'u32': DataType.U32, 'u64': DataType.U64,
            'i8': DataType.I8, 'i16': DataType.I16, 'i32': DataType.I32, 'i64': DataType.I64,
            'f32': DataType.F32, 'f64': DataType.F64, 'bool': DataType.BOOL, 'char': DataType.CHAR,
            'bit': DataType.BIT, 'ptr': DataType.PTR, 'mmio_ptr': DataType.MMIO_PTR,
            'block_array': DataType.BLOCK_ARRAY, 'rb_map_type': DataType.RB_MAP,
            'Option': DataType.OPTION,
        }
        if tok.value in type_map:
            self.advance()
            if self.current().type == TokenType.OP_TEMPLATE_LT:
                self.advance()
                while self.current().type != TokenType.OP_TEMPLATE_GT and self.current().type != TokenType.TOK_EOF:
                    self.advance()
                self.expect(TokenType.OP_TEMPLATE_GT, "Expected '>'")
            return type_map[tok.value]
        self.advance()
        return DataType.U64
        
    def parse_type_conversion(self, obj: ASTNode) -> ASTNode:
        node = ASTNode(ASTType.TYPE_CONVERSION, ":", obj.line, obj.column)
        node.add_child(obj)
        
        target_type = self.parse_type()
        node.target_type = target_type
        
        if self.current().type == TokenType.OP_DOT:
            self.advance()
            if self.current().type == TokenType.TOK_IDENTIFIER:
                node.conversion_method = self.current().value
                self.advance()
        
        return node
        
    def parse_let(self) -> Optional[ASTNode]:
        node = ASTNode(ASTType.ASSIGN, line=self.current().line, column=self.current().column)
        
        if not self.expect(TokenType.KW_LET, "Expected 'let'"):
            return None
            
        var_name = self.current().value
        if not self.expect(TokenType.TOK_IDENTIFIER, "Expected variable name"):
            return None
            
        var_type = DataType.U64
        is_block_array = False
        block_array_type = None
        
        if self.current().type == TokenType.OP_COLON:
            self.advance()
            if self.current().type == TokenType.KW_BLOCK_ARRAY:
                self.advance()
                var_type = DataType.BLOCK_ARRAY
                is_block_array = True
                if self.match(TokenType.OP_LPAREN):
                    block_array_type = self.parse_type()
                    self.expect(TokenType.OP_RPAREN, "Expected ')'")
            else:
                var_type = self.parse_type()
            
        is_global = (self.symbols.current_scope == 0)
        self.symbols.declare(var_name, var_type, node.line, node.column, is_global, is_block_array, block_array_type)
        
        var_child = ASTNode(ASTType.VARIABLE, var_name, node.line, node.column)
        node.add_child(var_child)
        
        if self.match(TokenType.OP_ASSIGN):
            node.add_child(self.parse_expression())
        else:
            node.add_child(ASTNode(ASTType.LITERAL, "0", node.line, node.column))
            
        self.match(TokenType.OP_SEMICOLON)
        return node
        
    def parse_switch(self) -> Optional[ASTNode]:
        node = ASTNode(ASTType.SWITCH_STMT, line=self.current().line, column=self.current().column)
        
        if not self.expect(TokenType.KW_SWITCH, "Expected 'switch'"):
            return None
            
        if not self.expect(TokenType.OP_LPAREN, "Expected '('"):
            return None
        node.add_child(self.parse_expression())
        if not self.expect(TokenType.OP_RPAREN, "Expected ')'"):
            return None
            
        if not self.expect(TokenType.OP_COLON, "Expected ':'"):
            return None
            
        self.parse_indented_block(node)
        return node
        
    def parse_data_section(self) -> Optional[ASTNode]:
        node = ASTNode(ASTType.DATA_SECTION, line=self.current().line, column=self.current().column)
        
        if not self.expect(TokenType.KW_DATA_SECTION, "Expected 'data_section'"):
            return None
            
        if self.current().type == TokenType.KW_FROM:
            self.advance()
            if self.current().type == TokenType.TOK_STRING:
                node.external_file = self.current().value
                self.advance()
                
        if self.current().type == TokenType.TOK_IDENTIFIER:
            node.value = self.current().value
            self.advance()
            
        if self.match(TokenType.KW_COLUMNAR):
            node.data_format = "columnar"
        elif self.match(TokenType.KW_INDENTED):
            node.data_format = "indented"
        elif self.current().type == TokenType.TOK_IDENTIFIER:
            node.data_format = self.current().value
            self.advance()
            
        if not self.expect(TokenType.OP_COLON, "Expected ':'"):
            return None
            
        self.parse_indented_block(node)
        return node
        
    def get_precedence(self, tok_type: TokenType) -> int:
        prec_map = {
            TokenType.OP_ASSIGN: 1,
            TokenType.OP_PLUS_ASSIGN: 1, TokenType.OP_MINUS_ASSIGN: 1,
            TokenType.OP_MULTIPLY_ASSIGN: 1, TokenType.OP_DIVIDE_ASSIGN: 1,
            TokenType.OP_CONVERT: 2,
            TokenType.OP_AND: 3, TokenType.OP_OR: 3,
            TokenType.OP_EQ: 4, TokenType.OP_NE: 4,
            TokenType.OP_LT: 5, TokenType.OP_LE: 5, TokenType.OP_GT: 5, TokenType.OP_GE: 5,
            TokenType.OP_BIT_AND: 6, TokenType.OP_BIT_XOR: 7, TokenType.OP_BIT_OR: 8,
            TokenType.OP_PLUS: 9, TokenType.OP_MINUS: 9,
            TokenType.OP_MULTIPLY: 10, TokenType.OP_DIVIDE: 10, TokenType.OP_MOD: 10,
            TokenType.OP_SHL: 11, TokenType.OP_SHR: 11,
        }
        return prec_map.get(tok_type, 0)
        
    def parse_expression(self) -> Optional[ASTNode]:
        return self.parse_binary_op(0)
        
    def parse_binary_op(self, min_precedence: int) -> Optional[ASTNode]:
        left = self.parse_primary()
        if not left:
            return None
            
        while True:
            tok = self.current()
            precedence = self.get_precedence(tok.type)
            if precedence == 0 or precedence < min_precedence:
                break
            self.advance()
            
            if tok.type == TokenType.OP_CONVERT:
                left = self.parse_type_conversion(left)
            else:
                right = self.parse_binary_op(precedence + 1)
                if not right:
                    return None
                binary = ASTNode(ASTType.BINARY_OP, tok.value, tok.line, tok.column)
                binary.add_child(left)
                binary.add_child(right)
                left = binary
            
        return left
        
    def parse_primary(self) -> Optional[ASTNode]:
        tok = self.current()
        
        if tok.type == TokenType.TOK_NUMBER or tok.type == TokenType.TOK_HEX or tok.type == TokenType.TOK_BINARY:
            self.advance()
            node = ASTNode(ASTType.LITERAL, tok.value, tok.line, tok.column)
            node.data_type = DataType.U64
            return node
            
        if tok.type == TokenType.TOK_STRING:
            self.advance()
            node = ASTNode(ASTType.LITERAL, tok.value, tok.line, tok.column)
            node.data_type = DataType.CHAR
            return node
            
        if tok.type == TokenType.TOK_IDENTIFIER:
            self.advance()
            if tok.value in BUILTIN_FUNCTIONS:
                node = ASTNode(ASTType.BUILTIN_CALL, tok.value, tok.line, tok.column)
                if self.current().type == TokenType.OP_LPAREN:
                    self.advance()
                    while self.current().type != TokenType.OP_RPAREN and self.current().type != TokenType.TOK_EOF:
                        node.add_child(self.parse_expression())
                        if self.current().type == TokenType.OP_COMMA:
                            self.advance()
                    self.expect(TokenType.OP_RPAREN, "Expected ')'")
                return node
                
            var_node = ASTNode(ASTType.VARIABLE, tok.value, tok.line, tok.column)
            return self.parse_postfix(var_node)
            
        if tok.type == TokenType.KW_TRUE:
            self.advance()
            return ASTNode(ASTType.LITERAL, "1", tok.line, tok.column)
            
        if tok.type == TokenType.KW_FALSE:
            self.advance()
            return ASTNode(ASTType.LITERAL, "0", tok.line, tok.column)
            
        if tok.type == TokenType.KW_NULL:
            self.advance()
            return ASTNode(ASTType.LITERAL, "0", tok.line, tok.column)
            
        if tok.type == TokenType.KW_NEW:
            self.advance()
            return self.parse_constructor()
            
        if tok.type == TokenType.KW_BLOCK_ARRAY:
            self.advance()
            node = ASTNode(ASTType.BLOCK_ARRAY_TYPE, line=tok.line, column=tok.column)
            if self.match(TokenType.OP_LPAREN):
                node.block_array_type = self.parse_type()
                self.expect(TokenType.OP_RPAREN, "Expected ')'")
            return node
            
        if tok.type == TokenType.OP_LPAREN:
            self.advance()
            expr = self.parse_expression()
            self.expect(TokenType.OP_RPAREN, "Expected ')'")
            return expr
            
        self.errors.add_error(f"Unexpected token: {tok.value}", tok.line, tok.column)
        return None
        
    def parse_constructor(self) -> Optional[ASTNode]:
        class_name = self.current().value
        self.advance()
        
        node = ASTNode(ASTType.METHOD_CALL, "new", self.current().line, self.current().column)
        node.value = class_name
        
        if self.expect(TokenType.OP_LPAREN, "Expected '('"):
            while self.current().type != TokenType.OP_RPAREN and self.current().type != TokenType.TOK_EOF:
                node.add_child(self.parse_expression())
                if self.current().type == TokenType.OP_COMMA:
                    self.advance()
            self.expect(TokenType.OP_RPAREN, "Expected ')'")
        return node
        
    def parse_postfix(self, node: ASTNode) -> ASTNode:
        while True:
            if self.current().type == TokenType.OP_LBRACKET:
                self.advance()
                index = self.parse_expression()
                self.expect(TokenType.OP_RBRACKET, "Expected ']'")
                if self.current().type == TokenType.OP_ASSIGN:
                    op = self.current()
                    self.advance()
                    assign = ASTNode(ASTType.ASSIGN, op.value, op.line, op.column)
                    assign.add_child(node)
                    assign.add_child(self.parse_expression())
                    return assign
                node.children.append(index if index else ASTNode(ASTType.LITERAL, "0", node.line, node.column))
                return node
            elif self.current().type == TokenType.OP_DOT:
                self.advance()
                method_name = self.current().value
                self.advance()
                
                if self.current().type == TokenType.OP_LPAREN:
                    block_array_method = ASTNode(ASTType.BLOCK_ARRAY_METHOD, method_name, node.line, node.column)
                    block_array_method.add_child(node)
                    block_array_method.simd_level = self.current_simd_level
                    self.advance()
                    while self.current().type != TokenType.OP_RPAREN and self.current().type != TokenType.TOK_EOF:
                        block_array_method.add_child(self.parse_expression())
                        if self.current().type == TokenType.OP_COMMA:
                            self.advance()
                    self.expect(TokenType.OP_RPAREN, "Expected ')'")
                    return block_array_method
                else:
                    member = ASTNode(ASTType.MEMBER_ACCESS, method_name, node.line, node.column)
                    member.add_child(node)
                    return member
            elif self.current().type == TokenType.OP_LPAREN:
                call = ASTNode(ASTType.CALL, node.value, node.line, node.column)
                call.add_child(node)
                self.advance()
                while self.current().type != TokenType.OP_RPAREN:
                    call.add_child(self.parse_expression())
                    if self.current().type == TokenType.OP_COMMA:
                        self.advance()
                self.expect(TokenType.OP_RPAREN, "Expected ')'")
                node = call
            else:
                break
        return node
        
    def parse_if(self) -> Optional[ASTNode]:
        node = ASTNode(ASTType.IF_STMT, line=self.current().line, column=self.current().column)
        if not self.expect(TokenType.KW_IF, "Expected 'if'"):
            return None
        if not self.expect(TokenType.OP_LPAREN, "Expected '('"):
            return None
        node.add_child(self.parse_expression())
        if not self.expect(TokenType.OP_RPAREN, "Expected ')'"):
            return None
        self.parse_indented_block(node)
        
        if self.current().type == TokenType.KW_ELSE:
            self.advance()
            else_node = ASTNode(ASTType.BLOCK, line=self.current().line, column=self.current().column)
            self.parse_indented_block(else_node)
            node.add_child(else_node)
        return node
        
    def parse_while(self) -> Optional[ASTNode]:
        node = ASTNode(ASTType.WHILE_STMT, line=self.current().line, column=self.current().column)
        if not self.expect(TokenType.KW_WHILE, "Expected 'while'"):
            return None
        if not self.expect(TokenType.OP_LPAREN, "Expected '('"):
            return None
        node.add_child(self.parse_expression())
        if not self.expect(TokenType.OP_RPAREN, "Expected ')'"):
            return None
        self.parse_indented_block(node)
        return node
        
    def parse_for(self) -> Optional[ASTNode]:
        node = ASTNode(ASTType.FOR_STMT, line=self.current().line, column=self.current().column)
        if not self.expect(TokenType.KW_FOR, "Expected 'for'"):
            return None
        if not self.expect(TokenType.OP_LPAREN, "Expected '('"):
            return None
            
        if self.current().type == TokenType.KW_LET:
            node.add_child(self.parse_let())
        elif self.current().type != TokenType.OP_SEMICOLON:
            node.add_child(self.parse_expression())
        self.match(TokenType.OP_SEMICOLON)
        
        node.add_child(self.parse_expression())
        self.match(TokenType.OP_SEMICOLON)
        
        if self.current().type != TokenType.OP_RPAREN:
            node.add_child(self.parse_expression())
            
        if not self.expect(TokenType.OP_RPAREN, "Expected ')'"):
            return None
            
        body = ASTNode(ASTType.BLOCK, line=self.current().line, column=self.current().column)
        self.parse_indented_block(body)
        node.add_child(body)
        return node
        
    def parse_return(self) -> Optional[ASTNode]:
        node = ASTNode(ASTType.RETURN_STMT, line=self.current().line, column=self.current().column)
        if not self.expect(TokenType.KW_RETURN, "Expected 'return'"):
            return None
        if self.current().type not in (TokenType.OP_SEMICOLON, TokenType.NEWLINE, TokenType.DEDENT):
            node.add_child(self.parse_expression())
        self.match(TokenType.OP_SEMICOLON)
        return node
        
    def parse_with(self) -> Optional[ASTNode]:
        node = ASTNode(ASTType.WITH_STMT, line=self.current().line, column=self.current().column)
        if not self.expect(TokenType.KW_WITH, "Expected 'with'"):
            return None
        node.add_child(self.parse_expression())
        self.parse_indented_block(node)
        return node
        
    def parse_block(self) -> Optional[ASTNode]:
        node = ASTNode(ASTType.BLOCK, line=self.current().line, column=self.current().column)
        if not self.expect(TokenType.OP_LBRACE, "Expected '{'"):
            return None
            
        self.symbols.enter_scope()
        while self.current().type != TokenType.OP_RBRACE and self.current().type != TokenType.TOK_EOF:
            stmt = self.parse_statement()
            if stmt:
                node.add_child(stmt)
            else:
                break
        self.expect(TokenType.OP_RBRACE, "Expected '}'")
        self.symbols.exit_scope()
        return node

# ============================================================================
# Builtin Functions
# ============================================================================

BUILTIN_FUNCTIONS = {
    "port_write8": (1, DataType.VOID),
    "port_read8": (1, DataType.U8),
    "port_write16": (2, DataType.VOID),
    "port_read16": (1, DataType.U16),
    "port_write32": (2, DataType.VOID),
    "port_read32": (1, DataType.U32),
    "disable_interrupts": (0, DataType.VOID),
    "enable_interrupts": (0, DataType.VOID),
    "halt": (0, DataType.VOID),
    "pause": (0, DataType.VOID),
    "read_cr0": (0, DataType.U64),
    "write_cr0": (1, DataType.VOID),
    "read_cr2": (0, DataType.U64),
    "read_cr3": (0, DataType.U64),
    "write_cr3": (1, DataType.VOID),
    "invlpg": (1, DataType.VOID),
    "rdtsc": (0, DataType.U64),
    "rdtscp": (0, DataType.U64),
    "cpuid": (2, DataType.U32),
    "read_msr": (1, DataType.U64),
    "write_msr": (2, DataType.VOID),
    "mfence": (0, DataType.VOID),
    "lfence": (0, DataType.VOID),
    "sfence": (0, DataType.VOID),
    "prefetch": (2, DataType.VOID),
    "physical_alloc": (2, DataType.PTR),
    "physical_free": (1, DataType.VOID),
    "copy_memory": (3, DataType.VOID),
    "zero_memory": (2, DataType.VOID),
    "memcmp": (3, DataType.I32),
    "memchr": (3, DataType.PTR),
    "sqrt": (1, DataType.F64),
    "sin": (1, DataType.F64),
    "cos": (1, DataType.F64),
    "load_module": (2, DataType.PTR),
    "unload_module": (1, DataType.VOID),
    "resolve_symbol": (2, DataType.PTR),
}

# ============================================================================
# Optimizer
# ============================================================================

class Optimizer:
    def __init__(self, opt_level: OptimizationLevel):
        self.opt_level = opt_level
        
    def optimize(self, node: ASTNode) -> ASTNode:
        if self.opt_level == OptimizationLevel.O0:
            return node
        elif self.opt_level == OptimizationLevel.O1:
            return self.optimize_O1(node)
        elif self.opt_level == OptimizationLevel.O2:
            return self.optimize_O2(node)
        elif self.opt_level == OptimizationLevel.O3:
            return self.optimize_O3(node)
        return node
        
    def optimize_O1(self, node: ASTNode) -> ASTNode:
        node = self.constant_folding(node)
        node = self.dead_code_elimination(node)
        return node
        
    def optimize_O2(self, node: ASTNode) -> ASTNode:
        node = self.optimize_O1(node)
        node = self.loop_invariant_motion(node)
        return node
        
    def optimize_O3(self, node: ASTNode) -> ASTNode:
        node = self.optimize_O2(node)
        node = self.vectorize_loops(node)
        return node
        
    def constant_folding(self, node: ASTNode) -> ASTNode:
        if node.type == ASTType.BINARY_OP and len(node.children) == 2:
            left = node.children[0]
            right = node.children[1]
            if left.type == ASTType.LITERAL and right.type == ASTType.LITERAL:
                try:
                    lval = int(left.value)
                    rval = int(right.value)
                    if node.value == "+":
                        return ASTNode(ASTType.LITERAL, str(lval + rval), node.line, node.column)
                    elif node.value == "-":
                        return ASTNode(ASTType.LITERAL, str(lval - rval), node.line, node.column)
                    elif node.value == "*":
                        return ASTNode(ASTType.LITERAL, str(lval * rval), node.line, node.column)
                except ValueError:
                    pass
        for i, child in enumerate(node.children):
            node.children[i] = self.constant_folding(child)
        return node
        
    def dead_code_elimination(self, node: ASTNode) -> ASTNode:
        if node.type == ASTType.IF_STMT and len(node.children) > 0:
            cond = node.children[0]
            if cond.type == ASTType.LITERAL and cond.value == "0":
                if len(node.children) > 2:
                    return node.children[2]
                else:
                    return ASTNode(ASTType.BLOCK, line=node.line, column=node.column)
        for i, child in enumerate(node.children):
            node.children[i] = self.dead_code_elimination(child)
        return node
        
    def loop_invariant_motion(self, node: ASTNode) -> ASTNode:
        if node.type == ASTType.WHILE_STMT or node.type == ASTType.FOR_STMT:
            invariants = []
            for child in node.children:
                if child.type == ASTType.BINARY_OP:
                    invariants.append(child)
            for invariant in invariants:
                node.children.insert(0, invariant)
        for i, child in enumerate(node.children):
            node.children[i] = self.loop_invariant_motion(child)
        return node
        
    def vectorize_loops(self, node: ASTNode) -> ASTNode:
        if node.type == ASTType.FOR_STMT:
            if node.simd_level == SIMDLevel.NONE:
                node.simd_level = SIMDLevel.AVX512
        for i, child in enumerate(node.children):
            node.children[i] = self.vectorize_loops(child)
        return node

# ============================================================================
# Code Generator
# ============================================================================

class CodeGenerator:
    def __init__(self, backend: Backend, symbols: SymbolTable, opt_level: OptimizationLevel,
                 output_format: OutputFormat = OutputFormat.ELF_EXECUTABLE):
        self.backend = backend
        self.symbols = symbols
        self.opt_level = opt_level
        self.output_format = output_format
        self.text: List[str] = []
        self.data: List[str] = []
        self.bss: List[str] = []
        self.rodata: List[str] = []
        self.label_counter = 0
        self.indent = 1
        self.module_exports: Dict[str, int] = {}
        
    def new_label(self) -> str:
        self.label_counter += 1
        return f".L{self.label_counter - 1}"
        
    def get_mov_prefix(self, dtype: DataType) -> str:
        for info in DATA_TYPE_TABLE:
            if info.type == dtype:
                return info.mov_prefix
        return "qword"
        
    def get_register(self, dtype: DataType) -> str:
        for info in DATA_TYPE_TABLE:
            if info.type == dtype:
                return info.register_name
        return "rax"
        
    def emit(self, line: str, section: str = "text") -> None:
        indent = "    " * self.indent
        if section == "text":
            self.text.append(indent + line)
        elif section == "data":
            self.data.append(line)
        elif section == "bss":
            self.bss.append(line)
        elif section == "rodata":
            self.rodata.append(line)
            
    def emit_raw(self, line: str, section: str = "text") -> None:
        if section == "text":
            self.text.append(line)
        elif section == "data":
            self.data.append(line)
        elif section == "bss":
            self.bss.append(line)
        elif section == "rodata":
            self.rodata.append(line)
            
    def generate_header(self) -> None:
        self.emit_raw("; ============================================================================", "text")
        self.emit_raw("; lowl Compiler v2.1.0", "text")
        self.emit_raw("; Copyright (c) 2026 Anthony Matarazzo", "text")
        self.emit_raw("; Licensed under MIT License", "text")
        self.emit_raw("; System V AMD64 ABI", "text")
        self.emit_raw("; ============================================================================", "text")
        self.emit_raw("", "text")
        
        if self.output_format == OutputFormat.BOOT_IMAGE:
            self.emit_raw("bits 16", "text")
            self.emit_raw("org 0x7C00", "text")
            self.emit_raw("", "text")
            self.emit_raw("start:", "text")
            self.emit("cli", "text")
            self.emit("xor ax, ax", "text")
            self.emit("mov ss, ax", "text")
            self.emit("mov sp, 0x7C00", "text")
            self.emit("mov ds, ax", "text")
            self.emit("mov es, ax", "text")
            self.emit("sti", "text")
            self.emit("", "text")
            self.emit("mov si, boot_msg", "text")
            self.emit("call print", "text")
            self.emit("", "text")
            self.emit("jmp $", "text")
            self.emit("", "text")
            self.emit("print:", "text")
            self.emit("lodsb", "text")
            self.emit("or al, al", "text")
            self.emit("jz .done", "text")
            self.emit("mov ah, 0x0E", "text")
            self.emit("int 0x10", "text")
            self.emit("jmp print", "text")
            self.emit(".done:", "text")
            self.emit("ret", "text")
            self.emit("", "text")
            self.emit("boot_msg: db 'lowl v2.1.0 booting...', 0x0D, 0x0A, 0", "rodata")
            self.emit("", "text")
            self.emit("times 510 - ($ - $$) db 0", "text")
            self.emit("dw 0xAA55", "text")
            
        elif self.backend == Backend.NASM:
            self.emit_raw("bits 64", "text")
            self.emit_raw("section .text", "text")
            if self.output_format == OutputFormat.KERNEL_MODULE:
                self.emit_raw("global module_init", "text")
                self.emit_raw("global module_exit", "text")
            else:
                self.emit_raw("global main", "text")
            self.emit_raw("", "text")
            self.emit_raw("section .data", "data")
            self.emit_raw("section .bss", "bss")
            self.emit_raw("section .rodata", "rodata")
        else:
            self.emit_raw(".text", "text")
            self.emit_raw(".global main", "text")
            self.emit_raw("", "text")
            self.emit_raw(".data", "data")
            self.emit_raw(".bss", "bss")
            self.emit_raw(".rodata", "rodata")
            
        if self.output_format == OutputFormat.KERNEL_MODULE:
            self.emit_raw("", "text")
            self.emit_raw("module_init:", "text")
            self.emit("push rbp", "text")
            self.emit("mov rbp, rsp", "text")
            
    def generate_footer(self) -> None:
        if self.output_format == OutputFormat.KERNEL_MODULE:
            self.emit("", "text")
            self.emit_raw("module_exit:", "text")
            self.emit("push rbp", "text")
            self.emit("mov rbp, rsp", "text")
            self.emit("xor eax, eax", "text")
            self.emit("pop rbp", "text")
            self.emit("ret", "text")
            
    def generate(self, node: ASTNode) -> str:
        self.text.clear()
        self.data.clear()
        self.bss.clear()
        self.rodata.clear()
        
        optimizer = Optimizer(self.opt_level)
        node = optimizer.optimize(node)
        
        self.generate_header()
        
        for child in node.children:
            self.gen_statement(child)
            
        if len(self.text) < 10 and self.output_format != OutputFormat.BOOT_IMAGE:
            if self.output_format == OutputFormat.KERNEL_MODULE:
                self.emit_raw("module_init:", "text")
                self.emit("xor eax, eax", "text")
                self.emit("ret", "text")
            else:
                self.emit_raw("main:", "text")
                self.emit("xor eax, eax", "text")
                self.emit("ret", "text")
                
        self.generate_footer()
            
        result = "\n".join(self.text) + "\n\n"
        result += "\n".join(self.rodata) + "\n\n"
        result += "\n".join(self.data) + "\n\n"
        result += "\n".join(self.bss) + "\n"
        return result
        
    def gen_statement(self, node: ASTNode) -> None:
        if not node:
            return
            
        if node.type == ASTType.ASSIGN:
            self.gen_assign(node)
        elif node.type == ASTType.RETURN_STMT:
            self.gen_return(node)
        elif node.type == ASTType.IF_STMT:
            self.gen_if(node)
        elif node.type == ASTType.WHILE_STMT:
            self.gen_while(node)
        elif node.type == ASTType.FOR_STMT:
            self.gen_for(node)
        elif node.type == ASTType.FUNCTION:
            self.gen_function(node)
        elif node.type == ASTType.CLASS:
            for child in node.children:
                self.gen_statement(child)
        elif node.type == ASTType.CALL:
            self.gen_call(node)
        elif node.type == ASTType.BUILTIN_CALL:
            self.gen_builtin(node)
        elif node.type == ASTType.BLOCK:
            for child in node.children:
                self.gen_statement(child)
        elif node.type == ASTType.SWITCH_STMT:
            self.gen_switch(node)
        elif node.type == ASTType.WITH_STMT:
            self.gen_with(node)
        elif node.type == ASTType.BLOCK_ARRAY_TYPE:
            self.gen_block_array_decl(node)
        elif node.type == ASTType.BLOCK_ARRAY_METHOD:
            self.gen_block_array_method(node)
        elif node.type == ASTType.SIMD_OPERATION:
            self.gen_simd_operation(node)
        elif node.type == ASTType.IMPORT_STMT:
            self.gen_import(node)
        elif node.type == ASTType.EXPORT_STMT:
            self.gen_export(node)
        elif node.type == ASTType.TYPE_CONVERSION:
            self.gen_type_conversion(node)
            
    def gen_type_conversion(self, node: ASTNode) -> None:
        if len(node.children) < 1:
            self.emit("push 0", "text")
            return
            
        self.gen_expression(node.children[0])
        
        target_info = self.symbols.get_type_info(node.target_type)
        method = node.conversion_method
        
        if node.target_type in [DataType.U8, DataType.U16, DataType.U32, DataType.U64]:
            if method == "round":
                self.emit("pop rax", "text")
                self.emit("push rax", "text")
            elif method == "floor":
                self.emit("pop rax", "text")
                self.emit("push rax", "text")
            elif method == "ceil":
                self.emit("pop rax", "text")
                self.emit("push rax", "text")
            elif method == "trunc":
                self.emit("pop rax", "text")
                self.emit("push rax", "text")
            elif method == "saturating":
                self.emit("pop rax", "text")
                self.emit("push rax", "text")
            elif method == "wrapping":
                self.emit("pop rax", "text")
                self.emit("push rax", "text")
            else:
                self.emit("pop rax", "text")
                self.emit("push rax", "text")
                
    def gen_import(self, node: ASTNode) -> None:
        if node.import_path:
            self.symbols.add_import(node.value, node.import_path)
            self.emit(f"; Import from {node.import_path}", "text")
            
    def gen_export(self, node: ASTNode) -> None:
        if node.export_name:
            self.emit_raw(f"global {node.export_name}", "text")
            self.module_exports[node.export_name] = 0
            self.emit(f"; Export {node.export_name}", "text")
            
    def gen_block_array_decl(self, node: ASTNode) -> None:
        block_size = node.block_size if node.block_size > 0 else 64
        self.emit(f"; BlockArray declaration with {block_size} byte blocks", "text")
        alignment = 16
        if node.block_array_type == DataType.F64:
            alignment = 32
        elif node.block_array_type == DataType.F32:
            alignment = 16
        self.emit(f"align {alignment}", "data")
        
    def gen_block_array_method(self, node: ASTNode) -> None:
        method = node.value
        obj = node.children[0] if node.children else None
        
        if method == "push":
            if len(node.children) > 1:
                self.gen_expression(node.children[1])
                self.emit("pop rax", "text")
                self.emit("; BlockArray push operation", "text")
        elif method == "pop":
            self.emit("; BlockArray pop operation", "text")
            self.emit("mov rax, 0", "text")
            self.emit("push rax", "text")
        elif method == "len":
            self.emit("; BlockArray get length", "text")
            self.emit("mov rax, 0", "text")
            self.emit("push rax", "text")
        elif method == "capacity":
            self.emit("; BlockArray get capacity", "text")
            self.emit("mov rax, 0", "text")
            self.emit("push rax", "text")
        elif method == "merge_blocks":
            self.emit("; BlockArray merge blocks", "text")
        elif method == "rebalance":
            self.emit("; BlockArray rebalance", "text")
        elif method == "sse_permute":
            self.gen_simd_permute(SIMDLevel.SSE)
        elif method == "avx_permute":
            self.gen_simd_permute(SIMDLevel.AVX)
        elif method == "avx512_permute":
            self.gen_simd_permute(SIMDLevel.AVX512)
        elif method == "forward":
            self.emit("; Forward iterator", "text")
        elif method == "reverse":
            self.emit("; Reverse iterator", "text")
            
    def gen_simd_permute(self, level: SIMDLevel) -> None:
        if level == SIMDLevel.SSE:
            self.emit("pshufd xmm0, xmm0, 0b11010010", "text")
            self.emit("movdqu [rdi], xmm0", "text")
        elif level == SIMDLevel.AVX:
            self.emit("vpshufd ymm0, ymm0, 0b11010010", "text")
            self.emit("vmovdqu [rdi], ymm0", "text")
        elif level == SIMDLevel.AVX512:
            self.emit("vpshufd zmm0, zmm0, 0b11010010", "text")
            self.emit("vmovdqu64 [rdi], zmm0", "text")
            
    def gen_simd_operation(self, node: ASTNode) -> None:
        if node.simd_level == SIMDLevel.SSE:
            self.emit("movaps xmm0, [rdi]", "text")
            self.emit("addps xmm0, [rsi]", "text")
            self.emit("movaps [rdx], xmm0", "text")
        elif node.simd_level == SIMDLevel.AVX:
            self.emit("vmovaps ymm0, [rdi]", "text")
            self.emit("vaddps ymm0, ymm0, [rsi]", "text")
            self.emit("vmovaps [rdx], ymm0", "text")
        elif node.simd_level == SIMDLevel.AVX512:
            self.emit("vmovaps zmm0, [rdi]", "text")
            self.emit("vaddps zmm0, zmm0, [rsi]", "text")
            self.emit("vmovaps [rdx], zmm0", "text")
            
    def gen_builtin(self, node: ASTNode) -> None:
        name = node.value
        
        if name == "port_write8" and len(node.children) >= 2:
            self.gen_expression(node.children[0])
            self.gen_expression(node.children[1])
            self.emit("pop rdx", "text")
            self.emit("pop rcx", "text")
            self.emit("mov al, dl", "text")
            self.emit("mov dx, cx", "text")
            self.emit("out dx, al", "text")
        elif name == "port_read8" and len(node.children) >= 1:
            self.gen_expression(node.children[0])
            self.emit("pop rcx", "text")
            self.emit("mov dx, cx", "text")
            self.emit("in al, dx", "text")
            self.emit("movzx rax, al", "text")
            self.emit("push rax", "text")
        elif name == "disable_interrupts":
            self.emit("cli", "text")
        elif name == "enable_interrupts":
            self.emit("sti", "text")
        elif name == "halt":
            self.emit("hlt", "text")
        elif name == "read_cr3":
            self.emit("mov rax, cr3", "text")
            self.emit("push rax", "text")
        elif name == "rdtsc":
            self.emit("rdtsc", "text")
            self.emit("shl rdx, 32", "text")
            self.emit("or rax, rdx", "text")
            self.emit("push rax", "text")
        elif name == "mfence":
            self.emit("mfence", "text")
        elif name == "load_module":
            self.emit("; Load module", "text")
            self.emit("mov rax, 0", "text")
            self.emit("push rax", "text")
        elif name == "resolve_symbol":
            self.emit("; Resolve symbol", "text")
            self.emit("mov rax, 0", "text")
            self.emit("push rax", "text")
            
    def gen_switch(self, node: ASTNode) -> None:
        if len(node.children) < 2:
            return
            
        self.gen_expression(node.children[0])
        self.emit("pop rax", "text")
        
        end_label = self.new_label()
        case_labels = []
        
        for i, case in enumerate(node.children[1:]):
            case_label = self.new_label()
            case_labels.append(case_label)
            if case.children and case.children[0].type == ASTType.LITERAL:
                self.emit(f"cmp rax, {case.children[0].value}", "text")
                self.emit(f"je {case_label}", "text")
                
        if case_labels:
            self.emit(f"jmp {end_label}", "text")
            
        for i, case in enumerate(node.children[1:]):
            self.emit_raw(f"{case_labels[i]}:", "text")
            if len(case.children) > 1:
                self.gen_statement(case.children[1])
            self.emit(f"jmp {end_label}", "text")
            
        self.emit_raw(f"{end_label}:", "text")
        
    def gen_function(self, node: ASTNode) -> None:
        self.emit_raw("", "text")
        self.emit_raw(f"; Function: {node.value} (opt: {node.optimization_level.value})", "text")
        self.emit_raw(f"{node.value}:", "text")
        self.emit("push rbp", "text")
        self.emit("mov rbp, rsp", "text")
        self.emit(f"sub rsp, {node.function_frame_size}", "text")
        
        arg_regs = ['rdi', 'rsi', 'rdx', 'rcx', 'r8', 'r9']
        for i, ptype in enumerate(node.function_params):
            if i < len(arg_regs):
                offset = -8 - (i * 8)
                mov_prefix = self.get_mov_prefix(ptype)
                self.emit(f"mov {mov_prefix} [rbp + {offset}], {arg_regs[i]}", "text")
                
        for child in node.children:
            self.gen_statement(child)
            
        if node.function_return != DataType.VOID:
            self.emit("xor eax, eax", "text")
        self.emit("mov rsp, rbp", "text")
        self.emit("pop rbp", "text")
        self.emit("ret", "text")
        
    def gen_call(self, node: ASTNode) -> None:
        if not node.children:
            return
            
        func_name = node.value
        args = node.children[1:] if len(node.children) > 1 else []
        
        for arg in reversed(args):
            self.gen_expression(arg)
            
        arg_regs = ['rdi', 'rsi', 'rdx', 'rcx', 'r8', 'r9']
        for i in range(min(len(args), 6)):
            self.emit(f"pop {arg_regs[i]}", "text")
            
        self.emit(f"call {func_name}", "text")
        self.emit("push rax", "text")
        
    def gen_assign(self, node: ASTNode) -> None:
        if len(node.children) < 2:
            return
            
        self.gen_expression(node.children[1])
        self.emit("pop rax", "text")
        
        lhs = node.children[0]
        if lhs.type == ASTType.VARIABLE:
            sym = self.symbols.lookup(lhs.value)
            if sym and not sym.is_global:
                mov_prefix = self.get_mov_prefix(sym.type)
                self.emit(f"mov {mov_prefix} [rbp + {sym.stack_offset}], rax", "text")
            else:
                mov_prefix = self.get_mov_prefix(sym.type) if sym else "qword"
                self.emit(f"mov {mov_prefix} [rel {lhs.value}], rax", "text")
                
    def gen_return(self, node: ASTNode) -> None:
        if node.children:
            self.gen_expression(node.children[0])
            self.emit("pop rax", "text")
        else:
            self.emit("xor eax, eax", "text")
        self.emit("mov rsp, rbp", "text")
        self.emit("pop rbp", "text")
        self.emit("ret", "text")
        
    def gen_if(self, node: ASTNode) -> None:
        else_label = self.new_label()
        end_label = self.new_label()
        
        self.gen_expression(node.children[0])
        self.emit("pop rax", "text")
        self.emit("cmp rax, 0", "text")
        self.emit(f"je {else_label}", "text")
        
        if len(node.children) > 1:
            self.gen_statement(node.children[1])
        self.emit(f"jmp {end_label}", "text")
        
        self.emit_raw(f"{else_label}:", "text")
        if len(node.children) > 2:
            self.gen_statement(node.children[2])
            
        self.emit_raw(f"{end_label}:", "text")
        
    def gen_while(self, node: ASTNode) -> None:
        start_label = self.new_label()
        end_label = self.new_label()
        
        self.emit_raw(f"{start_label}:", "text")
        self.gen_expression(node.children[0])
        self.emit("pop rax", "text")
        self.emit("cmp rax, 0", "text")
        self.emit(f"je {end_label}", "text")
        
        if len(node.children) > 1:
            self.gen_statement(node.children[1])
        self.emit(f"jmp {start_label}", "text")
        
        self.emit_raw(f"{end_label}:", "text")
        
    def gen_for(self, node: ASTNode) -> None:
        start_label = self.new_label()
        end_label = self.new_label()
        
        if len(node.children) > 0 and node.children[0]:
            self.gen_statement(node.children[0])
            
        self.emit_raw(f"{start_label}:", "text")
        
        if len(node.children) > 1 and node.children[1]:
            self.gen_expression(node.children[1])
            self.emit("pop rax", "text")
            self.emit("cmp rax, 0", "text")
            self.emit(f"je {end_label}", "text")
        
        if len(node.children) > 3 and node.children[3]:
            self.gen_statement(node.children[3])
            
        if len(node.children) > 2 and node.children[2]:
            self.gen_statement(node.children[2])
            
        self.emit(f"jmp {start_label}", "text")
        self.emit_raw(f"{end_label}:", "text")
        
    def gen_with(self, node: ASTNode) -> None:
        mutex_name = f"mutex_{self.label_counter}"
        spin_label = self.new_label()
        
        self.emit_raw(f"{spin_label}:", "text")
        self.emit("mov al, 1", "text")
        self.emit(f"xchg byte [rel {mutex_name}], al", "text")
        self.emit("test al, al", "text")
        self.emit(f"jnz {spin_label}", "text")
        self.emit("mfence", "text")
        
        if len(node.children) > 1 and node.children[1]:
            self.gen_statement(node.children[1])
            
        self.emit(f"mov byte [rel {mutex_name}], 0", "text")
        self.emit("mfence", "text")
        
        self.emit_raw(f"{mutex_name}: resb 8", "bss")
        
    def gen_expression(self, node: ASTNode) -> None:
        if not node:
            return
            
        if node.type == ASTType.LITERAL:
            self.emit(f"push {node.value}", "text")
        elif node.type == ASTType.VARIABLE:
            sym = self.symbols.lookup(node.value)
            if sym and not sym.is_global:
                mov_prefix = self.get_mov_prefix(sym.type)
                self.emit(f"push {mov_prefix} [rbp + {sym.stack_offset}]", "text")
            elif sym and sym.is_imported:
                self.emit(f"; Imported symbol: {node.value} from {sym.module_name}", "text")
                self.emit(f"push qword [rel {node.value}]", "text")
            else:
                mov_prefix = self.get_mov_prefix(sym.type) if sym else "qword"
                self.emit(f"push {mov_prefix} [rel {node.value}]", "text")
        elif node.type == ASTType.BINARY_OP:
            self.gen_expression(node.children[0])
            self.gen_expression(node.children[1])
            self.emit("pop rbx", "text")
            self.emit("pop rax", "text")
            
            if node.value == "+":
                self.emit("add rax, rbx", "text")
            elif node.value == "-":
                self.emit("sub rax, rbx", "text")
            elif node.value == "*":
                self.emit("imul rax, rbx", "text")
            elif node.value == "/":
                self.emit("xor rdx, rdx", "text")
                self.emit("div rbx", "text")
            elif node.value == "%":
                self.emit("xor rdx, rdx", "text")
                self.emit("div rbx", "text")
                self.emit("mov rax, rdx", "text")
            elif node.value == "&":
                self.emit("and rax, rbx", "text")
            elif node.value == "|":
                self.emit("or rax, rbx", "text")
            elif node.value == "^":
                self.emit("xor rax, rbx", "text")
            elif node.value == "<<":
                self.emit("mov rcx, rbx", "text")
                self.emit("shl rax, cl", "text")
            elif node.value == ">>":
                self.emit("mov rcx, rbx", "text")
                self.emit("shr rax, cl", "text")
            elif node.value == "==":
                self.emit("cmp rax, rbx", "text")
                self.emit("sete al", "text")
                self.emit("movzx rax, al", "text")
            elif node.value == "!=":
                self.emit("cmp rax, rbx", "text")
                self.emit("setne al", "text")
                self.emit("movzx rax, al", "text")
            elif node.value == "<":
                self.emit("cmp rax, rbx", "text")
                self.emit("setl al", "text")
                self.emit("movzx rax, al", "text")
            elif node.value == "<=":
                self.emit("cmp rax, rbx", "text")
                self.emit("setle al", "text")
                self.emit("movzx rax, al", "text")
            elif node.value == ">":
                self.emit("cmp rax, rbx", "text")
                self.emit("setg al", "text")
                self.emit("movzx rax, al", "text")
            elif node.value == ">=":
                self.emit("cmp rax, rbx", "text")
                self.emit("setge al", "text")
                self.emit("movzx rax, al", "text")
            elif node.value == "&&":
                false_label = self.new_label()
                end_label = self.new_label()
                self.emit("test rax, rax", "text")
                self.emit(f"jz {false_label}", "text")
                self.emit("test rbx, rbx", "text")
                self.emit(f"jz {false_label}", "text")
                self.emit("mov rax, 1", "text")
                self.emit(f"jmp {end_label}", "text")
                self.emit_raw(f"{false_label}:", "text")
                self.emit("mov rax, 0", "text")
                self.emit_raw(f"{end_label}:", "text")
            elif node.value == "||":
                true_label = self.new_label()
                end_label = self.new_label()
                self.emit("test rax, rax", "text")
                self.emit(f"jnz {true_label}", "text")
                self.emit("test rbx, rbx", "text")
                self.emit(f"jnz {true_label}", "text")
                self.emit("mov rax, 0", "text")
                self.emit(f"jmp {end_label}", "text")
                self.emit_raw(f"{true_label}:", "text")
                self.emit("mov rax, 1", "text")
                self.emit_raw(f"{end_label}:", "text")
                
            self.emit("push rax", "text")
        elif node.type == ASTType.TYPE_CONVERSION:
            self.gen_type_conversion(node)
        elif node.type == ASTType.CALL:
            self.gen_call(node)
        elif node.type == ASTType.BUILTIN_CALL:
            self.gen_builtin(node)
        elif node.type == ASTType.METHOD_CALL:
            self.gen_call(node)
        elif node.type == ASTType.BLOCK_ARRAY_METHOD:
            self.gen_block_array_method(node)
        else:
            self.emit("push 0", "text")

# ============================================================================
# Compiler Main
# ============================================================================

class Compiler:
    def __init__(self, backend: Backend = Backend.NASM, opt_level: OptimizationLevel = OptimizationLevel.O2,
                 output_format: OutputFormat = OutputFormat.ELF_EXECUTABLE, verbose: bool = False):
        self.backend = backend
        self.opt_level = opt_level
        self.output_format = output_format
        self.verbose = verbose
        self.config = LanguageConfig()
        self.errors = ErrorCollector()
        self.symbols = SymbolTable()
        
    def compile(self, source: str, output_file: str, source_file: str = "<input>") -> bool:
        if self.verbose:
            print(f"lowl Compiler v{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}")
            print(f"Copyright (c) 2026 Anthony Matarazzo - MIT License")
            print(f"Optimization level: {self.opt_level}")
            print(f"Output format: {self.output_format}")
            
        self.errors.set_source(source)
        self.errors.filename = source_file
            
        lexer = Lexer(source, source_file, self.config, self.errors)
        tokens = []
        while True:
            tok = lexer.next_token()
            if tok.type == TokenType.TOK_ERROR:
                self.errors.add_error(f"Lexer error: {tok.value}", tok.line, tok.column)
                return False
            tokens.append(tok)
            if tok.type == TokenType.TOK_EOF:
                break
                
        if self.verbose:
            print(f"Lexer: {len(tokens)} tokens")
        
        tokens = inject_indent_dedent(tokens, source)
        
        if self.verbose:
            indent_count = sum(1 for t in tokens if t.type == TokenType.INDENT)
            dedent_count = sum(1 for t in tokens if t.type == TokenType.DEDENT)
            print(f"Indent pass: {indent_count} INDENT, {dedent_count} DEDENT")
            
        parser = Parser(tokens, self.symbols, self.errors, self.opt_level)
        ast = parser.parse()
        
        if self.errors.has_errors():
            self.errors.print_summary()
            return False
            
        if self.verbose:
            print("Parser: AST built")
            
        generator = CodeGenerator(self.backend, self.symbols, self.opt_level, self.output_format)
        asm_code = generator.generate(ast)
        
        try:
            with open(output_file, 'w') as f:
                f.write(asm_code)
        except IOError as e:
            print(f"Cannot write to {output_file}: {e}")
            return False
            
        if self.verbose:
            lines = len(asm_code.split('\n'))
            print(f"Generated {lines} lines of assembly")
            
        return True

# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='lowl Compiler v2.1.0 - Systems Programming Language',
        epilog='Copyright (c) 2026 Anthony Matarazzo - MIT License'
    )
    parser.add_argument('input', help='Input .lowl file')
    parser.add_argument('-o', '--output', default='output.asm', help='Output file')
    parser.add_argument('--backend', choices=['nasm', 'intel'], default='nasm',
                        help='Assembly backend (default: nasm)')
    parser.add_argument('-O', '--optimize', choices=['0', '1', '2', '3'], default='2',
                        help='Optimization level (0=no optimization, 3=aggressive)')
    parser.add_argument('-f', '--format', choices=['elf', 'flat', 'kernel', 'coff', 'boot'], 
                        default='elf', help='Output format')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    parser.add_argument('--version', action='version', 
                        version=f'lowl v{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}')
    
    args = parser.parse_args()
    
    backend = Backend.NASM if args.backend == 'nasm' else Backend.INTEL_ASM
    opt_level = {
        '0': OptimizationLevel.O0,
        '1': OptimizationLevel.O1,
        '2': OptimizationLevel.O2,
        '3': OptimizationLevel.O3
    }[args.optimize]
    
    output_format = {
        'elf': OutputFormat.ELF_EXECUTABLE,
        'flat': OutputFormat.FLAT_BINARY,
        'kernel': OutputFormat.KERNEL_MODULE,
        'coff': OutputFormat.COFF_OBJECT,
        'boot': OutputFormat.BOOT_IMAGE
    }[args.format]
    
    try:
        with open(args.input, 'r') as f:
            source = f.read()
    except IOError as e:
        print(f"Error: Cannot open {args.input}: {e}")
        sys.exit(1)
        
    compiler = Compiler(backend, opt_level, output_format, args.verbose)
    if compiler.compile(source, args.output, args.input):
        print(f"Compiled {args.input} -> {args.output} (O{args.optimize}, {args.format})")
        sys.exit(0)
    else:
        print("Compilation failed")
        sys.exit(1)

if __name__ == '__main__':
    main()

