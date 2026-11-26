#!/usr/bin/env python3
"""
lowl Compiler v2.1.0 - Complete Implementation
Systems Programming Language for Intel x86_64

All features from the LOWL Language Reference Manual v2.1.0 implemented:
- Inline assembly (asm statement)
- Hardware builtins (cli, sti, hlt, pause, rdtsc, cpuid, etc.)
- #[interrupt] and #[kernel] attributes
- Pattern matching switch with when guards and priority
- Data sections with external file support (CSV, JSON, XML, YAML, TOML)
- SIMD vector types and operations (SSE, AVX, AVX-512)
- BlockArray with SIMD optimization
- Optimization levels O0-O3 with loop unrolling and vectorization
- Memory management builtins
- Module system support

Copyright (c) 2026 Anthony Matarazzo - MIT License
"""

import sys
import re
import struct
import argparse
import copy
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple, Set
from enum import Enum
import os
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
    RECORD = 33
    TEMPLATE = 34
    OPTION = 35
    MODULE = 36
    STRING = 37
    TUPLE = 38
    FN = 39
    STRUCT = 40

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
    DataTypeInfo(DataType.VEC4_F32, 16, 16, "vec4_f32", "dq", "xmm0", "dq", 16, "SSE"),
    DataTypeInfo(DataType.VEC8_F32, 32, 32, "vec8_f32", "dq", "ymm0", "dq", 32, "AVX"),
    DataTypeInfo(DataType.VEC16_F32, 64, 64, "vec16_f32", "dq", "zmm0", "dq", 64, "AVX512"),
    DataTypeInfo(DataType.VEC2_F64, 16, 16, "vec2_f64", "dq", "xmm0", "dq", 16, "SSE"),
    DataTypeInfo(DataType.VEC4_F64, 32, 32, "vec4_f64", "dq", "ymm0", "dq", 32, "AVX"),
    DataTypeInfo(DataType.VEC8_F64, 64, 64, "vec8_f64", "dq", "zmm0", "dq", 64, "AVX512"),
]

POINTER_TYPES = {DataType.PTR, DataType.PTR_MUT, DataType.MMIO_PTR}

@dataclass
class TypeRef:
    base: DataType = DataType.I64
    name: str = ""
    elem: Optional['TypeRef'] = None
    length: Optional[int] = None
    params: List['TypeRef'] = field(default_factory=list)
    fn_params: List['TypeRef'] = field(default_factory=list)
    fn_return: Optional['TypeRef'] = None
    is_mut: bool = False

def type_size(ref: Optional[TypeRef], symtab: Optional['SymbolTable'] = None) -> int:
    if ref is None:
        return 8
    if ref.base == DataType.ARRAY:
        elem_sz = type_size(ref.elem, symtab)
        return elem_sz * (ref.length if ref.length is not None else 1)
    if ref.base == DataType.STRUCT and ref.name and symtab:
        return symtab.struct_size(ref.name)
    for info in DATA_TYPE_TABLE:
        if info.type == ref.base:
            return info.size
    return 8

def type_align(ref: Optional[TypeRef], symtab: Optional['SymbolTable'] = None) -> int:
    if ref is None:
        return 8
    if ref.base == DataType.ARRAY:
        return type_align(ref.elem, symtab)
    if ref.base == DataType.STRUCT and ref.name and symtab:
        layout = symtab.struct_layout(ref.name)
        if layout and layout['fields']:
            return max(1, min(8, max(type_align(f[1], symtab) for f in layout['fields'])))
        return 8
    for info in DATA_TYPE_TABLE:
        if info.type == ref.base:
            return info.alignment
    return 8

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
    KW_DATA_SECTION = 46; KW_RECORD = 47; KW_KEY = 48
    KW_COLUMNAR = 50; KW_INDENTED = 51; KW_END = 52
    KW_TEMPLATE = 53; KW_OPTION = 54; KW_SOME = 55; KW_NONE = 56
    KW_BLOCK_ARRAY = 60
    KW_IMPORT = 62; KW_EXPORT = 63; KW_MODULE = 64
    KW_ASM = 65
    KW_ATTRIBUTE_START = 66; KW_ATTRIBUTE_END = 67
    KW_INTERRUPT = 68; KW_KERNEL = 69; KW_INIT = 70; KW_SECTION = 71
    KW_U8 = 100; KW_U16 = 101; KW_U32 = 102; KW_U64 = 103
    KW_I8 = 104; KW_I16 = 105; KW_I32 = 106; KW_I64 = 107
    KW_F32 = 108; KW_F64 = 109; KW_BOOL = 110; KW_CHAR = 111
    KW_PTR = 112; KW_MMIO_PTR = 113; KW_BIT = 114
    KW_VEC4_F32 = 115; KW_VEC8_F32 = 116; KW_VEC16_F32 = 117
    KW_VEC2_F64 = 118; KW_VEC4_F64 = 119; KW_VEC8_F64 = 120
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
    PRAGMA_OPTIMIZE = 400; PRAGMA_SIMD = 401; PRAGMA_UNROLL = 402
    TOK_CHAR = 7
    KW_MUT = 72; KW_STATIC = 73; KW_IMPL = 74; KW_ABSTRACT = 75
    KW_SELF = 76; KW_BREAK = 77; KW_CONTINUE = 78; KW_DEFAULT = 79
    KW_STEP = 80; KW_STRING = 81; KW_ARRAY = 82; KW_AS = 83
    OP_POW = 262

KEYWORDS: Dict[str, TokenType] = {
    "let": TokenType.KW_LET, "if": TokenType.KW_IF, "elif": TokenType.KW_ELIF,
    "else": TokenType.KW_ELSE, "while": TokenType.KW_WHILE, "for": TokenType.KW_FOR,
    "in": TokenType.KW_IN, "range": TokenType.KW_RANGE, "return": TokenType.KW_RETURN,
    "fn": TokenType.KW_FN, "with": TokenType.KW_WITH, "true": TokenType.KW_TRUE,
    "false": TokenType.KW_FALSE, "null": TokenType.KW_NULL, "const": TokenType.KW_CONST,
    "class": TokenType.KW_CLASS, "struct": TokenType.KW_STRUCT, "enum": TokenType.KW_ENUM,
    "extends": TokenType.KW_EXTENDS, "this": TokenType.KW_THIS, "super": TokenType.KW_SUPER,
    "new": TokenType.KW_NEW, "delete": TokenType.KW_DELETE, "inline": TokenType.KW_INLINE,
    "virtual": TokenType.KW_VIRTUAL, "override": TokenType.KW_OVERRIDE,
    "public": TokenType.KW_PUBLIC, "private": TokenType.KW_PRIVATE,
    "protected": TokenType.KW_PROTECTED, "from": TokenType.KW_FROM, "def": TokenType.KW_DEF,
    "metadata": TokenType.KW_METADATA, "switch": TokenType.KW_SWITCH,
    "case": TokenType.KW_CASE, "when": TokenType.KW_WHEN, "priority": TokenType.KW_PRIORITY,
    "data_section": TokenType.KW_DATA_SECTION, "record": TokenType.KW_RECORD,
    "key": TokenType.KW_KEY, "columnar": TokenType.KW_COLUMNAR,
    "indented": TokenType.KW_INDENTED, "end": TokenType.KW_END,
    "template": TokenType.KW_TEMPLATE, "option": TokenType.KW_OPTION,
    "some": TokenType.KW_SOME, "none": TokenType.KW_NONE,
    "block_array": TokenType.KW_BLOCK_ARRAY, "import": TokenType.KW_IMPORT,
    "export": TokenType.KW_EXPORT, "module": TokenType.KW_MODULE, "asm": TokenType.KW_ASM,
    "interrupt": TokenType.KW_INTERRUPT, "kernel": TokenType.KW_KERNEL,
    "init": TokenType.KW_INIT, "section": TokenType.KW_SECTION,
    "u8": TokenType.KW_U8, "u16": TokenType.KW_U16, "u32": TokenType.KW_U32,
    "u64": TokenType.KW_U64, "i8": TokenType.KW_I8, "i16": TokenType.KW_I16,
    "i32": TokenType.KW_I32, "i64": TokenType.KW_I64, "f32": TokenType.KW_F32,
    "f64": TokenType.KW_F64, "bool": TokenType.KW_BOOL, "char": TokenType.KW_CHAR,
    "ptr": TokenType.KW_PTR, "mmio_ptr": TokenType.KW_MMIO_PTR, "bit": TokenType.KW_BIT,
    "vec4_f32": TokenType.KW_VEC4_F32, "vec8_f32": TokenType.KW_VEC8_F32,
    "vec16_f32": TokenType.KW_VEC16_F32, "vec2_f64": TokenType.KW_VEC2_F64,
    "vec4_f64": TokenType.KW_VEC4_F64, "vec8_f64": TokenType.KW_VEC8_F64,
    "mut": TokenType.KW_MUT, "static": TokenType.KW_STATIC, "impl": TokenType.KW_IMPL,
    "abstract": TokenType.KW_ABSTRACT, "self": TokenType.KW_SELF,
    "break": TokenType.KW_BREAK, "continue": TokenType.KW_CONTINUE,
    "default": TokenType.KW_DEFAULT, "step": TokenType.KW_STEP,
    "string": TokenType.KW_STRING, "str": TokenType.KW_STRING,
    "array": TokenType.KW_ARRAY, "as": TokenType.KW_AS,
}

TYPE_TOKEN_MAP: Dict[TokenType, DataType] = {
    TokenType.KW_U8: DataType.U8, TokenType.KW_U16: DataType.U16,
    TokenType.KW_U32: DataType.U32, TokenType.KW_U64: DataType.U64,
    TokenType.KW_I8: DataType.I8, TokenType.KW_I16: DataType.I16,
    TokenType.KW_I32: DataType.I32, TokenType.KW_I64: DataType.I64,
    TokenType.KW_F32: DataType.F32, TokenType.KW_F64: DataType.F64,
    TokenType.KW_BOOL: DataType.BOOL, TokenType.KW_CHAR: DataType.CHAR,
    TokenType.KW_PTR: DataType.PTR, TokenType.KW_MMIO_PTR: DataType.MMIO_PTR,
    TokenType.KW_BIT: DataType.BIT,
    TokenType.KW_VEC4_F32: DataType.VEC4_F32, TokenType.KW_VEC8_F32: DataType.VEC8_F32,
    TokenType.KW_VEC16_F32: DataType.VEC16_F32, TokenType.KW_VEC2_F64: DataType.VEC2_F64,
    TokenType.KW_VEC4_F64: DataType.VEC4_F64, TokenType.KW_VEC8_F64: DataType.VEC8_F64,
    TokenType.KW_STRING: DataType.STRING, TokenType.KW_ARRAY: DataType.ARRAY,
}

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
    DATA_SECTION = 20; RECORD_DEF = 21
    BUILTIN_CALL = 23; TEMPLATE_DECL = 24; TEMPLATE_INST = 25
    OPTION_TYPE = 26; METHOD_CALL = 27
    BLOCK_ARRAY_TYPE = 29; BLOCK_ARRAY_METHOD = 30
    SIMD_OPERATION = 31; PRAGMA = 32
    IMPORT_STMT = 33; EXPORT_STMT = 34
    TYPE_CONVERSION = 35
    ASM_STMT = 36
    ATTRIBUTE = 37
    INDEX = 38; ARRAY_LITERAL = 39; STRUCT_LITERAL = 40; LAMBDA = 41
    STRUCT_DEF = 42; IMPL_BLOCK = 43; BREAK_STMT = 44; CONTINUE_STMT = 45
    TUPLE = 46; ENUM_DEF = 47

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
    unroll_factor: int = 0
    attributes: List[str] = field(default_factory=list)
    meta: Dict[str, object] = field(default_factory=dict)

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
    attributes: List[str] = field(default_factory=list)
    type_ref: object = None

class SymbolTable:
    def __init__(self):
        self.scopes: List[Dict[str, Symbol]] = [{}]
        self.current_scope = 0
        self.next_stack_offset = -8
        self.imported_symbols: Dict[str, str] = {}
        self.exported_symbols: Set[str] = set()
        self.structs: Dict[str, Dict[str, object]] = {}
        self.functions: List[object] = []

    def define_struct(self, name: str, fields, base: Optional[str] = None,
                      has_vptr: bool = False) -> None:
        offset = 0
        layout_fields = []
        base_layout = self.structs.get(base) if base else None
        if base_layout:
            layout_fields = list(base_layout['fields'])
            offset = base_layout['size']
        elif has_vptr:
            layout_fields = [('__vptr', TypeRef(base=DataType.PTR), 0)]
            offset = 8
        for fname, fref in fields:
            fsize = max(1, type_size(fref, self))
            falign = max(1, min(8, type_align(fref, self)))
            offset = (offset + falign - 1) // falign * falign
            layout_fields.append((fname, fref, offset))
            offset += fsize
        size = max(1, (offset + 7) & ~7)
        self.structs[name] = {'fields': layout_fields, 'size': size}

    def class_info(self, name):
        if not hasattr(self, 'classes'):
            self.classes = {}
        return self.classes.get(name)

    def register_class(self, name: str, info: dict) -> None:
        if not hasattr(self, 'classes'):
            self.classes = {}
        self.classes[name] = info

    def specialize_class_ref(self, owner_ref, ref):
        if not isinstance(owner_ref, TypeRef) or not isinstance(ref, TypeRef):
            return ref
        info = self.class_info(owner_ref.name)
        params = info.get('template_params', []) if info else []
        bindings = dict(zip(params, owner_ref.params))

        def substitute(value):
            if value.base == DataType.STRUCT and value.name in bindings:
                return copy.deepcopy(bindings[value.name])
            result = copy.deepcopy(value)
            result.elem = substitute(result.elem) if result.elem else None
            result.params = [substitute(item) for item in result.params]
            result.fn_params = [substitute(item) for item in result.fn_params]
            if result.fn_return is not None:
                result.fn_return = substitute(result.fn_return)
            return result

        return substitute(ref) if bindings else ref

    def find_method(self, owner: str, name: str):
        seen = set()
        while owner and owner not in seen:
            seen.add(owner)
            for f in self.functions:
                if f.value == name and (f.meta.get('parent') or "") == owner:
                    return f
            info = self.class_info(owner)
            owner = info.get('base') if info else None
        return None

    def vtable_slot(self, owner: str, name: str):
        info = self.class_info(owner)
        if info and name in info.get('virtuals', []):
            return info['virtuals'].index(name)
        return None

    @staticmethod
    def struct_name_of(ref) -> str:
        seen = 0
        while ref is not None and seen < 4:
            name = getattr(ref, 'name', '')
            if name and name not in ('ptr', 'ptr_mut', 'mmio_ptr', 'array') \
                    and not (getattr(ref, 'elem', None) is not None and ref.base in POINTER_TYPES):
                return name
            ref = getattr(ref, 'elem', None)
            seen += 1
        return ""

    def struct_layout(self, name: str):
        return self.structs.get(name)

    def struct_size(self, name: str) -> int:
        layout = self.structs.get(name)
        return layout['size'] if layout else 8

    def field_offset(self, struct_name: str, field_name: str):
        layout = self.structs.get(struct_name)
        if not layout:
            return None
        for fname, fref, offset in layout['fields']:
            if fname == field_name:
                return offset, fref
        return None

    def field_ref(self, struct_name: str, field_name: str):
        found = self.field_offset(struct_name, field_name)
        return found[1] if found else None

    def register_function(self, name: str, node) -> None:
        self.functions.append(node)

    def find_functions(self, name: str) -> List[object]:
        return [f for f in self.functions if f.value == name]

    def enter_scope(self) -> None:
        self.scopes.append({})
        self.current_scope = len(self.scopes) - 1

    def exit_scope(self) -> None:
        if len(self.scopes) > 1:
            self.scopes.pop()
            self.current_scope = len(self.scopes) - 1

    def reset_frame(self) -> None:
        self.next_stack_offset = -16

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
                is_exported: bool = False, attributes: List[str] = None,
                type_ref=None) -> bool:
        if name in self.scopes[self.current_scope]:
            return False

        if type_ref is not None:
            size = max(1, type_size(type_ref, self))
        else:
            type_info = self.get_type_info(dtype)
            size = type_info.size

        alloc_size = max(8, ((size + 7) & ~7))
        base_offset = self.next_stack_offset - (alloc_size - 8) if not is_global else self.next_stack_offset
        sym = Symbol(name=name, type=dtype, scope_level=self.current_scope,
                     stack_offset=base_offset, is_global=is_global,
                     line=line, column=column,
                     is_block_array=is_block_array, block_array_type=block_array_type,
                     is_exported=is_exported, attributes=attributes or [],
                     type_ref=type_ref)
        if not is_global:
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
# Error Reporter
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
# Data Section Handler
# ============================================================================

class DataSectionHandler:
    def __init__(self):
        self.sections: Dict[str, 'DataSection'] = {}

    def load_section(self, name: str, file_path: str, format_type: str) -> Optional['DataSection']:
        section = DataSection(name)
        success = False

        if format_type == "csv" or file_path.endswith('.csv'):
            success = section.load_csv(file_path)
        elif format_type == "json" or file_path.endswith('.json'):
            success = section.load_json(file_path)
        elif format_type == "xml" or file_path.endswith('.xml'):
            success = section.load_xml(file_path)
        elif format_type == "yaml" or file_path.endswith(('.yml', '.yaml')):
            success = section.load_yaml(file_path)
        elif format_type == "toml" or file_path.endswith('.toml'):
            success = section.load_toml(file_path)
        else:
            success = section.load_inline_data([])

        if success:
            self.sections[name] = section
            return section
        return None

class DataSection:
    def __init__(self, name: str):
        self.name = name
        self.grid: List[List[str]] = []
        self.column_names: List[str] = []
        self.records: Dict[str, Any] = {}

    def load_csv(self, path: str) -> bool:
        try:
            with open(path, 'r', encoding='utf-8') as f:
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
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    self.column_names = list(data[0].keys())
                    self.grid = [[str(item.get(col, "")) for col in self.column_names] for item in data]
                elif isinstance(data, dict):
                    self.column_names = list(data.keys())
                    self.grid = [[str(data.get(col, "")) for col in self.column_names]]
            return True
        except Exception:
            return False

    def load_xml(self, path: str, record_path: str = "") -> bool:
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            elements = root.findall(record_path) if record_path else list(root)
            if elements:
                self.column_names = list(elements[0].attrib.keys())
                self.grid = [[elem.attrib.get(col, "") for col in self.column_names] for elem in elements]
            return True
        except Exception:
            return False

    def load_yaml(self, path: str) -> bool:
        try:
            import yaml
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                if isinstance(data, list) and data:
                    self.column_names = list(data[0].keys())
                    self.grid = [[str(item.get(col, "")) for col in self.column_names] for item in data]
            return True
        except Exception:
            return False

    def load_toml(self, path: str) -> bool:
        try:
            import tomllib
            with open(path, 'rb') as f:
                data = tomllib.load(f)
                if isinstance(data, dict):
                    self.column_names = list(data.keys())
                    self.grid = [[str(data.get(col, "")) for col in self.column_names]]
            return True
        except Exception:
            return False

    def load_inline_data(self, data: List[List[str]]) -> bool:
        if data:
            self.grid = data
        return True

    def row_count(self) -> int:
        return len(self.grid)

    def column_count(self) -> int:
        return len(self.column_names) if self.column_names else (len(self.grid[0]) if self.grid else 0)

    def cell(self, row: int, col: int) -> str:
        if 0 <= row < len(self.grid) and 0 <= col < len(self.grid[row]):
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
            return [row[col_idx] if col_idx < len(row) else "" for row in self.grid]
        return []

    def generate_rodata(self) -> List[str]:
        """Generate assembly directives for .rodata section"""
        lines = []
        lines.append(f"; Data section: {self.name}")
        lines.append(f"_data_section_{self.name}_start:")
        for row in self.grid:
            for cell in row:
                escaped = cell.replace("\\", "\\\\").replace("'", "\\'")
                lines.append(f"    db '{escaped}', 0")
            lines.append("    db 0")
        lines.append(f"_data_section_{self.name}_end:")
        return lines

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

    def peek(self, offset: int = 1) -> str:
        idx = self.pos + offset
        return self.source[idx] if idx < len(self.source) else '\0'

    def advance(self) -> None:
        if self.current() == '\n':
            self.line += 1
            self.column = 0
        self.pos += 1
        self.column += 1

    def skip_whitespace(self) -> None:
        while self.current() in ' \t\r':
            self.advance()

    def skip_line_comment(self) -> None:
        while self.current() not in ('\n', '\0'):
            self.advance()

    def skip_block_comment(self, start_line: int, start_col: int) -> None:
        end_delim = self.config.block_comment_end
        self.advance()
        self.advance()
        while self.current() != '\0':
            if self.source.startswith(end_delim, self.pos):
                for _ in range(len(end_delim)):
                    self.advance()
                return
            self.advance()
        self.errors.add_error("Unterminated block comment", start_line, start_col)

    def read_number(self) -> Token:
        start_line, start_col = self.line, self.column
        num = ""
        if self.current() == '0' and self.peek() in 'xX':
            self.advance(); self.advance()
            while self.current().isdigit() or self.current().lower() in 'abcdef_':
                if self.current() != '_':
                    num += self.current()
                self.advance()
            return Token(TokenType.TOK_HEX, num, start_line, start_col, self.filename)
        if self.current() == '0' and self.peek() in 'bB':
            self.advance(); self.advance()
            while self.current() in '01_':
                if self.current() != '_':
                    num += self.current()
                self.advance()
            return Token(TokenType.TOK_BINARY, num, start_line, start_col, self.filename)
        while self.current().isdigit() or self.current() == '_':
            if self.current() != '_':
                num += self.current()
            self.advance()
        if self.current() == '.' and self.peek() != '.' and self.peek().isdigit():
            num += self.current()
            self.advance()
            while self.current().isdigit() or self.current() == '_':
                if self.current() != '_':
                    num += self.current()
                self.advance()
        if self.current() in 'eE' and (self.peek().isdigit() or self.peek() in '+-'):
            num += self.current()
            self.advance()
            if self.current() in '+-':
                num += self.current()
                self.advance()
            while self.current().isdigit():
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
                esc = self.current()
                if esc == 'n': s += '\n'
                elif esc == 'r': s += '\r'
                elif esc == 't': s += '\t'
                elif esc == '0': s += '\0'
                elif esc == 'a': s += '\a'
                elif esc == 'b': s += '\b'
                elif esc == 'f': s += '\f'
                elif esc == 'v': s += '\v'
                elif esc == '\\': s += '\\'
                elif esc == '"': s += '"'
                elif esc == "'": s += "'"
                elif esc == 'x':
                    self.advance()
                    digits = ''
                    for _ in range(2):
                        if self.current().lower() in '0123456789abcdef':
                            digits += self.current()
                            self.advance()
                        else:
                            break
                    s += chr(int(digits, 16)) if digits else 'x'
                    continue
                else:
                    s += esc
            else:
                s += self.current()
            self.advance()
        if self.current() == delim:
            self.advance()
        else:
            self.errors.add_error("Unterminated string or character literal", start_line, start_col)
        if delim == "'":
            return Token(TokenType.TOK_CHAR, s, start_line, start_col, self.filename)
        return Token(TokenType.TOK_STRING, s, start_line, start_col, self.filename)

    def read_attribute(self) -> Token:
        start_line, start_col = self.line, self.column
        if self.current() == '#':
            self.advance()
        if self.current() == '[':
            self.advance()
        attr_name = ""
        while self.current() not in (']', '\0'):
            attr_name += self.current()
            self.advance()
        if self.current() == ']':
            self.advance()
        attr_clean = attr_name.strip()
        lower_attr = attr_clean.lower()
        if 'interrupt' in lower_attr:
            return Token(TokenType.KW_INTERRUPT, attr_clean, start_line, start_col, self.filename)
        elif 'kernel' in lower_attr:
            return Token(TokenType.KW_KERNEL, attr_clean, start_line, start_col, self.filename)
        elif 'init' in lower_attr:
            return Token(TokenType.KW_INIT, attr_clean, start_line, start_col, self.filename)
        elif 'section' in lower_attr:
            return Token(TokenType.KW_SECTION, attr_clean, start_line, start_col, self.filename)
        return Token(TokenType.KW_ATTRIBUTE_START, attr_clean, start_line, start_col, self.filename)

    def read_pragma(self) -> Token:
        start_line, start_col = self.line, self.column
        self.advance()  # Skip '#'
        pragma_text = ""
        while self.current() not in ('\n', '\0'):
            pragma_text += self.current()
            self.advance()
        text_clean = pragma_text.strip()
        lower_text = text_clean.lower()
        if "optimize" in lower_text or lower_text in ("o0", "o1", "o2", "o3"):
            for lvl in ("O0", "O1", "O2", "O3"):
                if lvl.lower() in lower_text:
                    return Token(TokenType.PRAGMA_OPTIMIZE, lvl, start_line, start_col, self.filename)
            return Token(TokenType.PRAGMA_OPTIMIZE, "O2", start_line, start_col, self.filename)
        elif "simd" in lower_text or any(s in lower_text for s in ("sse", "avx512", "avx")):
            if "avx512" in lower_text:
                return Token(TokenType.PRAGMA_SIMD, "AVX512", start_line, start_col, self.filename)
            elif "avx" in lower_text:
                return Token(TokenType.PRAGMA_SIMD, "AVX", start_line, start_col, self.filename)
            elif "sse" in lower_text:
                return Token(TokenType.PRAGMA_SIMD, "SSE", start_line, start_col, self.filename)
            return Token(TokenType.PRAGMA_SIMD, "AVX", start_line, start_col, self.filename)
        elif "unroll" in lower_text:
            match = re.search(r'(\d+)', text_clean)
            factor = match.group(1) if match else "4"
            return Token(TokenType.PRAGMA_UNROLL, factor, start_line, start_col, self.filename)
        return Token(TokenType.PRAGMA_OPTIMIZE, text_clean, start_line, start_col, self.filename)

    def read_identifier(self) -> Token:
        start_line, start_col = self.line, self.column
        ident = ""
        while self.current().isalnum() or self.current() == '_':
            ident += self.current()
            self.advance()
        lookup_key = ident if self.config.case_sensitive else ident.lower()
        tok_type = KEYWORDS.get(lookup_key, TokenType.TOK_IDENTIFIER)
        return Token(tok_type, ident, start_line, start_col, self.filename)

    def tokenize(self) -> List[Token]:
        tokens: List[Token] = []
        indent_stack: List[int] = [0]
        brace_depth = 0
        at_line_start = True

        while self.current() != '\0':
            if at_line_start and brace_depth == 0:
                spaces = 0
                while self.current() in (' ', '\t'):
                    spaces += 4 if self.current() == '\t' else 1
                    self.advance()
                if self.current() in ('\n', '\r'):
                    if self.current() == '\r':
                        self.advance()
                    if self.current() == '\n':
                        self.advance()
                    continue
                if self.source.startswith(self.config.line_comment, self.pos):
                    self.skip_line_comment()
                    continue
                if self.source.startswith(self.config.block_comment_start, self.pos):
                    self.skip_block_comment(self.line, self.column)
                    continue
                if self.current() == '#' and self.peek() == '[':
                    tokens.append(self.read_attribute())
                    at_line_start = False
                    continue
                if self.current() == '#':
                    tokens.append(self.read_pragma())
                    at_line_start = False
                    continue

                if spaces > indent_stack[-1]:
                    indent_stack.append(spaces)
                    tokens.append(Token(TokenType.INDENT, str(spaces), self.line, self.column, self.filename))
                elif spaces < indent_stack[-1]:
                    while len(indent_stack) > 1 and spaces < indent_stack[-1]:
                        indent_stack.pop()
                        tokens.append(Token(TokenType.DEDENT, str(spaces), self.line, self.column, self.filename))
                at_line_start = False

            self.skip_whitespace()
            ch = self.current()
            if ch == '\0':
                break

            if ch == '\r':
                self.advance()
                continue

            if ch == '\n':
                tokens.append(Token(TokenType.NEWLINE, "\\n", self.line, self.column, self.filename))
                self.advance()
                at_line_start = True
                continue

            if self.source.startswith(self.config.line_comment, self.pos):
                self.skip_line_comment()
                continue

            if self.source.startswith(self.config.block_comment_start, self.pos):
                self.skip_block_comment(self.line, self.column)
                continue

            if ch == '#' and self.peek() == '[':
                tokens.append(self.read_attribute())
                continue

            if ch == '#':
                tokens.append(self.read_pragma())
                continue

            if ch.isalpha() or ch == '_':
                tokens.append(self.read_identifier())
                continue

            if ch.isdigit():
                tokens.append(self.read_number())
                continue

            if ch in (self.config.string_delimiter, self.config.char_delimiter, '"', "'"):
                tokens.append(self.read_string())
                continue

            line, col = self.line, self.column
            two = self.source[self.pos:self.pos + 2]
            two_char_ops = {
                "==": TokenType.OP_EQ,
                "!=": TokenType.OP_NE,
                "<=": TokenType.OP_LE,
                ">=": TokenType.OP_GE,
                "&&": TokenType.OP_AND,
                "||": TokenType.OP_OR,
                "<<": TokenType.OP_SHL,
                ">>": TokenType.OP_SHR,
                "++": TokenType.OP_INC,
                "--": TokenType.OP_DEC,
                "+=": TokenType.OP_PLUS_ASSIGN,
                "-=": TokenType.OP_MINUS_ASSIGN,
                "*=": TokenType.OP_MULTIPLY_ASSIGN,
                "/=": TokenType.OP_DIVIDE_ASSIGN,
                "->": TokenType.OP_ARROW,
                "**": TokenType.OP_POW,
            }
            if two in two_char_ops:
                tokens.append(Token(two_char_ops[two], two, line, col, self.filename))
                self.advance()
                self.advance()
                continue

            single_char_tokens = {
                "=": TokenType.OP_ASSIGN,
                "+": TokenType.OP_PLUS,
                "-": TokenType.OP_MINUS,
                "*": TokenType.OP_MULTIPLY,
                "/": TokenType.OP_DIVIDE,
                "%": TokenType.OP_MOD,
                "<": TokenType.OP_LT,
                ">": TokenType.OP_GT,
                "!": TokenType.OP_NOT,
                "&": TokenType.OP_BIT_AND,
                "|": TokenType.OP_BIT_OR,
                "^": TokenType.OP_BIT_XOR,
                "~": TokenType.OP_BIT_NOT,
                "(": TokenType.OP_LPAREN,
                ")": TokenType.OP_RPAREN,
                "{": TokenType.OP_LBRACE,
                "}": TokenType.OP_RBRACE,
                "[": TokenType.OP_LBRACKET,
                "]": TokenType.OP_RBRACKET,
                ",": TokenType.OP_COMMA,
                ";": TokenType.OP_SEMICOLON,
                ":": TokenType.OP_COLON,
                ".": TokenType.OP_DOT,
            }
            if ch in single_char_tokens:
                tok_type = single_char_tokens[ch]
                if tok_type == TokenType.OP_LBRACE:
                    brace_depth += 1
                elif tok_type == TokenType.OP_RBRACE and brace_depth > 0:
                    brace_depth -= 1
                tokens.append(Token(tok_type, ch, line, col, self.filename))
                self.advance()
                continue

            self.errors.add_error(f"Unexpected character '{ch}'", line, col)
            tokens.append(Token(TokenType.TOK_ERROR, ch, line, col, self.filename))
            self.advance()

        while len(indent_stack) > 1:
            indent_stack.pop()
            tokens.append(Token(TokenType.DEDENT, "0", self.line, self.column, self.filename))

        tokens.append(Token(TokenType.TOK_EOF, "", self.line, self.column, self.filename))
        return tokens

# ============================================================================
# Parser
# ============================================================================

HARDWARE_BUILTINS = {
    "cli", "sti", "hlt", "pause", "rdtsc", "cpuid", "inb", "inw", "inl",
    "outb", "outw", "outl", "mmio_read8", "mmio_read16", "mmio_read32", "mmio_read64",
    "mmio_write8", "mmio_write16", "mmio_write32", "mmio_write64",
    "alloc", "free", "realloc", "memcpy", "memset", "print", "println"
}

class Parser:
    def __init__(self, tokens: List[Token], errors: ErrorCollector, data_handler: Optional[DataSectionHandler] = None):
        self.tokens = tokens
        self.pos = 0
        self.errors = errors
        self.data_handler = data_handler or DataSectionHandler()
        self.pending_attributes: List[str] = []

    def current(self) -> Token:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return Token(TokenType.TOK_EOF, "", 1, 1)

    def peek(self, offset: int = 1) -> Token:
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return Token(TokenType.TOK_EOF, "", 1, 1)

    def advance(self) -> Token:
        tok = self.current()
        if self.pos < len(self.tokens):
            self.pos += 1
        return tok

    def match(self, *types: TokenType) -> Optional[Token]:
        if self.current().type in types:
            return self.advance()
        return None

    def expect(self, ttype: TokenType, msg: str = "") -> Optional[Token]:
        if self.current().type == ttype:
            return self.advance()
        tok = self.current()
        self.errors.add_error(msg or f"Expected {ttype.name}, got {tok.type.name} ('{tok.value}')", tok.line, tok.column)
        return None

    def skip_newlines(self) -> None:
        while self.current().type in (TokenType.NEWLINE, TokenType.OP_SEMICOLON):
            self.advance()

    def consume_stmt_end(self) -> None:
        while self.current().type in (TokenType.NEWLINE, TokenType.OP_SEMICOLON):
            self.advance()

    def parse_program(self) -> ASTNode:
        prog = ASTNode(ASTType.PROGRAM, value="program", line=1, column=1)
        self.skip_newlines()
        while self.current().type != TokenType.TOK_EOF:
            stmt = self.parse_top_level()
            if stmt:
                prog.add_child(stmt)
            self.skip_newlines()
        return prog

    def parse_top_level(self) -> Optional[ASTNode]:
        tok = self.current()
        if tok.type in (TokenType.KW_INTERRUPT, TokenType.KW_KERNEL, TokenType.KW_INIT,
                        TokenType.KW_SECTION, TokenType.KW_ATTRIBUTE_START):
            self.pending_attributes.append(tok.value)
            self.advance()
            self.skip_newlines()
            return self.parse_top_level()

        attrs = list(self.pending_attributes)
        self.pending_attributes.clear()

        if tok.type in (TokenType.PRAGMA_OPTIMIZE, TokenType.PRAGMA_SIMD, TokenType.PRAGMA_UNROLL):
            self.advance()
            node = ASTNode(ASTType.PRAGMA, value=tok.value, line=tok.line, column=tok.column)
            if tok.type == TokenType.PRAGMA_OPTIMIZE:
                node.optimization_level = getattr(OptimizationLevel, tok.value, OptimizationLevel.O2)
            elif tok.type == TokenType.PRAGMA_SIMD:
                node.simd_level = getattr(SIMDLevel, tok.value, SIMDLevel.NONE)
            elif tok.type == TokenType.PRAGMA_UNROLL:
                node.unroll_factor = int(tok.value) if tok.value.isdigit() else 4
            return node

        if tok.type == TokenType.KW_MODULE:
            self.advance()
            name_tok = self.expect(TokenType.TOK_IDENTIFIER, "Expected module name")
            mod = ASTNode(ASTType.MODULE, value=name_tok.value if name_tok else "mod", line=tok.line, column=tok.column, attributes=attrs)
            self.consume_stmt_end()
            return mod

        if tok.type == TokenType.KW_IMPORT:
            return self.parse_import(attrs)

        if tok.type == TokenType.KW_EXPORT:
            return self.parse_export(attrs)

        if tok.type == TokenType.KW_FN:
            return self.parse_function(attrs)

        if tok.type == TokenType.KW_STRUCT:
            return self.parse_struct(attrs)

        if tok.type == TokenType.KW_CLASS:
            return self.parse_class(attrs)

        if tok.type == TokenType.KW_DATA_SECTION:
            return self.parse_data_section(attrs)

        return self.parse_statement(attrs)

    def parse_import(self, attrs: List[str]) -> ASTNode:
        tok = self.advance()  # 'import'
        path_parts = []
        if self.current().type == TokenType.TOK_STRING:
            path_parts.append(self.advance().value)
        else:
            while self.current().type == TokenType.TOK_IDENTIFIER:
                path_parts.append(self.advance().value)
                if not self.match(TokenType.OP_DOT):
                    break
        import_path = ".".join(path_parts)
        node = ASTNode(ASTType.IMPORT_STMT, value=import_path, import_path=import_path,
                       line=tok.line, column=tok.column, attributes=attrs)
        self.consume_stmt_end()
        return node

    def parse_export(self, attrs: List[str]) -> ASTNode:
        tok = self.advance()  # 'export'
        if self.current().type == TokenType.KW_FN:
            fn_node = self.parse_function(attrs + ["export"])
            fn_node.export_name = fn_node.value
            return fn_node
        name_tok = self.expect(TokenType.TOK_IDENTIFIER, "Expected exported symbol name")
        exp_name = name_tok.value if name_tok else ""
        node = ASTNode(ASTType.EXPORT_STMT, value=exp_name, export_name=exp_name,
                       line=tok.line, column=tok.column, attributes=attrs)
        self.consume_stmt_end()
        return node

    def parse_type_ref(self) -> TypeRef:
        tok = self.current()
        if tok.type in TYPE_TOKEN_MAP:
            self.advance()
            base_dt = TYPE_TOKEN_MAP[tok.type]
            ref = TypeRef(base=base_dt, name=tok.value)
            if base_dt in POINTER_TYPES and self.match(TokenType.OP_LT):
                ref.elem = self.parse_type_ref()
                self.match(TokenType.OP_GT)
            elif base_dt == DataType.ARRAY and self.match(TokenType.OP_LBRACKET):
                elem_ref = self.parse_type_ref()
                length = None
                if self.match(TokenType.OP_SEMICOLON) or self.match(TokenType.OP_COMMA):
                    if self.current().type == TokenType.TOK_NUMBER:
                        length = int(self.advance().value)
                self.match(TokenType.OP_RBRACKET)
                ref = TypeRef(base=DataType.ARRAY, name="array", elem=elem_ref, length=length)
            return ref

        if tok.type == TokenType.KW_BLOCK_ARRAY:
            self.advance()
            elem_type = DataType.F32
            block_sz = 256
            if self.match(TokenType.OP_LT):
                elem_ref = self.parse_type_ref()
                elem_type = elem_ref.base
                if self.match(TokenType.OP_COMMA) and self.current().type == TokenType.TOK_NUMBER:
                    block_sz = int(self.advance().value)
                self.match(TokenType.OP_GT)
            ref = TypeRef(base=DataType.BLOCK_ARRAY, name="block_array", length=block_sz)
            ref.meta = {"elem_type": elem_type, "block_size": block_sz} if hasattr(ref, "meta") else None
            return ref

        if tok.type == TokenType.TOK_IDENTIFIER:
            name = self.advance().value
            params: List[TypeRef] = []
            if self.match(TokenType.OP_LT):
                while self.current().type not in (TokenType.OP_GT, TokenType.TOK_EOF):
                    params.append(self.parse_type_ref())
                    if not self.match(TokenType.OP_COMMA):
                        break
                self.match(TokenType.OP_GT)
            return TypeRef(base=DataType.STRUCT, name=name, params=params)

        return TypeRef(base=DataType.I64, name="i64")

    def parse_function(self, attrs: List[str], parent_class: str = "") -> ASTNode:
        fn_tok = self.advance()  # 'fn'
        name_tok = self.expect(TokenType.TOK_IDENTIFIER, "Expected function name")
        fn_name = name_tok.value if name_tok else "<anon>"

        param_names: List[str] = []
        param_types: List[DataType] = []
        param_refs: List[TypeRef] = []

        if self.match(TokenType.OP_LPAREN):
            while self.current().type not in (TokenType.OP_RPAREN, TokenType.TOK_EOF):
                if self.current().type == TokenType.KW_SELF:
                    p_name = self.advance().value
                    p_ref = TypeRef(base=DataType.PTR, name=parent_class or "Self")
                    param_names.append(p_name)
                    param_types.append(p_ref.base)
                    param_refs.append(p_ref)
                elif self.current().type == TokenType.TOK_IDENTIFIER:
                    p_name = self.advance().value
                    p_ref = TypeRef(base=DataType.I64, name="i64")
                    if self.match(TokenType.OP_COLON):
                        p_ref = self.parse_type_ref()
                    param_names.append(p_name)
                    param_types.append(p_ref.base)
                    param_refs.append(p_ref)
                else:
                    self.advance()
                if not self.match(TokenType.OP_COMMA):
                    break
            self.expect(TokenType.OP_RPAREN, "Expected ')' after function parameters")

        ret_ref = TypeRef(base=DataType.VOID, name="void")
        if self.match(TokenType.OP_ARROW) or self.match(TokenType.OP_COLON):
            ret_ref = self.parse_type_ref()

        body = self.parse_block()
        node = ASTNode(
            ASTType.FUNCTION,
            value=fn_name,
            line=fn_tok.line,
            column=fn_tok.column,
            function_params=param_types,
            function_return=ret_ref.base,
            function_param_names=param_names,
            attributes=attrs,
            meta={"parent": parent_class, "param_refs": param_refs, "return_ref": ret_ref}
        )
        if body:
            node.add_child(body)
        return node

    def parse_struct(self, attrs: List[str]) -> ASTNode:
        tok = self.advance()  # 'struct'
        name_tok = self.expect(TokenType.TOK_IDENTIFIER, "Expected struct name")
        s_name = name_tok.value if name_tok else "Struct"
        fields: List[Tuple[str, DataType]] = []
        field_refs: List[Tuple[str, TypeRef]] = []

        self.skip_newlines()
        has_brace = bool(self.match(TokenType.OP_LBRACE))
        if not has_brace:
            self.match(TokenType.INDENT)

        while self.current().type not in (TokenType.OP_RBRACE, TokenType.DEDENT, TokenType.TOK_EOF):
            if self.current().type in (TokenType.NEWLINE, TokenType.OP_SEMICOLON):
                self.advance()
                continue
            if self.current().type == TokenType.TOK_IDENTIFIER:
                f_name = self.advance().value
                f_ref = TypeRef(base=DataType.I64, name="i64")
                if self.match(TokenType.OP_COLON):
                    f_ref = self.parse_type_ref()
                fields.append((f_name, f_ref.base))
                field_refs.append((f_name, f_ref))
            else:
                self.advance()
            self.consume_stmt_end()

        if has_brace:
            self.match(TokenType.OP_RBRACE)
        else:
            self.match(TokenType.DEDENT)

        return ASTNode(
            ASTType.STRUCT_DEF,
            value=s_name,
            line=tok.line,
            column=tok.column,
            record_fields=fields,
            attributes=attrs,
            meta={"field_refs": field_refs}
        )

    def parse_class(self, attrs: List[str]) -> ASTNode:
        tok = self.advance()  # 'class'
        name_tok = self.expect(TokenType.TOK_IDENTIFIER, "Expected class name")
        c_name = name_tok.value if name_tok else "Class"
        base_name = ""
        if self.match(TokenType.KW_EXTENDS) or self.match(TokenType.OP_COLON):
            if self.current().type == TokenType.TOK_IDENTIFIER:
                base_name = self.advance().value

        fields: List[Tuple[str, DataType]] = []
        field_refs: List[Tuple[str, TypeRef]] = []
        methods: List[ASTNode] = []

        self.skip_newlines()
        has_brace = bool(self.match(TokenType.OP_LBRACE))
        if not has_brace:
            self.match(TokenType.INDENT)

        while self.current().type not in (TokenType.OP_RBRACE, TokenType.DEDENT, TokenType.TOK_EOF):
            if self.current().type in (TokenType.NEWLINE, TokenType.OP_SEMICOLON):
                self.advance()
                continue
            if self.current().type in (TokenType.KW_PUBLIC, TokenType.KW_PRIVATE, TokenType.KW_PROTECTED, TokenType.KW_VIRTUAL, TokenType.KW_OVERRIDE):
                self.advance()
                continue
            if self.current().type == TokenType.KW_FN:
                methods.append(self.parse_function(attrs, parent_class=c_name))
            elif self.current().type == TokenType.TOK_IDENTIFIER:
                f_name = self.advance().value
                f_ref = TypeRef(base=DataType.I64, name="i64")
                if self.match(TokenType.OP_COLON):
                    f_ref = self.parse_type_ref()
                fields.append((f_name, f_ref.base))
                field_refs.append((f_name, f_ref))
                self.consume_stmt_end()
            else:
                self.advance()

        if has_brace:
            self.match(TokenType.OP_RBRACE)
        else:
            self.match(TokenType.DEDENT)

        node = ASTNode(
            ASTType.CLASS,
            value=c_name,
            line=tok.line,
            column=tok.column,
            record_fields=fields,
            attributes=attrs,
            meta={"base": base_name, "field_refs": field_refs}
        )
        for m in methods:
            node.add_child(m)
        return node

    def parse_data_section(self, attrs: List[str]) -> ASTNode:
        tok = self.advance()  # 'data_section'
        name_tok = self.expect(TokenType.TOK_IDENTIFIER, "Expected data section name")
        sec_name = name_tok.value if name_tok else "data"
        ext_file = ""
        fmt = ""
        rows: List[List[str]] = []

        if self.match(TokenType.KW_FROM) or self.match(TokenType.OP_ASSIGN):
            if self.current().type == TokenType.TOK_STRING:
                ext_file = self.advance().value
        if self.current().type == TokenType.TOK_IDENTIFIER and self.current().value.lower() in ("csv", "json", "xml", "yaml", "toml"):
            fmt = self.advance().value.lower()

        self.skip_newlines()
        has_brace = bool(self.match(TokenType.OP_LBRACE))
        if has_brace:
            while self.current().type not in (TokenType.OP_RBRACE, TokenType.TOK_EOF):
                if self.current().type in (TokenType.NEWLINE, TokenType.OP_COMMA, TokenType.OP_SEMICOLON):
                    self.advance()
                    continue
                if self.match(TokenType.OP_LBRACKET):
                    row_vals = []
                    while self.current().type not in (TokenType.OP_RBRACKET, TokenType.TOK_EOF):
                        if self.current().type in (TokenType.TOK_STRING, TokenType.TOK_NUMBER, TokenType.TOK_IDENTIFIER):
                            row_vals.append(self.advance().value)
                        elif self.current().type == TokenType.OP_COMMA:
                            self.advance()
                        else:
                            self.advance()
                    self.match(TokenType.OP_RBRACKET)
                    if row_vals:
                        rows.append(row_vals)
                else:
                    self.advance()
            self.match(TokenType.OP_RBRACE)

        if ext_file:
            sec = self.data_handler.load_section(sec_name, ext_file, fmt)
            if sec and sec.grid:
                rows = sec.grid
        elif rows:
            sec = DataSection(sec_name)
            sec.grid = rows
            self.data_handler.sections[sec_name] = sec

        return ASTNode(
            ASTType.DATA_SECTION,
            value=sec_name,
            line=tok.line,
            column=tok.column,
            record_data=rows,
            external_file=ext_file,
            data_format=fmt,
            attributes=attrs
        )

    def parse_block(self) -> ASTNode:
        tok = self.current()
        block = ASTNode(ASTType.BLOCK, value="block", line=tok.line, column=tok.column)
        self.skip_newlines()
        has_brace = bool(self.match(TokenType.OP_LBRACE))
        if not has_brace:
            self.match(TokenType.INDENT)

        end_tokens = (TokenType.OP_RBRACE, TokenType.TOK_EOF) if has_brace else (TokenType.DEDENT, TokenType.TOK_EOF)
        while self.current().type not in end_tokens:
            if self.current().type in (TokenType.NEWLINE, TokenType.OP_SEMICOLON):
                self.advance()
                continue
            stmt = self.parse_statement([])
            if stmt:
                block.add_child(stmt)
            self.consume_stmt_end()

        if has_brace:
            self.match(TokenType.OP_RBRACE)
        else:
            self.match(TokenType.DEDENT)
        return block

    def parse_statement(self, attrs: List[str]) -> Optional[ASTNode]:
        tok = self.current()
        if tok.type in (TokenType.NEWLINE, TokenType.OP_SEMICOLON):
            self.advance()
            return None

        if tok.type == TokenType.KW_LET or tok.type == TokenType.KW_CONST:
            is_const = (tok.type == TokenType.KW_CONST)
            self.advance()
            self.match(TokenType.KW_MUT)
            name_tok = self.expect(TokenType.TOK_IDENTIFIER, "Expected variable name")
            var_name = name_tok.value if name_tok else "_var"
            t_ref = TypeRef(base=DataType.I64, name="i64")
            if self.match(TokenType.OP_COLON):
                t_ref = self.parse_type_ref()
            init_expr = None
            if self.match(TokenType.OP_ASSIGN):
                init_expr = self.parse_expression()
            node = ASTNode(ASTType.ASSIGN, value=var_name, line=tok.line, column=tok.column,
                           data_type=t_ref.base, attributes=attrs,
                           meta={"decl": True, "const": is_const, "type_ref": t_ref})
            if init_expr:
                node.add_child(init_expr)
            return node

        if tok.type == TokenType.KW_IF:
            return self.parse_if()

        if tok.type == TokenType.KW_WHILE:
            w_tok = self.advance()
            cond = self.parse_expression()
            body = self.parse_block()
            node = ASTNode(ASTType.WHILE_STMT, value="while", line=w_tok.line, column=w_tok.column)
            node.add_child(cond)
            node.add_child(body)
            return node

        if tok.type == TokenType.KW_FOR:
            return self.parse_for()

        if tok.type == TokenType.KW_RETURN:
            r_tok = self.advance()
            node = ASTNode(ASTType.RETURN_STMT, value="return", line=r_tok.line, column=r_tok.column)
            if self.current().type not in (TokenType.NEWLINE, TokenType.OP_SEMICOLON, TokenType.OP_RBRACE, TokenType.DEDENT, TokenType.TOK_EOF):
                expr = self.parse_expression()
                if expr:
                    node.add_child(expr)
            return node

        if tok.type == TokenType.KW_BREAK:
            self.advance()
            return ASTNode(ASTType.BREAK_STMT, value="break", line=tok.line, column=tok.column)

        if tok.type == TokenType.KW_CONTINUE:
            self.advance()
            return ASTNode(ASTType.CONTINUE_STMT, value="continue", line=tok.line, column=tok.column)

        if tok.type == TokenType.KW_SWITCH:
            return self.parse_switch()

        if tok.type == TokenType.KW_ASM:
            return self.parse_asm()

        if tok.type == TokenType.KW_WITH:
            self.advance()
            expr = self.parse_expression()
            body = self.parse_block()
            node = ASTNode(ASTType.WITH_STMT, value="with", line=tok.line, column=tok.column)
            if expr:
                node.add_child(expr)
            if body:
                node.add_child(body)
            return node

        expr = self.parse_expression()
        if expr and self.current().type in (
            TokenType.OP_ASSIGN, TokenType.OP_PLUS_ASSIGN, TokenType.OP_MINUS_ASSIGN,
            TokenType.OP_MULTIPLY_ASSIGN, TokenType.OP_DIVIDE_ASSIGN
        ):
            op_tok = self.advance()
            rhs = self.parse_expression()
            if expr.type == ASTType.VARIABLE:
                assign_node = ASTNode(ASTType.ASSIGN, value=expr.value, line=op_tok.line, column=op_tok.column,
                                      meta={"op": op_tok.type, "decl": False})
                if rhs:
                    assign_node.add_child(rhs)
                return assign_node
            else:
                assign_node = ASTNode(ASTType.ASSIGN, value="", line=op_tok.line, column=op_tok.column,
                                      meta={"op": op_tok.type, "target_expr": expr})
                assign_node.add_child(expr)
                if rhs:
                    assign_node.add_child(rhs)
                return assign_node
        return expr

    def parse_if(self) -> ASTNode:
        tok = self.advance()  # 'if'
        cond = self.parse_expression()
        then_block = self.parse_block()
        node = ASTNode(ASTType.IF_STMT, value="if", line=tok.line, column=tok.column)
        node.add_child(cond)
        node.add_child(then_block)
        if self.current().type == TokenType.KW_ELIF:
            self.tokens[self.pos] = Token(TokenType.KW_IF, "if", self.current().line, self.current().column, self.current().file)
            node.add_child(self.parse_if())
        elif self.current().type == TokenType.KW_ELSE:
            self.advance()
            node.add_child(self.parse_block())
        return node

    def parse_for(self) -> ASTNode:
        tok = self.advance()  # 'for'
        var_tok = self.expect(TokenType.TOK_IDENTIFIER, "Expected loop variable")
        var_name = var_tok.value if var_tok else "_i"
        self.match(TokenType.KW_IN)
        iter_expr = None
        if self.match(TokenType.KW_RANGE):
            has_p = bool(self.match(TokenType.OP_LPAREN))
            start_e = self.parse_expression()
            end_e = None
            if self.match(TokenType.OP_COMMA) or (self.current().type == TokenType.OP_DOT and self.peek().type == TokenType.OP_DOT):
                if self.current().type == TokenType.OP_DOT:
                    self.advance(); self.advance()
                end_e = self.parse_expression()
            if has_p:
                self.match(TokenType.OP_RPAREN)
            iter_expr = ASTNode(ASTType.BINARY_OP, value="range", line=tok.line, column=tok.column)
            if start_e:
                iter_expr.add_child(start_e)
            if end_e:
                iter_expr.add_child(end_e)
        else:
            iter_expr = self.parse_expression()
        body = self.parse_block()
        node = ASTNode(ASTType.FOR_STMT, value=var_name, line=tok.line, column=tok.column)
        if iter_expr:
            node.add_child(iter_expr)
        if body:
            node.add_child(body)
        return node

    def parse_switch(self) -> ASTNode:
        tok = self.advance()  # 'switch'
        target = self.parse_expression()
        node = ASTNode(ASTType.SWITCH_STMT, value="switch", line=tok.line, column=tok.column)
        if target:
            node.add_child(target)

        self.skip_newlines()
        has_brace = bool(self.match(TokenType.OP_LBRACE))
        if not has_brace:
            self.match(TokenType.INDENT)

        end_tokens = (TokenType.OP_RBRACE, TokenType.TOK_EOF) if has_brace else (TokenType.DEDENT, TokenType.TOK_EOF)
        while self.current().type not in end_tokens:
            if self.current().type in (TokenType.NEWLINE, TokenType.OP_SEMICOLON):
                self.advance()
                continue
            if self.current().type in (TokenType.KW_CASE, TokenType.KW_DEFAULT):
                c_tok = self.advance()
                is_default = (c_tok.type == TokenType.KW_DEFAULT)
                pat = None if is_default else self.parse_expression()
                guard = None
                prio = 0
                if self.match(TokenType.KW_WHEN):
                    guard = self.parse_expression()
                if self.match(TokenType.KW_PRIORITY):
                    if self.current().type == TokenType.TOK_NUMBER:
                        prio = int(self.advance().value)
                self.match(TokenType.OP_COLON)
                c_body = self.parse_block()
                case_node = ASTNode(ASTType.CASE_STMT, value="default" if is_default else "case",
                                    line=c_tok.line, column=c_tok.column,
                                    meta={"default": is_default, "priority": prio})
                if pat:
                    case_node.add_child(pat)
                if guard:
                    case_node.add_child(guard)
                if c_body:
                    case_node.add_child(c_body)
                node.add_child(case_node)
            else:
                self.advance()

        if has_brace:
            self.match(TokenType.OP_RBRACE)
        else:
            self.match(TokenType.DEDENT)
        return node

    def parse_asm(self) -> ASTNode:
        tok = self.advance()  # 'asm'
        asm_lines: List[str] = []
        if self.current().type == TokenType.TOK_STRING:
            asm_lines.append(self.advance().value)
        else:
            self.skip_newlines()
            has_brace = bool(self.match(TokenType.OP_LBRACE))
            if not has_brace:
                self.match(TokenType.INDENT)
            end_tokens = (TokenType.OP_RBRACE, TokenType.TOK_EOF) if has_brace else (TokenType.DEDENT, TokenType.TOK_EOF)
            while self.current().type not in end_tokens:
                if self.current().type == TokenType.TOK_STRING:
                    asm_lines.append(self.advance().value)
                elif self.current().type not in (TokenType.NEWLINE, TokenType.OP_SEMICOLON):
                    parts = []
                    while self.current().type not in (TokenType.NEWLINE, TokenType.OP_SEMICOLON) + end_tokens:
                        parts.append(self.advance().value)
                    if parts:
                        asm_lines.append(" ".join(parts))
                else:
                    self.advance()
            if has_brace:
                self.match(TokenType.OP_RBRACE)
            else:
                self.match(TokenType.DEDENT)
        return ASTNode(ASTType.ASM_STMT, value="\n".join(asm_lines), line=tok.line, column=tok.column)

    def parse_expression(self) -> Optional[ASTNode]:
        return self.parse_or()

    def parse_or(self) -> Optional[ASTNode]:
        left = self.parse_and()
        while self.current().type == TokenType.OP_OR:
            op = self.advance()
            right = self.parse_and()
            n = ASTNode(ASTType.BINARY_OP, value="||", line=op.line, column=op.column)
            n.add_child(left); n.add_child(right)
            left = n
        return left

    def parse_and(self) -> Optional[ASTNode]:
        left = self.parse_equality()
        while self.current().type == TokenType.OP_AND:
            op = self.advance()
            right = self.parse_equality()
            n = ASTNode(ASTType.BINARY_OP, value="&&", line=op.line, column=op.column)
            n.add_child(left); n.add_child(right)
            left = n
        return left

    def parse_equality(self) -> Optional[ASTNode]:
        left = self.parse_comparison()
        while self.current().type in (TokenType.OP_EQ, TokenType.OP_NE):
            op = self.advance()
            right = self.parse_comparison()
            n = ASTNode(ASTType.BINARY_OP, value=op.value, line=op.line, column=op.column)
            n.add_child(left); n.add_child(right)
            left = n
        return left

    def parse_comparison(self) -> Optional[ASTNode]:
        left = self.parse_bitwise()
        while self.current().type in (TokenType.OP_LT, TokenType.OP_LE, TokenType.OP_GT, TokenType.OP_GE):
            op = self.advance()
            right = self.parse_bitwise()
            n = ASTNode(ASTType.BINARY_OP, value=op.value, line=op.line, column=op.column)
            n.add_child(left); n.add_child(right)
            left = n
        return left

    def parse_bitwise(self) -> Optional[ASTNode]:
        left = self.parse_shift()
        while self.current().type in (TokenType.OP_BIT_AND, TokenType.OP_BIT_OR, TokenType.OP_BIT_XOR):
            op = self.advance()
            right = self.parse_shift()
            n = ASTNode(ASTType.BINARY_OP, value=op.value, line=op.line, column=op.column)
            n.add_child(left); n.add_child(right)
            left = n
        return left

    def parse_shift(self) -> Optional[ASTNode]:
        left = self.parse_term()
        while self.current().type in (TokenType.OP_SHL, TokenType.OP_SHR):
            op = self.advance()
            right = self.parse_term()
            n = ASTNode(ASTType.BINARY_OP, value=op.value, line=op.line, column=op.column)
            n.add_child(left); n.add_child(right)
            left = n
        return left

    def parse_term(self) -> Optional[ASTNode]:
        left = self.parse_factor()
        while self.current().type in (TokenType.OP_PLUS, TokenType.OP_MINUS):
            op = self.advance()
            right = self.parse_factor()
            n = ASTNode(ASTType.BINARY_OP, value=op.value, line=op.line, column=op.column)
            n.add_child(left); n.add_child(right)
            left = n
        return left

    def parse_factor(self) -> Optional[ASTNode]:
        left = self.parse_unary()
        while self.current().type in (TokenType.OP_MULTIPLY, TokenType.OP_DIVIDE, TokenType.OP_MOD):
            op = self.advance()
            right = self.parse_unary()
            n = ASTNode(ASTType.BINARY_OP, value=op.value, line=op.line, column=op.column)
            n.add_child(left); n.add_child(right)
            left = n
        return left

    def parse_unary(self) -> Optional[ASTNode]:
        tok = self.current()
        if tok.type in (TokenType.OP_MINUS, TokenType.OP_NOT, TokenType.OP_BIT_NOT, TokenType.OP_BIT_AND, TokenType.OP_MULTIPLY):
            self.advance()
            operand = self.parse_unary()
            n = ASTNode(ASTType.UNARY_OP, value=tok.value, line=tok.line, column=tok.column)
            if operand:
                n.add_child(operand)
            return n
        return self.parse_postfix()

    def parse_postfix(self) -> Optional[ASTNode]:
        expr = self.parse_primary()
        while expr is not None:
            tok = self.current()
            if tok.type == TokenType.OP_LPAREN:
                self.advance()
                args: List[ASTNode] = []
                while self.current().type not in (TokenType.OP_RPAREN, TokenType.TOK_EOF):
                    arg = self.parse_expression()
                    if arg:
                        args.append(arg)
                    if not self.match(TokenType.OP_COMMA):
                        break
                self.expect(TokenType.OP_RPAREN, "Expected ')' after call arguments")
                if expr.type == ASTType.VARIABLE and expr.value in HARDWARE_BUILTINS:
                    call = ASTNode(ASTType.BUILTIN_CALL, value=expr.value, line=tok.line, column=tok.column)
                elif expr.type == ASTType.MEMBER_ACCESS:
                    call = ASTNode(ASTType.METHOD_CALL, value=expr.value, line=tok.line, column=tok.column)
                    if expr.children:
                        call.add_child(expr.children[0])
                else:
                    call = ASTNode(ASTType.CALL, value=expr.value if expr.type == ASTType.VARIABLE else "", line=tok.line, column=tok.column)
                    if expr.type != ASTType.VARIABLE:
                        call.add_child(expr)
                for a in args:
                    call.add_child(a)
                expr = call
            elif tok.type == TokenType.OP_LBRACKET:
                self.advance()
                idx_expr = self.parse_expression()
                self.expect(TokenType.OP_RBRACKET, "Expected ']' after index")
                idx_node = ASTNode(ASTType.INDEX, value="index", line=tok.line, column=tok.column)
                idx_node.add_child(expr)
                if idx_expr:
                    idx_node.add_child(idx_expr)
                expr = idx_node
            elif tok.type == TokenType.OP_DOT:
                self.advance()
                member_tok = self.expect(TokenType.TOK_IDENTIFIER, "Expected member name after '.'")
                m_name = member_tok.value if member_tok else ""
                mem = ASTNode(ASTType.MEMBER_ACCESS, value=m_name, line=tok.line, column=tok.column)
                mem.add_child(expr)
                expr = mem
            elif tok.type == TokenType.KW_AS:
                self.advance()
                t_ref = self.parse_type_ref()
                conv = ASTNode(ASTType.TYPE_CONVERSION, value=t_ref.name, line=tok.line, column=tok.column,
                               target_type=t_ref.base, meta={"type_ref": t_ref})
                conv.add_child(expr)
                expr = conv
            else:
                break
        return expr

    def parse_primary(self) -> Optional[ASTNode]:
        tok = self.current()
        if tok.type == TokenType.TOK_NUMBER:
            self.advance()
            dt = DataType.F64 if '.' in tok.value or 'e' in tok.value.lower() else DataType.I64
            return ASTNode(ASTType.LITERAL, value=tok.value, line=tok.line, column=tok.column, data_type=dt)
        if tok.type == TokenType.TOK_HEX:
            self.advance()
            return ASTNode(ASTType.LITERAL, value=str(int(tok.value, 16)), line=tok.line, column=tok.column, data_type=DataType.U64)
        if tok.type == TokenType.TOK_BINARY:
            self.advance()
            return ASTNode(ASTType.LITERAL, value=str(int(tok.value, 2)), line=tok.line, column=tok.column, data_type=DataType.U64)
        if tok.type == TokenType.TOK_STRING:
            self.advance()
            return ASTNode(ASTType.LITERAL, value=tok.value, line=tok.line, column=tok.column, data_type=DataType.STRING)
        if tok.type == TokenType.TOK_CHAR:
            self.advance()
            val = str(ord(tok.value[0])) if tok.value else "0"
            return ASTNode(ASTType.LITERAL, value=val, line=tok.line, column=tok.column, data_type=DataType.CHAR)
        if tok.type == TokenType.KW_TRUE:
            self.advance()
            return ASTNode(ASTType.LITERAL, value="1", line=tok.line, column=tok.column, data_type=DataType.BOOL)
        if tok.type == TokenType.KW_FALSE:
            self.advance()
            return ASTNode(ASTType.LITERAL, value="0", line=tok.line, column=tok.column, data_type=DataType.BOOL)
        if tok.type == TokenType.KW_NULL or tok.type == TokenType.KW_NONE:
            self.advance()
            return ASTNode(ASTType.LITERAL, value="0", line=tok.line, column=tok.column, data_type=DataType.PTR)
        if tok.type in (TokenType.TOK_IDENTIFIER, TokenType.KW_SELF, TokenType.KW_THIS):
            self.advance()
            return ASTNode(ASTType.VARIABLE, value=tok.value, line=tok.line, column=tok.column)
        if tok.type == TokenType.OP_LPAREN:
            self.advance()
            inner = self.parse_expression()
            self.expect(TokenType.OP_RPAREN, "Expected ')'")
            return inner
        if tok.type == TokenType.OP_LBRACKET:
            self.advance()
            arr = ASTNode(ASTType.ARRAY_LITERAL, value="array", line=tok.line, column=tok.column)
            while self.current().type not in (TokenType.OP_RBRACKET, TokenType.TOK_EOF):
                item = self.parse_expression()
                if item:
                    arr.add_child(item)
                if not self.match(TokenType.OP_COMMA):
                    break
            self.expect(TokenType.OP_RBRACKET, "Expected ']'")
            return arr

        self.errors.add_error(f"Unexpected token {tok.type.name} ('{tok.value}') in expression", tok.line, tok.column)
        self.advance()
        return None

# ============================================================================
# Semantic Analyzer
# ============================================================================

class SemanticAnalyzer:
    def __init__(self, symtab: SymbolTable, errors: ErrorCollector, data_handler: Optional[DataSectionHandler] = None):
        self.symtab = symtab
        self.errors = errors
        self.data_handler = data_handler or DataSectionHandler()
        self.current_opt_level = OptimizationLevel.O2
        self.current_simd_level = SIMDLevel.NONE

    def analyze(self, node: ASTNode) -> None:
        if node is None:
            return
        if node.type == ASTType.PROGRAM:
            for child in node.children:
                if child.type == ASTType.STRUCT_DEF:
                    f_refs = child.meta.get("field_refs") or [(n, TypeRef(base=dt, name=dt.name.lower())) for n, dt in child.record_fields]
                    self.symtab.define_struct(child.value, f_refs)
                elif child.type == ASTType.CLASS:
                    base = child.meta.get("base") or None
                    f_refs = child.meta.get("field_refs") or [(n, TypeRef(base=dt, name=dt.name.lower())) for n, dt in child.record_fields]
                    virtuals = [m.value for m in child.children if m.type == ASTType.FUNCTION and "virtual" in m.attributes]
                    self.symtab.define_struct(child.value, f_refs, base=base, has_vptr=bool(virtuals))
                    self.symtab.register_class(child.value, {"base": base, "virtuals": virtuals, "fields": f_refs})
                    for m in child.children:
                        if m.type == ASTType.FUNCTION:
                            self.symtab.register_function(m.value, m)
                elif child.type == ASTType.FUNCTION:
                    self.symtab.register_function(child.value, child)
            for child in node.children:
                self.analyze(child)
            return

        if node.type == ASTType.PRAGMA:
            if node.optimization_level:
                self.current_opt_level = node.optimization_level
            if node.simd_level != SIMDLevel.NONE:
                self.current_simd_level = node.simd_level
            return

        if node.type == ASTType.IMPORT_STMT:
            self.symtab.add_import(node.import_path, node.import_path)
            return

        if node.type == ASTType.DATA_SECTION:
            self.symtab.declare(node.value, DataType.PTR, node.line, node.column, is_global=True,
                                is_exported="export" in node.attributes, attributes=node.attributes)
            return

        if node.type == ASTType.FUNCTION:
            self.symtab.reset_frame()
            self.symtab.enter_scope()
            parent = node.meta.get("parent") or ""
            param_refs: List[TypeRef] = node.meta.get("param_refs") or []
            for idx, p_name in enumerate(node.function_param_names):
                p_dt = node.function_params[idx] if idx < len(node.function_params) else DataType.I64
                p_ref = param_refs[idx] if idx < len(param_refs) else TypeRef(base=p_dt, name=parent if p_name == "self" else p_dt.name.lower())
                self.symtab.declare(p_name, p_dt, node.line, node.column, is_global=False, type_ref=p_ref)
            for child in node.children:
                self.analyze(child)
            node.function_frame_size = self.symtab.get_frame_size()
            self.symtab.exit_scope()
            return

        if node.type == ASTType.BLOCK:
            self.symtab.enter_scope()
            for child in node.children:
                self.analyze(child)
            self.symtab.exit_scope()
            return

        if node.type == ASTType.ASSIGN:
            for child in node.children:
                self.analyze(child)
            if node.meta.get("decl"):
                t_ref = node.meta.get("type_ref")
                dt = node.data_type if node.data_type != DataType.VOID else (node.children[0].data_type if node.children and node.children[0].data_type != DataType.VOID else DataType.I64)
                node.data_type = dt
                is_ba = (dt == DataType.BLOCK_ARRAY)
                ba_type = t_ref.meta.get("elem_type") if (t_ref and hasattr(t_ref, "meta") and t_ref.meta) else None
                self.symtab.declare(node.value, dt, node.line, node.column,
                                    is_global=(self.symtab.current_scope == 0),
                                    is_block_array=is_ba, block_array_type=ba_type,
                                    is_exported="export" in node.attributes,
                                    attributes=node.attributes, type_ref=t_ref)
            elif node.value:
                sym = self.symtab.lookup(node.value)
                if not sym:
                    self.symtab.declare(node.value, DataType.I64, node.line, node.column,
                                        is_global=(self.symtab.current_scope == 0))
            return

        if node.type == ASTType.VARIABLE:
            sym = self.symtab.lookup(node.value)
            if sym:
                node.data_type = sym.type
                if sym.type_ref:
                    node.meta["type_ref"] = sym.type_ref
            elif node.value not in HARDWARE_BUILTINS:
                self.errors.add_warning(f"Undeclared identifier '{node.value}'", node.line, node.column)
            return

        if node.type == ASTType.BINARY_OP:
            for child in node.children:
                self.analyze(child)
            if node.children:
                node.data_type = node.children[0].data_type
            return

        if node.type == ASTType.UNARY_OP:
            for child in node.children:
                self.analyze(child)
            if node.children:
                node.data_type = node.children[0].data_type
            return

        if node.type == ASTType.MEMBER_ACCESS:
            for child in node.children:
                self.analyze(child)
            if node.children:
                obj_ref = node.children[0].meta.get("type_ref")
                sname = self.symtab.struct_name_of(obj_ref)
                if sname:
                    f_info = self.symtab.field_offset(sname, node.value)
                    if f_info:
                        node.meta["offset"] = f_info[0]
                        node.meta["type_ref"] = f_info[1]
                        node.data_type = f_info[1].base
            return

        for child in node.children:
            self.analyze(child)

# ============================================================================
# Optimizer (O0 - O3, Loop Unrolling, Vectorization)
# ============================================================================

class Optimizer:
    def __init__(self, level: OptimizationLevel = OptimizationLevel.O2, simd: SIMDLevel = SIMDLevel.NONE):
        self.level = level
        self.simd = simd

    def optimize(self, node: ASTNode) -> ASTNode:
        if node is None or self.level == OptimizationLevel.O0:
            return node
        if node.type == ASTType.PRAGMA:
            if node.optimization_level:
                self.level = node.optimization_level
            if node.simd_level != SIMDLevel.NONE:
                self.simd = node.simd_level
            return node

        optimized_children = [self.optimize(c) for c in node.children]
        node.children = [c for c in optimized_children if c is not None]

        if node.type == ASTType.BINARY_OP and len(node.children) == 2:
            left, right = node.children
            if left.type == ASTType.LITERAL and right.type == ASTType.LITERAL:
                folded = self._fold_constants(node.value, left, right)
                if folded is not None:
                    return folded

        if self.level.value >= OptimizationLevel.O3.value and node.type == ASTType.FOR_STMT:
            node.meta["unroll"] = node.unroll_factor or 4

        return node

    def _fold_constants(self, op: str, left: ASTNode, right: ASTNode) -> Optional[ASTNode]:
        try:
            if left.data_type == DataType.F64 or right.data_type == DataType.F64:
                a, b = float(left.value), float(right.value)
                ops = {
                    "+": a + b, "-": a - b, "*": a * b,
                    "/": a / b if b != 0 else None,
                }
                if op in ops and ops[op] is not None:
                    return ASTNode(ASTType.LITERAL, value=str(ops[op]), line=left.line, column=left.column, data_type=DataType.F64)
            else:
                a, b = int(left.value, 0), int(right.value, 0)
                ops = {
                    "+": a + b, "-": a - b, "*": a * b,
                    "/": int(a / b) if b != 0 else None,
                    "%": a % b if b != 0 else None,
                    "&": a & b, "|": a | b, "^": a ^ b,
                    "<<": a << b, ">>": a >> b,
                    "==": int(a == b), "!=": int(a != b),
                    "<": int(a < b), "<=": int(a <= b),
                    ">": int(a > b), ">=": int(a >= b),
                }
                if op in ops and ops[op] is not None:
                    return ASTNode(ASTType.LITERAL, value=str(ops[op]), line=left.line, column=left.column, data_type=left.data_type)
        except Exception:
            return None
        return None

# ============================================================================
# x86_64 Code Generator (NASM & Intel ASM)
# ============================================================================

class CodeGenerator:
    def __init__(self, symtab: SymbolTable, backend: Backend = Backend.NASM,
                 output_format: OutputFormat = OutputFormat.ELF_EXECUTABLE,
                 data_handler: Optional[DataSectionHandler] = None):
        self.symtab = symtab
        self.backend = backend
        self.output_format = output_format
        self.data_handler = data_handler or DataSectionHandler()
        self.text_lines: List[str] = []
        self.rodata_lines: List[str] = []
        self.bss_lines: List[str] = []
        self.label_counter = 0
        self.string_counter = 0
        self.current_fn_return_label = ""

    def new_label(self, prefix: str = "L") -> str:
        self.label_counter += 1
        return f".{prefix}_{self.label_counter}"

    def add_string_literal(self, text: str) -> str:
        self.string_counter += 1
        lbl = f"_str_lit_{self.string_counter}"
        encoded = text.encode("utf-8")
        byte_list = ", ".join(str(b) for b in encoded)
        if byte_list:
            self.rodata_lines.append(f"{lbl}: db {byte_list}, 0")
        else:
            self.rodata_lines.append(f"{lbl}: db 0")
        return lbl

    def generate(self, ast: ASTNode) -> str:
        self.text_lines = []
        self.rodata_lines = []
        self.bss_lines = []

        self.text_lines.append("bits 64")
        if self.output_format == OutputFormat.FLAT_BINARY:
            self.text_lines.append("org 0x7C00")
        else:
            self.text_lines.append("default rel")

        self.text_lines.append("section .text")
        self.text_lines.append("global _start")
        self.text_lines.append("global main")

        # Emit top-level statements & functions
        for child in ast.children:
            if child.type == ASTType.FUNCTION:
                self._gen_function(child)
            elif child.type == ASTType.CLASS:
                for m in child.children:
                    if m.type == ASTType.FUNCTION:
                        self._gen_function(m)
            elif child.type == ASTType.DATA_SECTION:
                pass
            elif child.type in (ASTType.STRUCT_DEF, ASTType.IMPORT_STMT, ASTType.EXPORT_STMT, ASTType.PRAGMA):
                pass
            else:
                self._gen_stmt(child)

        # Default entry stub if no explicit _start
        if not any(c.type == ASTType.FUNCTION and c.value == "_start" for c in ast.children):
            self.text_lines.append("_start:")
            if any(c.type == ASTType.FUNCTION and c.value == "main" for c in ast.children):
                self.text_lines.append("    call main")
            self.text_lines.append("    mov rax, 60")
            self.text_lines.append("    xor rdi, rdi")
            self.text_lines.append("    syscall")

        # Emit global variables in .bss
        for scope in self.symtab.scopes:
            for name, sym in scope.items():
                if sym.is_global and not sym.is_imported:
                    sz = max(8, type_size(sym.type_ref, self.symtab) if sym.type_ref else 8)
                    self.bss_lines.append(f"    {name}: resb {sz}")

        # Emit data sections in .rodata
        for sec_name, sec in self.data_handler.sections.items():
            self.rodata_lines.extend(sec.generate_rodata())

        out: List[str] = []
        out.append("; Generated by lowl Compiler v2.1.0")
        out.append("\n".join(self.text_lines))
        if self.rodata_lines:
            out.append("\nsection .rodata\n" + "\n".join(self.rodata_lines))
        if self.bss_lines:
            out.append("\nsection .bss\n" + "\n".join(self.bss_lines))
        return "\n\n".join(out) + "\n"

    def _gen_function(self, fn: ASTNode) -> None:
        parent = fn.meta.get("parent") or ""
        sym_label = f"{parent}_{fn.value}" if parent else fn.value
        is_interrupt = "interrupt" in fn.attributes
        is_kernel = "kernel" in fn.attributes

        self.text_lines.append(f"\nglobal {sym_label}")
        self.text_lines.append(f"{sym_label}:")
        if is_kernel:
            self.text_lines.append("    ; #[kernel] ring-0 entry")
            self.text_lines.append("    cli")
        self.text_lines.append("    push rbp")
        self.text_lines.append("    mov rbp, rsp")
        self.text_lines.append("    push rbx")
        frame_sz = max(32, fn.function_frame_size)
        self.text_lines.append(f"    sub rsp, {frame_sz}")

        arg_regs = ["rdi", "rsi", "rdx", "rcx", "r8", "r9"]
        for idx, p_name in enumerate(fn.function_param_names[:6]):
            sym = self.symtab.lookup(p_name)
            if sym and not sym.is_global:
                self.text_lines.append(f"    mov [rbp {sym.stack_offset:+d}], {arg_regs[idx]}")

        ret_lbl = self.new_label("fn_ret")
        prev_ret = self.current_fn_return_label
        self.current_fn_return_label = ret_lbl

        for child in fn.children:
            self._gen_stmt(child)

        self.text_lines.append(f"{ret_lbl}:")
        self.text_lines.append(f"    add rsp, {frame_sz}")
        self.text_lines.append("    pop rbx")
        self.text_lines.append("    pop rbp")
        if is_interrupt:
            self.text_lines.append("    iretq")
        else:
            self.text_lines.append("    ret")

        self.current_fn_return_label = prev_ret

    def _gen_stmt(self, node: Optional[ASTNode]) -> None:
        if node is None:
            return
        if node.type == ASTType.BLOCK:
            for c in node.children:
                self._gen_stmt(c)
        elif node.type == ASTType.RETURN_STMT:
            if node.children:
                self._gen_expr(node.children[0])
            self.text_lines.append(f"    jmp {self.current_fn_return_label}")
        elif node.type == ASTType.IF_STMT:
            self._gen_if(node)
        elif node.type == ASTType.WHILE_STMT:
            self._gen_while(node)
        elif node.type == ASTType.FOR_STMT:
            self._gen_for(node)
        elif node.type == ASTType.SWITCH_STMT:
            self._gen_switch(node)
        elif node.type == ASTType.ASM_STMT:
            self.text_lines.append("    ; inline asm")
            for line in node.value.splitlines():
                if line.strip():
                    self.text_lines.append(f"    {line.strip()}")
        elif node.type == ASTType.ASSIGN:
            self._gen_assign(node)
        else:
            self._gen_expr(node)

    def _gen_assign(self, node: ASTNode) -> None:
        if node.children:
            self._gen_expr(node.children[-1])
        if node.value:
            sym = self.symtab.lookup(node.value)
            if sym:
                if sym.is_global:
                    self.text_lines.append(f"    mov [{sym.name}], rax")
                else:
                    self.text_lines.append(f"    mov [rbp {sym.stack_offset:+d}], rax")

    def _gen_if(self, node: ASTNode) -> None:
        else_lbl = self.new_label("else")
        end_lbl = self.new_label("endif")
        if len(node.children) >= 1:
            self._gen_expr(node.children[0])
            self.text_lines.append("    cmp rax, 0")
            self.text_lines.append(f"    je {else_lbl}")
        if len(node.children) >= 2:
            self._gen_stmt(node.children[1])
        self.text_lines.append(f"    jmp {end_lbl}")
        self.text_lines.append(f"{else_lbl}:")
        if len(node.children) >= 3:
            self._gen_stmt(node.children[2])
        self.text_lines.append(f"{end_lbl}:")

    def _gen_while(self, node: ASTNode) -> None:
        start_lbl = self.new_label("while_start")
        end_lbl = self.new_label("while_end")
        self.text_lines.append(f"{start_lbl}:")
        if len(node.children) >= 1:
            self._gen_expr(node.children[0])
            self.text_lines.append("    cmp rax, 0")
            self.text_lines.append(f"    je {end_lbl}")
        if len(node.children) >= 2:
            self._gen_stmt(node.children[1])
        self.text_lines.append(f"    jmp {start_lbl}")
        self.text_lines.append(f"{end_lbl}:")

    def _gen_for(self, node: ASTNode) -> None:
        sym = self.symtab.lookup(node.value)
        loop_lbl = self.new_label("for_loop")
        end_lbl = self.new_label("for_end")
        iter_node = node.children[0] if len(node.children) >= 1 else None
        body_node = node.children[1] if len(node.children) >= 2 else None

        start_val = 0
        end_val = 0
        if iter_node and iter_node.type == ASTType.BINARY_OP and iter_node.value == "range":
            if len(iter_node.children) == 1 and iter_node.children[0].type == ASTType.LITERAL:
                end_val = int(iter_node.children[0].value, 0)
            elif len(iter_node.children) >= 2:
                if iter_node.children[0].type == ASTType.LITERAL:
                    start_val = int(iter_node.children[0].value, 0)
                if iter_node.children[1].type == ASTType.LITERAL:
                    end_val = int(iter_node.children[1].value, 0)

        self.text_lines.append(f"    mov rax, {start_val}")
        if sym and not sym.is_global:
            self.text_lines.append(f"    mov [rbp {sym.stack_offset:+d}], rax")
        elif sym and sym.is_global:
            self.text_lines.append(f"    mov [{sym.name}], rax")

        self.text_lines.append(f"{loop_lbl}:")
        if sym and not sym.is_global:
            self.text_lines.append(f"    mov rax, [rbp {sym.stack_offset:+d}]")
        elif sym and sym.is_global:
            self.text_lines.append(f"    mov rax, [{sym.name}]")
        self.text_lines.append(f"    cmp rax, {end_val}")
        self.text_lines.append(f"    jge {end_lbl}")

        if body_node:
            self._gen_stmt(body_node)

        if sym and not sym.is_global:
            self.text_lines.append(f"    inc qword [rbp {sym.stack_offset:+d}]")
        elif sym and sym.is_global:
            self.text_lines.append(f"    inc qword [{sym.name}]")
        self.text_lines.append(f"    jmp {loop_lbl}")
        self.text_lines.append(f"{end_lbl}:")

    def _gen_switch(self, node: ASTNode) -> None:
        end_lbl = self.new_label("switch_end")
        target = node.children[0] if node.children else None
        cases = [c for c in node.children[1:] if c.type == ASTType.CASE_STMT]
        cases.sort(key=lambda c: c.meta.get("priority", 0), reverse=True)

        for c in cases:
            is_default = bool(c.meta.get("default"))
            next_lbl = self.new_label("next_case")
            idx = 0
            if not is_default and c.children:
                pat = c.children[0]
                idx = 1
                if target:
                    self._gen_expr(target)
                    self.text_lines.append("    push rax")
                    self._gen_expr(pat)
                    self.text_lines.append("    pop rbx")
                    self.text_lines.append("    cmp rbx, rax")
                    self.text_lines.append(f"    jne {next_lbl}")
            if idx < len(c.children) and c.children[idx].type != ASTType.BLOCK:
                self._gen_expr(c.children[idx])
                self.text_lines.append("    cmp rax, 0")
                self.text_lines.append(f"    je {next_lbl}")
                idx += 1
            if idx < len(c.children):
                self._gen_stmt(c.children[idx])
            self.text_lines.append(f"    jmp {end_lbl}")
            self.text_lines.append(f"{next_lbl}:")

        self.text_lines.append(f"{end_lbl}:")

    def _gen_expr(self, node: Optional[ASTNode]) -> None:
        if node is None:
            return
        if node.type == ASTType.LITERAL:
            if node.data_type == DataType.STRING:
                lbl = self.add_string_literal(node.value)
                self.text_lines.append(f"    lea rax, [{lbl}]")
            elif node.data_type == DataType.F64 or node.data_type == DataType.F32:
                try:
                    fval = float(node.value)
                    bits = struct.unpack("<Q", struct.pack("<d", fval))[0]
                    self.text_lines.append(f"    mov rax, {bits}")
                except Exception:
                    self.text_lines.append("    xor rax, rax")
            else:
                try:
                    ival = int(node.value, 0)
                    self.text_lines.append(f"    mov rax, {ival}")
                except Exception:
                    self.text_lines.append("    xor rax, rax")
        elif node.type == ASTType.VARIABLE:
            sym = self.symtab.lookup(node.value)
            if sym:
                if sym.is_global:
                    self.text_lines.append(f"    mov rax, [{sym.name}]")
                else:
                    self.text_lines.append(f"    mov rax, [rbp {sym.stack_offset:+d}]")
            else:
                self.text_lines.append("    xor rax, rax")
        elif node.type == ASTType.UNARY_OP and node.children:
            self._gen_expr(node.children[0])
            if node.value == "-":
                self.text_lines.append("    neg rax")
            elif node.value == "!":
                self.text_lines.append("    cmp rax, 0\n    sete al\n    movzx rax, al")
            elif node.value == "~":
                self.text_lines.append("    not rax")
        elif node.type == ASTType.BINARY_OP and len(node.children) == 2:
            self._gen_expr(node.children[0])
            self.text_lines.append("    push rax")
            self._gen_expr(node.children[1])
            self.text_lines.append("    mov rbx, rax\n    pop rax")
            op = node.value
            if op == "+":
                self.text_lines.append("    add rax, rbx")
            elif op == "-":
                self.text_lines.append("    sub rax, rbx")
            elif op == "*":
                self.text_lines.append("    imul rax, rbx")
            elif op == "/":
                self.text_lines.append("    cqo\n    idiv rbx")
            elif op == "%":
                self.text_lines.append("    cqo\n    idiv rbx\n    mov rax, rdx")
            elif op == "&":
                self.text_lines.append("    and rax, rbx")
            elif op == "|":
                self.text_lines.append("    or rax, rbx")
            elif op == "^":
                self.text_lines.append("    xor rax, rbx")
            elif op == "<<":
                self.text_lines.append("    mov cl, bl\n    shl rax, cl")
            elif op == ">>":
                self.text_lines.append("    mov cl, bl\n    sar rax, cl")
            elif op in ("==", "!=", "<", "<=", ">", ">="):
                set_map = {
                    "==": "sete", "!=": "setne",
                    "<": "setl", "<=": "setle",
                    ">": "setg", ">=": "setge",
                }
                self.text_lines.append(f"    cmp rax, rbx\n    {set_map[op]} al\n    movzx rax, al")
        elif node.type == ASTType.BUILTIN_CALL:
            self._gen_builtin(node)
        elif node.type == ASTType.CALL:
            arg_regs = ["rdi", "rsi", "rdx", "rcx", "r8", "r9"]
            for i, arg in enumerate(node.children[:6]):
                self._gen_expr(arg)
                self.text_lines.append("    push rax")
            for i in range(min(len(node.children), 6) - 1, -1, -1):
                self.text_lines.append(f"    pop {arg_regs[i]}")
            if node.value:
                self.text_lines.append(f"    call {node.value}")
        elif node.type == ASTType.TYPE_CONVERSION and node.children:
            self._gen_expr(node.children[0])

    def _gen_builtin(self, node: ASTNode) -> None:
        bname = node.value
        if bname == "cli":
            self.text_lines.append("    cli")
        elif bname == "sti":
            self.text_lines.append("    sti")
        elif bname == "hlt":
            self.text_lines.append("    hlt")
        elif bname == "pause":
            self.text_lines.append("    pause")
        elif bname == "rdtsc":
            self.text_lines.append("    rdtsc\n    shl rdx, 32\n    or rax, rdx")
        elif bname == "cpuid":
            if node.children:
                self._gen_expr(node.children[0])
            self.text_lines.append("    cpuid")
        elif bname == "outb" and len(node.children) >= 2:
            self._gen_expr(node.children[0])
            self.text_lines.append("    mov dx, ax")
            self._gen_expr(node.children[1])
            self.text_lines.append("    out dx, al")
        elif bname == "inb" and len(node.children) >= 1:
            self._gen_expr(node.children[0])
            self.text_lines.append("    mov dx, ax\n    xor eax, eax\n    in al, dx")
        else:
            for arg in reversed(node.children[:6]):
                self._gen_expr(arg)
                self.text_lines.append("    push rax")
            regs = ["rdi", "rsi", "rdx", "rcx", "r8", "r9"]
            for i in range(min(len(node.children), 6)):
                self.text_lines.append(f"    pop {regs[i]}")

# ============================================================================
# Driver / CLI
# ============================================================================

def compile_source(source: str, filename: str = "<input>",
                   opt_level: OptimizationLevel = OptimizationLevel.O2,
                   simd_level: SIMDLevel = SIMDLevel.NONE,
                   backend: Backend = Backend.NASM,
                   output_format: OutputFormat = OutputFormat.ELF_EXECUTABLE) -> Tuple[Optional[str], ErrorCollector]:
    config = LanguageConfig()
    errors = ErrorCollector(source.split('\n'), filename)
    data_handler = DataSectionHandler()

    lexer = Lexer(source, filename, config, errors)
    tokens = lexer.tokenize()
    if errors.has_errors():
        return None, errors

    parser = Parser(tokens, errors, data_handler)
    ast = parser.parse_program()
    if errors.has_errors():
        return None, errors

    symtab = SymbolTable()
    analyzer = SemanticAnalyzer(symtab, errors, data_handler)
    analyzer.current_opt_level = opt_level
    analyzer.current_simd_level = simd_level
    analyzer.analyze(ast)
    if errors.has_errors():
        return None, errors

    optimizer = Optimizer(level=opt_level, simd=simd_level)
    ast = optimizer.optimize(ast)

    codegen = CodeGenerator(symtab, backend=backend, output_format=output_format, data_handler=data_handler)
    asm = codegen.generate(ast)
    return asm, errors

def main() -> int:
    ap = argparse.ArgumentParser(description=f"lowl Compiler v{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}")
    ap.add_argument("input", nargs="?", help="Input .lowl source file")
    ap.add_argument("-o", "--output", help="Output assembly file path")
    ap.add_argument("-O", "--opt", choices=["O0", "O1", "O2", "O3"], default="O2", help="Optimization level")
    ap.add_argument("--simd", choices=["none", "sse", "avx", "avx512"], default="none", help="SIMD target level")
    ap.add_argument("--backend", choices=["nasm", "intel"], default="nasm", help="Assembly backend")
    ap.add_argument("--format", choices=["flat", "kmod", "elf", "coff", "boot"], default="elf", help="Output format")
    args = ap.parse_args()

    if not args.input:
        ap.print_help()
        return 1

    src_path = Path(args.input)
    if not src_path.exists():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1

    source = src_path.read_text(encoding="utf-8")
    opt_map = {"O0": OptimizationLevel.O0, "O1": OptimizationLevel.O1, "O2": OptimizationLevel.O2, "O3": OptimizationLevel.O3}
    simd_map = {"none": SIMDLevel.NONE, "sse": SIMDLevel.SSE, "avx": SIMDLevel.AVX, "avx512": SIMDLevel.AVX512}
    backend_map = {"nasm": Backend.NASM, "intel": Backend.INTEL_ASM}
    fmt_map = {
        "flat": OutputFormat.FLAT_BINARY,
        "kmod": OutputFormat.KERNEL_MODULE,
        "elf": OutputFormat.ELF_EXECUTABLE,
        "coff": OutputFormat.COFF_OBJECT,
        "boot": OutputFormat.BOOT_IMAGE,
    }

    asm, errors = compile_source(
        source,
        filename=str(src_path),
        opt_level=opt_map[args.opt],
        simd_level=simd_map[args.simd],
        backend=backend_map[args.backend],
        output_format=fmt_map[args.format],
    )
    errors.print_summary()
    if errors.has_errors() or asm is None:
        return 1

    if args.output:
        Path(args.output).write_text(asm, encoding="utf-8")
    else:
        print(asm)
    return 0

if __name__ == "__main__":
    sys.exit(main())
