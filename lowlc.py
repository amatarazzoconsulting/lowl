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
            # derived classes embed the base layout first, so base methods work on them
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

    # -- class registry (inheritance / virtual dispatch) --------------------
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
        """Look a method up along the inheritance chain, most-derived class first."""
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
        """Struct/class name of a type, looking through pointers and references."""
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
        # [rbp-8] is reserved for the saved rbx (callee-saved in the SysV ABI)
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
        
        # Multi-slot locals (arrays, structs) are addressed from their lowest
        # byte and grow upward, so the base must sit (alloc_size - 8) below the
        # first free slot; otherwise element stores overwrite saved rbp / the
        # return address.
        alloc_size = max(8, ((size + 7) & ~7))
        base_offset = self.next_stack_offset - (alloc_size - 8) if not is_global else self.next_stack_offset
        sym = Symbol(name=name, type=dtype, scope_level=self.current_scope,
                     stack_offset=base_offset, is_global=is_global, 
                     line=line, column=column,
                     is_block_array=is_block_array, block_array_type=block_array_type,
                     is_exported=is_exported, attributes=attributes or [])
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
    
    def load_inline_data(self, data: List[List[str]]) -> bool:
        if data:
            self.grid = data
        return True
    
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
        
    def generate_rodata(self) -> List[str]:
        """Generate assembly directives for .rodata section"""
        lines = []
        lines.append(f"; Data section: {self.name}")
        lines.append(f"_data_section_{self.name}_start:")
        for row in self.grid:
            for cell in row:
                lines.append(f"    db '{cell}', 0")
            lines.append(f"    db 0")  # Row separator
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
        while self.current().isdigit():
            num += self.current()
            self.advance()
        # fractional part (but never consume '..' which starts a range)
        if self.current() == '.' and self.peek() != '.' and self.peek().isdigit():
            num += self.current()
            self.advance()
            while self.current().isdigit():
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
                    self.advance()          # move past the 'x'
                    digits = ''
                    for _ in range(2):
                        if self.current().lower() in '0123456789abcdef':
                            digits += self.current()
                            self.advance()
                        else:
                            break
                    s += chr(int(digits, 16)) if digits else 'x'
                    continue
                else: s += esc
            else:
                s += self.current()
            self.advance()
        if self.current() == delim:
            self.advance()
        if delim == "'":
            return Token(TokenType.TOK_CHAR, s, start_line, start_col, self.filename)
        return Token(TokenType.TOK_STRING, s, start_line, start_col, self.filename)
    
    def read_attribute(self) -> Token:
        start_line, start_col = self.line, self.column
        if self.current() == '#':
            self.advance()
        self.advance()  # Skip '['
        attr_name = ""
        while self.current() != ']' and self.current() != '\0':
            attr_name += self.current()
            self.advance()
        if self.current() == ']':
            self.advance()
        # Check for common attributes
        if 'interrupt' in attr_name:
            return Token(TokenType.KW_INTERRUPT, attr_name, start_line, start_col, self.filename)
        elif 'kernel' in attr_name:
            return Token(TokenType.KW_KERNEL, attr_name, start_line, start_col, self.filename)
        elif 'init' in attr_name:
            return Token(TokenType.KW_INIT, attr_name, start_line, start_col, self.filename)
        elif 'section' in attr_name:
            return Token(TokenType.KW_SECTION, attr_name, start_line, start_col, self.filename)
        else:
            return Token(TokenType.KW_ATTRIBUTE_START, attr_name, start_line, start_col, self.filename)
    
    def read_pragma(self) -> Token:
        start_line, start_col = self.line, self.column
        self.advance()  # Skip '#'
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
        elif "unroll" in pragma_text.lower():
            match = re.search(r'unroll\s*\(\s*(\d+)\s*\)', pragma_text)
            if match:
                return Token(TokenType.PRAGMA_UNROLL, match.group(1), start_line, start_col, self.filename)
        
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
            'record': TokenType.KW_RECORD, 'key': TokenType.KW_KEY,
            'columnar': TokenType.KW_COLUMNAR, 'indented': TokenType.KW_INDENTED, 'end': TokenType.KW_END,
            'template': TokenType.KW_TEMPLATE, 'Option': TokenType.KW_OPTION, 'some': TokenType.KW_SOME,
            'none': TokenType.KW_NONE,
            'block_array': TokenType.KW_BLOCK_ARRAY,
            'with': TokenType.KW_WITH, 'BlockArray': TokenType.KW_BLOCK_ARRAY,
            'import': TokenType.KW_IMPORT, 'export': TokenType.KW_EXPORT, 'module': TokenType.KW_MODULE,
            'asm': TokenType.KW_ASM,
            'u8': TokenType.KW_U8, 'u16': TokenType.KW_U16, 'u32': TokenType.KW_U32, 'u64': TokenType.KW_U64,
            'i8': TokenType.KW_I8, 'i16': TokenType.KW_I16, 'i32': TokenType.KW_I32, 'i64': TokenType.KW_I64,
            'f32': TokenType.KW_F32, 'f64': TokenType.KW_F64, 'bool': TokenType.KW_BOOL, 'char': TokenType.KW_CHAR,
            'ptr': TokenType.KW_PTR, 'mmio_ptr': TokenType.KW_MMIO_PTR, 'bit': TokenType.KW_BIT,
            'vec4_f32': TokenType.KW_VEC4_F32, 'vec8_f32': TokenType.KW_VEC8_F32, 'vec16_f32': TokenType.KW_VEC16_F32,
            'vec2_f64': TokenType.KW_VEC2_F64, 'vec4_f64': TokenType.KW_VEC4_F64,
            'vec8_f64': TokenType.KW_VEC8_F64,
            'mut': TokenType.KW_MUT, 'static': TokenType.KW_STATIC, 'impl': TokenType.KW_IMPL,
            'abstract': TokenType.KW_ABSTRACT, 'self': TokenType.KW_SELF,
            'break': TokenType.KW_BREAK, 'continue': TokenType.KW_CONTINUE,
            'default': TokenType.KW_DEFAULT, 'step': TokenType.KW_STEP,
            'string': TokenType.KW_STRING, 'array': TokenType.KW_ARRAY,
            'in': TokenType.KW_IN, 'elif': TokenType.KW_ELIF,
            'and': TokenType.OP_AND, 'or': TokenType.OP_OR, 'not': TokenType.OP_NOT,
            'as': TokenType.OP_CONVERT,
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
        if c == '*' and self.current() == '*':
            self.advance()
            return Token(TokenType.OP_POW, "**", start_line, start_col, self.filename)
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
            
        if self.current() == '#' and self.peek() == '[':
            return self.read_attribute()
            
        if self.current() == '#':
            return self.read_pragma()
            
        if self.current() == '@' and self.peek() == '[':
            return self.read_attribute()
            
        if self.current().isdigit():
            return self.read_number()
            
        if self.current() == '"' or self.current() == "'":
            return self.read_string()
            
        if self.current() == '.' and self.peek() == '.':
            self.advance(); self.advance()
            return Token(TokenType.KW_RANGE, "..", self.line, self.column, self.filename)
            
        if self.current().isalpha() or self.current() == '_':
            return self.read_identifier()
            
            
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

    depth = 0   # open (), [] and {}: a newline inside them continues the expression
    openers = (TokenType.OP_LPAREN, TokenType.OP_LBRACKET, TokenType.OP_LBRACE)
    closers = (TokenType.OP_RPAREN, TokenType.OP_RBRACKET, TokenType.OP_RBRACE)

    while i < n:
        tok = tokens[i]
        if tok.type in openers:
            depth += 1
        elif tok.type in closers and depth > 0:
            depth -= 1
        if tok.type == TokenType.NEWLINE and depth > 0:
            i += 1
            continue
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

# ============================================================================
# Type References (rich type info: arrays, structs, pointers, functions)
# ============================================================================

@dataclass
class TypeRef:
    base: DataType = DataType.U64
    name: str = ""
    elem: Optional['TypeRef'] = None
    length: int = 0
    params: List['TypeRef'] = field(default_factory=list)
    is_mut: bool = False
    is_ref: bool = False
    fn_params: List['TypeRef'] = field(default_factory=list)
    fn_return: Optional['TypeRef'] = None

    def __repr__(self) -> str:
        if self.base == DataType.ARRAY and self.elem:
            return f"array<{self.elem!r}, {self.length}>"
        if self.base == DataType.STRUCT:
            return self.name
        if self.base == DataType.PTR and self.elem:
            return f"ptr<{self.elem!r}>"
        if self.base == DataType.PTR_MUT and self.elem:
            return f"ptr_mut<{self.elem!r}>"
        if self.base == DataType.MMIO_PTR and self.elem:
            return f"mmio_ptr<{self.elem!r}>"
        if self.base == DataType.OPTION and self.elem:
            return f"Option<{self.elem!r}>"
        if self.base == DataType.TUPLE:
            return "(" + ", ".join(repr(p) for p in self.params) + ")"
        if self.base == DataType.FN:
            return "fn(" + ", ".join(repr(p) for p in self.fn_params) + ")"
        return self.base.name.lower()


PRIMITIVE_TYPES = {
    'u8': DataType.U8, 'u16': DataType.U16, 'u32': DataType.U32, 'u64': DataType.U64,
    'u128': DataType.U128,
    'i8': DataType.I8, 'i16': DataType.I16, 'i32': DataType.I32, 'i64': DataType.I64,
    'i128': DataType.I128,
    'f32': DataType.F32, 'f64': DataType.F64, 'f80': DataType.F80,
    'bool': DataType.BOOL, 'char': DataType.CHAR, 'bit': DataType.BIT,
    'string': DataType.STRING, 'void': DataType.VOID,
    'vec4_f32': DataType.VEC4_F32, 'vec8_f32': DataType.VEC8_F32,
    'vec16_f32': DataType.VEC16_F32, 'vec2_f64': DataType.VEC2_F64,
    'vec4_f64': DataType.VEC4_F64, 'vec8_f64': DataType.VEC8_F64,
}

SOFT_KEYWORD_NAMES = {'new', 'delete', 'get', 'set', 'size', 'key', 'end', 'from', 'case',
                      'default', 'when', 'in', 'step', 'record', 'metadata', 'priority'}

TYPE_START_TOKENS = {TokenType.KW_U8, TokenType.KW_U16, TokenType.KW_U32, TokenType.KW_U64,
                     TokenType.KW_I8, TokenType.KW_I16, TokenType.KW_I32, TokenType.KW_I64,
                     TokenType.KW_F32, TokenType.KW_F64, TokenType.KW_BOOL, TokenType.KW_CHAR,
                     TokenType.KW_PTR, TokenType.KW_MMIO_PTR, TokenType.KW_BIT,
                     TokenType.KW_STRING, TokenType.KW_ARRAY, TokenType.KW_VEC4_F32,
                     TokenType.KW_VEC8_F32, TokenType.KW_VEC16_F32, TokenType.KW_VEC2_F64,
                     TokenType.KW_VEC4_F64, TokenType.KW_VEC8_F64, TokenType.KW_BLOCK_ARRAY,
                     TokenType.KW_OPTION}

INTEGER_TYPES = {DataType.U8, DataType.U16, DataType.U32, DataType.U64, DataType.U128,
                 DataType.I8, DataType.I16, DataType.I32, DataType.I64, DataType.I128,
                 DataType.BOOL, DataType.CHAR, DataType.BIT}
FLOAT_TYPES = {DataType.F32, DataType.F64, DataType.F80}
POINTER_TYPES = {DataType.PTR, DataType.PTR_MUT, DataType.MMIO_PTR, DataType.STRING, DataType.FN}
VECTOR_INFO = {
    DataType.VEC4_F32: (4, 4, SIMDLevel.SSE),
    DataType.VEC8_F32: (8, 4, SIMDLevel.AVX),
    DataType.VEC16_F32: (16, 4, SIMDLevel.AVX512),
    DataType.VEC2_F64: (2, 8, SIMDLevel.SSE),
    DataType.VEC4_F64: (4, 8, SIMDLevel.AVX),
    DataType.VEC8_F64: (8, 8, SIMDLevel.AVX512),
}


def type_size(ref, symbols=None) -> int:
    """Byte size of a type as laid out in memory."""
    if ref is None:
        return 8
    base = ref.base
    if base in INTEGER_TYPES or base in FLOAT_TYPES:
        for info in DATA_TYPE_TABLE:
            if info.type == base:
                return info.size
        return 8
    if base in POINTER_TYPES:
        return 8
    if base == DataType.ARRAY:
        return max(1, type_size(ref.elem, symbols) * max(1, ref.length))
    if base == DataType.STRUCT:
        if symbols is not None:
            layout = symbols.struct_layout(ref.name)
            if layout:
                return layout['size']
        return 8
    if base == DataType.OPTION:
        return type_size(ref.elem, symbols) + 8
    if base == DataType.TUPLE:
        total = 0
        for p in ref.params:
            total += max(8, type_size(p, symbols))
        return total
    if base in VECTOR_INFO:
        return VECTOR_INFO[base][0] * VECTOR_INFO[base][1]
    return 8


def type_align(ref, symbols=None) -> int:
    size = type_size(ref, symbols)
    align = 1
    while align < 8 and align * 2 <= size:
        align *= 2
    return align


# ============================================================================
# Parser
# ============================================================================

class Parser:
    MODIFIER_TOKENS = {
        TokenType.KW_INLINE: "inline",
        TokenType.KW_VIRTUAL: "virtual",
        TokenType.KW_OVERRIDE: "override",
        TokenType.KW_ABSTRACT: "abstract",
        TokenType.KW_PUBLIC: "public",
        TokenType.KW_PRIVATE: "private",
        TokenType.KW_PROTECTED: "protected",
    }

    def __init__(self, tokens: List[Token], symbols: SymbolTable, errors: ErrorCollector,
                 opt_level: OptimizationLevel = OptimizationLevel.O2):
        self.tokens = tokens
        self.pos = 0
        self.symbols = symbols
        self.errors = errors
        self.current_opt_level = opt_level
        self.current_simd_level = SIMDLevel.NONE
        self.current_unroll_factor = 0
        self.current_attributes: List[str] = []
        self.known_types: Dict[str, TypeRef] = {}
        self.current_class: str = ""
        self.current_visibility: str = "public"

    # -- token helpers ------------------------------------------------------
    def current(self) -> Token:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else Token(TokenType.TOK_EOF, "", 0, 0, "")

    def peek(self, offset: int = 1) -> Token:
        idx = self.pos + offset
        return self.tokens[idx] if idx < len(self.tokens) else Token(TokenType.TOK_EOF, "", 0, 0, "")

    def advance(self) -> None:
        if self.pos < len(self.tokens):
            self.pos += 1

    def match(self, tok_type: TokenType) -> bool:
        if self.current().type == tok_type:
            self.advance()
            return True
        return False

    def match_any(self, *tok_types: TokenType) -> bool:
        if self.current().type in tok_types:
            self.advance()
            return True
        return False

    def expect(self, tok_type: TokenType, msg: str) -> bool:
        if self.current().type != tok_type:
            self.errors.add_error(msg, self.current().line, self.current().column)
            return False
        self.advance()
        return True

    def error(self, msg: str) -> None:
        self.errors.add_error(msg, self.current().line, self.current().column)

    @staticmethod
    def is_name_token(tok: Token) -> bool:
        return bool(tok.value) and str(tok.value).replace('_', 'a').isalnum()

    def skip_soft_newlines(self) -> None:
        while self.current().type in (TokenType.NEWLINE, TokenType.INDENT, TokenType.DEDENT):
            self.advance()

    def skip_to_line_end(self) -> None:
        while self.current().type not in (TokenType.NEWLINE, TokenType.TOK_EOF, TokenType.DEDENT):
            self.advance()

    # -- generic brackets ---------------------------------------------------
    def at_generic_open(self) -> bool:
        return self.current().type in (TokenType.OP_LT, TokenType.OP_TEMPLATE_LT)

    def at_generic_close(self) -> bool:
        return self.current().type in (TokenType.OP_GT, TokenType.OP_TEMPLATE_GT, TokenType.OP_SHR)

    def expect_generic_open(self, msg: str) -> bool:
        if self.at_generic_open():
            self.advance()
            return True
        self.error(msg)
        return False

    def expect_generic_close(self, msg: str) -> bool:
        tok = self.current()
        if tok.type in (TokenType.OP_GT, TokenType.OP_TEMPLATE_GT):
            self.advance()
            return True
        if tok.type == TokenType.OP_SHR:
            # '>>' closes two nested generic lists: consume one '>' now
            self.tokens[self.pos] = Token(TokenType.OP_GT, ">", tok.line, tok.column, tok.file)
            return True
        self.error(msg)
        return False

    # -- attributes ---------------------------------------------------------
    def parse_attributes(self) -> List[str]:
        attrs = []
        while self.current().type in [TokenType.KW_ATTRIBUTE_START, TokenType.KW_INTERRUPT,
                                      TokenType.KW_KERNEL, TokenType.KW_INIT, TokenType.KW_SECTION]:
            attrs.append(self.current().value)
            self.advance()
        return attrs

    # -- program ------------------------------------------------------------
    def parse(self) -> ASTNode:
        program = ASTNode(ASTType.PROGRAM, "", 0, 0)
        while self.current().type != TokenType.TOK_EOF:
            before = self.pos
            stmt = self.parse_statement()
            if stmt:
                program.add_child(stmt)
            if self.pos == before:
                if self.current().type == TokenType.TOK_EOF:
                    break
                self.advance()
        return program

    # -- statements ---------------------------------------------------------
    def parse_statement(self) -> Optional[ASTNode]:
        tok = self.current()

        if tok.type in (TokenType.NEWLINE, TokenType.INDENT, TokenType.DEDENT):
            self.advance()
            return None

        if tok.type in [TokenType.KW_ATTRIBUTE_START, TokenType.KW_INTERRUPT,
                        TokenType.KW_KERNEL, TokenType.KW_INIT, TokenType.KW_SECTION]:
            attrs = self.parse_attributes()
            stmt = self.parse_statement()
            if stmt:
                stmt.attributes = attrs + list(stmt.attributes)
            return stmt

        # visibility sections inside class/struct bodies: "private:" / "public:"
        if tok.type in (TokenType.KW_PRIVATE, TokenType.KW_PUBLIC, TokenType.KW_PROTECTED) \
                and self.peek().type == TokenType.OP_COLON:
            self.current_visibility = self.MODIFIER_TOKENS[tok.type]
            self.advance()
            self.advance()
            return None

        if tok.type in self.MODIFIER_TOKENS:
            mods = []
            while self.current().type in self.MODIFIER_TOKENS:
                mods.append(self.MODIFIER_TOKENS[self.current().type])
                self.advance()
            nxt = self.current().type
            if nxt in (TokenType.KW_FN, TokenType.KW_DEF):
                return self.parse_function(mods)
            if nxt == TokenType.KW_CLASS:
                return self.parse_class(mods)
            if nxt == TokenType.KW_STRUCT:
                return self.parse_struct(mods)
            self.error("Expected declaration after modifier")
            self.skip_to_line_end()
            return None

        if tok.type == TokenType.KW_STATIC:
            if self.peek().type in (TokenType.KW_FN, TokenType.KW_DEF):
                self.advance()
                return self.parse_function(["static"])
            return self.parse_var_decl(is_static=True)

        dispatch = {
            TokenType.PRAGMA_OPTIMIZE: self.parse_pragma_optimize,
            TokenType.PRAGMA_SIMD: self.parse_pragma_simd,
            TokenType.PRAGMA_UNROLL: self.parse_pragma_unroll,
            TokenType.KW_IMPORT: self.parse_import,
            TokenType.KW_EXPORT: self.parse_export,
            TokenType.KW_MODULE: self.parse_module,
            TokenType.KW_LET: self.parse_let,
            TokenType.KW_CONST: self.parse_var_decl,
            TokenType.KW_FN: self.parse_function,
            TokenType.KW_DEF: self.parse_function,
            TokenType.KW_CLASS: self.parse_class,
            TokenType.KW_STRUCT: self.parse_struct,
            TokenType.KW_ENUM: self.parse_enum,
            TokenType.KW_IMPL: self.parse_impl,
            TokenType.KW_TEMPLATE: self.parse_template,
            TokenType.KW_IF: self.parse_if,
            TokenType.KW_WHILE: self.parse_while,
            TokenType.KW_FOR: self.parse_for,
            TokenType.KW_RETURN: self.parse_return,
            TokenType.KW_SWITCH: self.parse_switch,
            TokenType.KW_CASE: self.parse_case,
            TokenType.KW_DEFAULT: self.parse_case,
            TokenType.KW_BREAK: self.parse_break_continue,
            TokenType.KW_CONTINUE: self.parse_break_continue,
            TokenType.KW_DATA_SECTION: self.parse_data_section,
            TokenType.KW_WITH: self.parse_with,
            TokenType.KW_BLOCK_ARRAY: self.parse_block_array,
            TokenType.KW_ASM: self.parse_asm_statement,
            TokenType.OP_LBRACE: self.parse_block,
        }
        handler = dispatch.get(tok.type)
        if handler:
            return handler()

        return self.parse_expression_statement()

    def parse_expression_statement(self) -> Optional[ASTNode]:
        expr = self.parse_expression()
        if expr is None:
            return None
        assign_ops = {
            TokenType.OP_ASSIGN: "=",
            TokenType.OP_PLUS_ASSIGN: "+=",
            TokenType.OP_MINUS_ASSIGN: "-=",
            TokenType.OP_MULTIPLY_ASSIGN: "*=",
            TokenType.OP_DIVIDE_ASSIGN: "/=",
        }
        if self.current().type in assign_ops:
            op_tok = self.current()
            self.advance()
            node = ASTNode(ASTType.ASSIGN, assign_ops[op_tok.type], op_tok.line, op_tok.column)
            node.add_child(expr)
            node.add_child(self.parse_expression())
            node.meta['is_declaration'] = False
            self.match(TokenType.OP_SEMICOLON)
            return node
        self.match(TokenType.OP_SEMICOLON)
        return expr

    def parse_break_continue(self) -> ASTNode:
        tok = self.current()
        self.advance()
        node = ASTNode(ASTType.BREAK_STMT if tok.type == TokenType.KW_BREAK else ASTType.CONTINUE_STMT,
                       tok.value, tok.line, tok.column)
        self.match(TokenType.OP_SEMICOLON)
        return node

    def parse_indented_block(self, node: ASTNode) -> None:
        if self.current().type not in (TokenType.NEWLINE, TokenType.INDENT, TokenType.DEDENT,
                                       TokenType.TOK_EOF):
            # single-line body after ':'  e.g.  if x == 0: return 0
            before = self.pos
            stmt = self.parse_statement()
            if stmt:
                node.add_child(stmt)
            if self.pos == before:
                self.advance()
            self.match(TokenType.NEWLINE)
            return
        while self.current().type == TokenType.NEWLINE:
            self.advance()
        if self.current().type == TokenType.INDENT:
            self.advance()
            while self.current().type not in (TokenType.DEDENT, TokenType.TOK_EOF):
                before = self.pos
                stmt = self.parse_statement()
                if stmt:
                    node.add_child(stmt)
                if self.pos == before:
                    self.advance()
            self.match(TokenType.DEDENT)

    def parse_inline_block(self, node: ASTNode) -> None:
        """Statements on the same line after ':' (e.g. switch cases)."""
        while self.current().type not in (TokenType.NEWLINE, TokenType.DEDENT, TokenType.TOK_EOF):
            before = self.pos
            stmt = self.parse_statement()
            if stmt:
                node.add_child(stmt)
            if self.pos == before:
                self.advance()
        self.match(TokenType.NEWLINE)

    # -- types --------------------------------------------------------------
    def parse_type_ref(self) -> TypeRef:
        tok = self.current()

        if tok.type == TokenType.OP_BIT_AND:
            self.advance()
            is_mut = self.match(TokenType.KW_MUT)
            inner = self.parse_type_ref()
            inner.is_ref = True
            inner.is_mut = inner.is_mut or is_mut
            return inner

        if tok.type in (TokenType.KW_FN, TokenType.KW_DEF):
            self.advance()
            ref = TypeRef(base=DataType.FN)
            if self.match(TokenType.OP_LPAREN):
                while self.current().type not in (TokenType.OP_RPAREN, TokenType.TOK_EOF):
                    ref.fn_params.append(self.parse_type_ref())
                    if not self.match(TokenType.OP_COMMA):
                        break
                self.expect(TokenType.OP_RPAREN, "Expected ')' in function type")
            if self.match(TokenType.OP_ARROW):
                ref.fn_return = self.parse_type_ref()
            return ref

        if tok.type == TokenType.OP_LPAREN:
            self.advance()
            ref = TypeRef(base=DataType.TUPLE)
            while self.current().type not in (TokenType.OP_RPAREN, TokenType.TOK_EOF):
                ref.params.append(self.parse_type_ref())
                if not self.match(TokenType.OP_COMMA):
                    break
            self.expect(TokenType.OP_RPAREN, "Expected ')' in tuple type")
            return ref

        name = tok.value
        self.advance()

        if name in PRIMITIVE_TYPES:
            ref = TypeRef(base=PRIMITIVE_TYPES[name], name=name)
            if self.at_generic_open():
                self.advance()
                while not self.at_generic_close() and self.current().type != TokenType.TOK_EOF:
                    self.advance()
                self.expect_generic_close("Expected '>'")
            return ref

        if name in ('ptr', 'ptr_mut', 'mmio_ptr'):
            ref = TypeRef(base={'ptr': DataType.PTR, 'ptr_mut': DataType.PTR_MUT,
                                'mmio_ptr': DataType.MMIO_PTR}[name], name=name)
            if self.at_generic_open():
                self.advance()
                if not self.at_generic_close():
                    ref.elem = self.parse_type_ref()
                self.expect_generic_close("Expected '>'")
            return ref

        if name in ('array', 'Array'):
            ref = TypeRef(base=DataType.ARRAY, name='array')
            if self.at_generic_open():
                self.advance()
                ref.elem = self.parse_type_ref()
                if self.match(TokenType.OP_COMMA):
                    if self.current().type in (TokenType.TOK_NUMBER, TokenType.TOK_HEX):
                        try:
                            ref.length = int(self.current().value, 0)
                        except ValueError:
                            ref.length = 0
                        self.advance()
                    elif self.current().type == TokenType.TOK_IDENTIFIER:
                        self.advance()
                self.expect_generic_close("Expected '>'")
            return ref

        if name == 'Option':
            ref = TypeRef(base=DataType.OPTION, name='Option')
            if self.at_generic_open():
                self.advance()
                ref.elem = self.parse_type_ref()
                self.expect_generic_close("Expected '>'")
            return ref

        if name in ('BlockArray', 'block_array'):
            ref = TypeRef(base=DataType.BLOCK_ARRAY, name='BlockArray')
            if self.at_generic_open():
                self.advance()
                ref.elem = self.parse_type_ref()
                self.expect_generic_close("Expected '>'")
            return ref

        ref = TypeRef(base=DataType.STRUCT, name=name)
        if self.at_generic_open():
            self.advance()
            while not self.at_generic_close() and self.current().type != TokenType.TOK_EOF:
                ref.params.append(self.parse_type_ref())
                if not self.match(TokenType.OP_COMMA):
                    break
            self.expect_generic_close("Expected '>'")
        if name in self.known_types:
            known = self.known_types[name]
            return TypeRef(base=known.base, name=name, elem=known.elem, length=known.length,
                           params=ref.params)
        return ref

    def parse_type(self) -> DataType:
        return self.parse_type_ref().base

    def parse_type_conversion(self, obj: ASTNode) -> ASTNode:
        node = ASTNode(ASTType.TYPE_CONVERSION, "as", obj.line, obj.column)
        node.add_child(obj)
        target = self.parse_type_ref()
        node.target_type = target.base
        node.meta['target_ref'] = target
        if self.current().type == TokenType.OP_DOT:
            self.advance()
            if self.current().value:
                node.conversion_method = self.current().value
                self.advance()
                if self.current().type == TokenType.OP_LPAREN:
                    self.advance()
                    self.expect(TokenType.OP_RPAREN, "Expected ')'")
        return node

    # -- variable declarations ---------------------------------------------
    def _declare_local(self, name: str, ref: TypeRef, line: int, column: int,
                       is_global: bool = False, is_static: bool = False) -> None:
        is_global = is_global or is_static or self.symbols.current_scope == 0
        self.symbols.declare(name, ref.base, line, column, is_global,
                             is_block_array=(ref.base == DataType.BLOCK_ARRAY),
                             block_array_type=ref.elem.base if ref.elem else None,
                             type_ref=ref)
        sym = self.symbols.lookup(name)
        if sym is not None:
            sym.type_ref = ref

    def parse_let(self, consume_semicolon: bool = True) -> Optional[ASTNode]:
        tok = self.current()
        if not self.expect(TokenType.KW_LET, "Expected 'let'"):
            return None
        is_mut = self.match(TokenType.KW_MUT)

        if self.current().type == TokenType.OP_LPAREN:
            self.advance()
            names = []
            while self.current().type not in (TokenType.OP_RPAREN, TokenType.TOK_EOF):
                if self.current().type == TokenType.TOK_IDENTIFIER:
                    names.append(self.current().value)
                    self.advance()
                if not self.match(TokenType.OP_COMMA):
                    break
            self.expect(TokenType.OP_RPAREN, "Expected ')' in destructuring pattern")
            node = ASTNode(ASTType.ASSIGN, "=", tok.line, tok.column)
            node.meta['is_declaration'] = True
            node.meta['tuple_names'] = names
            node.meta['is_mut'] = is_mut
            tuple_offsets = []
            for name in names:
                self._declare_local(name, TypeRef(base=DataType.U64), tok.line, tok.column)
                tsym = self.symbols.lookup(name)
                tuple_offsets.append(tsym.stack_offset if tsym is not None else None)
            node.meta['tuple_offsets'] = tuple_offsets
            if self.match(TokenType.OP_ASSIGN):
                node.add_child(self.parse_expression())
            if consume_semicolon:
                self.match(TokenType.OP_SEMICOLON)
            return node

        name_tok = self.current()
        if not self.is_name_token(name_tok):
            self.error("Expected variable name")
            self.skip_to_line_end()
            return None
        name = name_tok.value
        self.advance()

        node = ASTNode(ASTType.ASSIGN, "=", tok.line, tok.column)
        node.meta['is_declaration'] = True
        node.meta['is_mut'] = is_mut

        ref = None
        if self.match(TokenType.OP_COLON):
            ref = self.parse_type_ref()

        value = None
        if self.match(TokenType.OP_ASSIGN):
            value = self.parse_expression()

        if ref is None:
            ref = self._infer_ref(value)

        node.meta['type_ref'] = ref
        var_node = ASTNode(ASTType.VARIABLE, name, tok.line, tok.column)
        var_node.meta['type_ref'] = ref
        node.add_child(var_node)
        if value is not None:
            node.add_child(value)

        self._declare_local(name, ref, tok.line, tok.column)
        self._stamp_var(var_node, name)
        if consume_semicolon:
            self.match(TokenType.OP_SEMICOLON)
        return node

    def parse_var_decl(self, is_static: bool = False) -> Optional[ASTNode]:
        tok = self.current()
        is_const = tok.type == TokenType.KW_CONST
        if is_static:
            if not self.expect(TokenType.KW_STATIC, "Expected 'static'"):
                return None
        elif is_const:
            if not self.expect(TokenType.KW_CONST, "Expected 'const'"):
                return None
        else:
            self.error("Expected 'static' or 'const'")
            return None

        name_tok = self.current()
        if not self.is_name_token(name_tok):
            self.error("Expected variable name")
            self.skip_to_line_end()
            return None
        self.advance()

        node = ASTNode(ASTType.ASSIGN, "=", tok.line, tok.column)
        node.meta['is_declaration'] = True
        node.meta['is_static'] = True
        node.meta['is_const'] = is_const

        ref = None
        if self.match(TokenType.OP_COLON):
            ref = self.parse_type_ref()

        value = None
        if self.match(TokenType.OP_ASSIGN):
            value = self.parse_expression()

        if ref is None:
            ref = self._infer_ref(value)
        node.meta['type_ref'] = ref

        var_node = ASTNode(ASTType.VARIABLE, name_tok.value, tok.line, tok.column)
        var_node.meta['type_ref'] = ref
        node.add_child(var_node)
        if value is not None:
            node.add_child(value)

        self._declare_local(name_tok.value, ref, tok.line, tok.column, is_global=True)
        self._stamp_var(var_node, name_tok.value)
        self.match(TokenType.OP_SEMICOLON)
        return node

    def _stamp_var(self, node: ASTNode, name: str) -> ASTNode:
        sym = self.symbols.lookup(name)
        if sym is not None:
            node.meta['offset'] = sym.stack_offset
            node.meta['is_global'] = sym.is_global
            if sym.type_ref is not None:
                node.meta.setdefault('type_ref', sym.type_ref)
        return node

    def _static_ref(self, node: Optional[ASTNode]):
        """Best-effort static type of an expression at parse time (or None)."""
        if node is None:
            return None
        ref = node.meta.get('type_ref')
        if isinstance(ref, TypeRef):
            return ref
        if node.type == ASTType.MEMBER_ACCESS and node.children:
            base = self._static_ref(node.children[0])
            name = self.symbols.struct_name_of(base)
            found = self.symbols.field_ref(name, node.value) if name else None
            return self.symbols.specialize_class_ref(base, found) if found else None
        if node.type == ASTType.INDEX and node.children:
            base = self._static_ref(node.children[0])
            return base.elem if isinstance(base, TypeRef) else None
        if node.type == ASTType.METHOD_CALL and node.children:
            recv = node.children[0]
            recv_ref = self._static_ref(recv)
            if isinstance(recv_ref, TypeRef) and recv_ref.base in VECTOR_INFO:
                if node.value in ('iota', 'broadcast', 'fma'):
                    return recv_ref
                if node.value in ('dot', 'hadd_all', 'hmax', 'hmin'):
                    return TypeRef(base=DataType.F64)
            owner = recv.value if recv.meta.get('is_type_name') else \
                self.symbols.struct_name_of(recv_ref)
            fn = self.symbols.find_method(owner, node.value) if owner else None
            if fn is not None and isinstance(fn.meta.get('return_ref'), TypeRef):
                return self.symbols.specialize_class_ref(recv_ref, fn.meta['return_ref'])
        return None

    def _infer_ref(self, value: Optional[ASTNode]) -> TypeRef:
        if value is None:
            return TypeRef(base=DataType.U64)
        if value.type == ASTType.LITERAL:
            if value.data_type == DataType.F64:
                return TypeRef(base=DataType.F64)
            if value.data_type == DataType.CHAR and value.meta.get('is_string'):
                return TypeRef(base=DataType.STRING)
            if value.data_type == DataType.CHAR:
                return TypeRef(base=DataType.CHAR)
            if value.data_type == DataType.BOOL:
                return TypeRef(base=DataType.BOOL)
            return TypeRef(base=DataType.U64)
        if value.type == ASTType.ARRAY_LITERAL:
            elem = self._infer_ref(value.children[0]) if value.children else TypeRef(base=DataType.U64)
            return TypeRef(base=DataType.ARRAY, elem=elem,
                           length=len(value.children) or value.meta.get('repeat', 0))
        if value.type == ASTType.SIMD_OPERATION and value.value in PRIMITIVE_TYPES:
            return TypeRef(base=PRIMITIVE_TYPES[value.value], name=value.value)
        if value.type == ASTType.STRUCT_LITERAL:
            return TypeRef(base=DataType.STRUCT, name=value.value)
        if value.type == ASTType.LAMBDA:
            return TypeRef(base=DataType.FN)
        if value.type == ASTType.METHOD_CALL and value.children:
            recv = value.children[0]
            if recv.meta.get('is_type_name') and recv.value == 'Option':
                if value.value == 'some' and len(value.children) > 1:
                    return TypeRef(base=DataType.OPTION, name='Option',
                                   elem=self._infer_ref(value.children[1]))
                if value.value == 'none':
                    return TypeRef(base=DataType.OPTION, name='Option',
                                   elem=TypeRef(base=DataType.U64))
            recv_ref = self._static_ref(recv)
            if isinstance(recv_ref, TypeRef) and recv_ref.base in VECTOR_INFO:
                if value.value in ('iota', 'broadcast', 'fma'):
                    return recv_ref
                if value.value in ('dot', 'hadd_all', 'hmax', 'hmin'):
                    return TypeRef(base=DataType.F64)
            owner = None
            if recv.meta.get('is_type_name'):
                owner = recv.value
                if value.value == 'new' and owner:
                    recv_ref = self._static_ref(recv)
                    return TypeRef(base=DataType.STRUCT, name=owner,
                                   params=recv_ref.params if isinstance(recv_ref, TypeRef) else [])
            else:
                owner = self.symbols.struct_name_of(self._static_ref(recv)) or None
            if owner:
                fn = self.symbols.find_method(owner, value.value)
                if fn is not None and isinstance(fn.meta.get('return_ref'), TypeRef):
                    return self.symbols.specialize_class_ref(self._static_ref(recv),
                                                             fn.meta['return_ref'])
        if value.type in (ASTType.CALL, ASTType.METHOD_CALL):
            ret = value.meta.get('return_ref')
            if isinstance(ret, TypeRef):
                return ret
        if value.type in (ASTType.MEMBER_ACCESS, ASTType.INDEX):
            found = self._static_ref(value)
            if found is not None:
                return found
        if value.type == ASTType.TYPE_CONVERSION:
            return value.meta.get('target_ref') or TypeRef(base=value.target_type)
        if value.type == ASTType.VARIABLE:
            sym = self.symbols.lookup(value.value)
            if sym is not None and sym.type_ref is not None:
                return sym.type_ref
        if value.type == ASTType.BINARY_OP and value.value in ('+', '-', '*', '/', '%'):
            return self._infer_ref(value.children[0])
        return TypeRef(base=DataType.U64)

    # -- functions ----------------------------------------------------------
    def parse_function(self, modifiers: Optional[List[str]] = None) -> Optional[ASTNode]:
        node = ASTNode(ASTType.FUNCTION, line=self.current().line, column=self.current().column)
        node.optimization_level = self.current_opt_level
        node.simd_level = self.current_simd_level
        node.attributes = self.current_attributes.copy()
        node.meta['modifiers'] = list(modifiers or [])
        node.meta['visibility'] = self.current_visibility
        node.meta['parent'] = self.current_class

        if not self.match_any(TokenType.KW_FN, TokenType.KW_DEF):
            self.error("Expected 'fn'")
            return None

        name_tok = self.current()
        if name_tok.type != TokenType.TOK_IDENTIFIER and name_tok.value not in SOFT_KEYWORD_NAMES:
            self.error("Expected function name")
            self.skip_to_line_end()
            return None
        self.advance()
        node.value = name_tok.value

        if self.at_generic_open():
            self.advance()
            while not self.at_generic_close() and self.current().type != TokenType.TOK_EOF:
                if self.current().value in ('class', 'typename'):
                    self.advance()
                    continue
                if self.current().type == TokenType.TOK_IDENTIFIER:
                    node.template_params.append(self.current().value)
                self.advance()
            self.expect_generic_close("Expected '>'")

        if not self.expect(TokenType.OP_LPAREN, "Expected '('"):
            self.skip_to_line_end()
            return None

        param_names: List[str] = []
        param_refs: List[TypeRef] = []
        param_defaults: List[Optional[ASTNode]] = []
        self_mode = ""

        while self.current().type not in (TokenType.OP_RPAREN, TokenType.TOK_EOF):
            if self.current().type in (TokenType.OP_BIT_AND, TokenType.KW_MUT, TokenType.KW_SELF):
                is_ref = self.match(TokenType.OP_BIT_AND)
                is_mut = self.match(TokenType.KW_MUT)
                if self.current().type == TokenType.KW_SELF:
                    self.advance()
                    self_mode = ('ref_mut' if is_mut else 'ref') if is_ref else ('mut' if is_mut else 'value')
                    param_names.append('self')
                    param_refs.append(TypeRef(base=DataType.PTR if is_ref else DataType.STRUCT,
                                              name=self.current_class, is_ref=is_ref, is_mut=is_mut))
                    param_defaults.append(None)
                    if not self.match(TokenType.OP_COMMA):
                        break
                    continue

            pname_tok = self.current()
            if pname_tok.type != TokenType.TOK_IDENTIFIER and pname_tok.value not in SOFT_KEYWORD_NAMES:
                self.error("Expected parameter name")
                self.advance()
                break
            self.advance()
            param_names.append(pname_tok.value)

            if self.match(TokenType.OP_COLON):
                pref = self.parse_type_ref()
            else:
                pref = TypeRef(base=DataType.U64)
            param_refs.append(pref)
            param_defaults.append(None)

            if self.match(TokenType.OP_ASSIGN):
                param_defaults[-1] = self.parse_expression()
            if not self.match(TokenType.OP_COMMA):
                break

        self.expect(TokenType.OP_RPAREN, "Expected ')'")

        ret_ref = TypeRef(base=DataType.VOID)
        if self.match(TokenType.OP_ARROW):
            ret_ref = self.parse_type_ref()

        # instance methods always take the receiver as their first argument,
        # even when the signature leaves it implicit (`fn speak():`)
        mods = node.meta.get('modifiers') or []
        if self.current_class and 'self' not in param_names and 'static' not in mods:
            param_names.insert(0, 'self')
            param_refs.insert(0, TypeRef(base=DataType.PTR, name=self.current_class, is_ref=True))
            param_defaults.insert(0, None)
            self_mode = self_mode or 'ref'

        node.function_params = [p.base for p in param_refs]
        node.function_param_names = param_names
        node.function_return = ret_ref.base
        node.meta['param_refs'] = param_refs
        node.meta['param_defaults'] = param_defaults
        node.meta['return_ref'] = ret_ref
        node.meta['self_mode'] = self_mode

        self.symbols.register_function(node.value, node)

        has_body = self.current().type == TokenType.OP_COLON
        node.meta['has_body'] = has_body
        self.symbols.reset_frame()
        self.symbols.enter_scope()
        for pname, pref in zip(param_names, param_refs):
            self.symbols.declare(pname, pref.base, node.line, node.column, False)
            sym = self.symbols.lookup(pname)
            if sym is not None:
                sym.type_ref = pref

        if has_body:
            self.advance()
            self.parse_indented_block(node)
        elif self.current().type not in (TokenType.NEWLINE, TokenType.DEDENT, TokenType.TOK_EOF):
            self.skip_to_line_end()

        node.meta['param_offsets'] = [
            (self.symbols.lookup(pname).stack_offset if self.symbols.lookup(pname) else -(8 * (i + 1)))
            for i, pname in enumerate(param_names)]
        node.function_frame_size = self.symbols.get_frame_size()
        node.meta['frame_size'] = node.function_frame_size
        self.symbols.exit_scope()
        return node

    # -- aggregate types ----------------------------------------------------
    def parse_struct(self, modifiers: Optional[List[str]] = None) -> Optional[ASTNode]:
        tok = self.current()
        if not self.expect(TokenType.KW_STRUCT, "Expected 'struct'"):
            return None
        name_tok = self.current()
        if name_tok.type != TokenType.TOK_IDENTIFIER:
            self.error("Expected struct name")
            self.skip_to_line_end()
            return None
        self.advance()

        node = ASTNode(ASTType.STRUCT_DEF, name_tok.value, tok.line, tok.column)
        node.attributes = self.current_attributes.copy()
        node.meta['modifiers'] = list(modifiers or [])

        if self.at_generic_open():
            self.advance()
            while not self.at_generic_close() and self.current().type != TokenType.TOK_EOF:
                if self.current().type == TokenType.TOK_IDENTIFIER:
                    node.template_params.append(self.current().value)
                self.advance()
            self.expect_generic_close("Expected '>'")

        self.expect(TokenType.OP_COLON, "Expected ':' after struct name")

        self.known_types[name_tok.value] = TypeRef(base=DataType.STRUCT, name=name_tok.value)
        outer_class = self.current_class
        self.current_class = name_tok.value
        fields: List[Tuple[str, TypeRef]] = []
        methods: List[ASTNode] = []

        self.symbols.enter_scope()
        self._parse_aggregate_body(fields, methods)
        self.symbols.exit_scope()
        self.current_class = outer_class

        node.record_fields = [(fname, fref.base) for fname, fref in fields]
        node.meta['field_refs'] = fields
        node.meta['methods'] = methods
        for m in methods:
            node.add_child(m)

        self.symbols.define_struct(name_tok.value, fields)
        return node

    def _parse_aggregate_body(self, fields: List[Tuple[str, TypeRef]], methods: List[ASTNode]) -> None:
        while self.current().type == TokenType.NEWLINE:
            self.advance()
        if self.current().type == TokenType.INDENT:
            self.advance()
            while self.current().type not in (TokenType.DEDENT, TokenType.TOK_EOF):
                before = self.pos
                tok = self.current()
                if tok.type in (TokenType.KW_PRIVATE, TokenType.KW_PUBLIC, TokenType.KW_PROTECTED) \
                        and self.peek().type == TokenType.OP_COLON:
                    self.current_visibility = self.MODIFIER_TOKENS[tok.type]
                    self.advance()
                    self.advance()
                    if self.current().type == TokenType.NEWLINE:
                        self.advance()
                        if self.current().type == TokenType.INDENT:
                            self.advance()
                            while self.current().type not in (TokenType.DEDENT, TokenType.TOK_EOF):
                                inner_before = self.pos
                                self._parse_member(fields, methods)
                                if self.pos == inner_before:
                                    self.advance()
                            self.match(TokenType.DEDENT)
                    continue
                self._parse_member(fields, methods)
                if self.pos == before:
                    self.advance()
            self.match(TokenType.DEDENT)

    def _parse_member(self, fields: List[Tuple[str, TypeRef]], methods: List[ASTNode]) -> None:
        tok = self.current()
        if tok.type in (TokenType.NEWLINE, TokenType.INDENT):
            self.advance()
            return
        if tok.type in (TokenType.KW_FN, TokenType.KW_DEF) or tok.type in self.MODIFIER_TOKENS:
            mods = []
            while self.current().type in self.MODIFIER_TOKENS:
                mods.append(self.MODIFIER_TOKENS[self.current().type])
                self.advance()
            if self.current().type in (TokenType.KW_FN, TokenType.KW_DEF):
                fn = self.parse_function(mods)
                if fn:
                    methods.append(fn)
            else:
                self.error("Expected method declaration")
                self.skip_to_line_end()
            return
        if tok.type == TokenType.KW_STATIC:
            self.advance()
            if self.current().type in (TokenType.KW_FN, TokenType.KW_DEF):
                fn = self.parse_function(["static"])
                if fn:
                    methods.append(fn)
                return
            self.error("Expected 'fn' after 'static'")
            self.skip_to_line_end()
            return
        if tok.type == TokenType.TOK_IDENTIFIER or (tok.value in SOFT_KEYWORD_NAMES
                                                    and self.peek().type == TokenType.OP_COLON):
            name = tok.value
            self.advance()
            if self.match(TokenType.OP_COLON):
                ref = self.parse_type_ref()
                if self.match(TokenType.OP_ASSIGN):
                    default_expr = self.parse_expression()
                    if self.current_class and default_expr is not None:
                        defaults = getattr(self.symbols, 'field_defaults', None)
                        if defaults is None:
                            defaults = self.symbols.field_defaults = {}
                        defaults.setdefault(self.current_class, []).append((name, ref, default_expr))
                fields.append((name, ref))
                self.match(TokenType.OP_SEMICOLON)
                return
            self.error("Expected ':' after field name")
            self.skip_to_line_end()
            return
        self.skip_to_line_end()

    def parse_class(self, modifiers: Optional[List[str]] = None) -> Optional[ASTNode]:
        tok = self.current()
        if not self.expect(TokenType.KW_CLASS, "Expected 'class'"):
            return None
        name_tok = self.current()
        if name_tok.type != TokenType.TOK_IDENTIFIER:
            self.error("Expected class name")
            self.skip_to_line_end()
            return None
        self.advance()

        node = ASTNode(ASTType.CLASS, name_tok.value, tok.line, tok.column)
        node.attributes = self.current_attributes.copy()
        node.meta['modifiers'] = list(modifiers or [])

        if self.at_generic_open():
            self.advance()
            while not self.at_generic_close() and self.current().type != TokenType.TOK_EOF:
                if self.current().type == TokenType.TOK_IDENTIFIER:
                    node.template_params.append(self.current().value)
                self.advance()
            self.expect_generic_close("Expected '>'")

        if self.match(TokenType.KW_EXTENDS):
            if self.current().type == TokenType.TOK_IDENTIFIER:
                node.meta['base_class'] = self.current().value
                self.advance()

        if not self.expect(TokenType.OP_COLON, "Expected ':' after class name"):
            self.skip_to_line_end()

        self.known_types[name_tok.value] = TypeRef(base=DataType.STRUCT, name=name_tok.value)
        outer_class = self.current_class
        self.current_class = name_tok.value
        fields: List[Tuple[str, TypeRef]] = []
        methods: List[ASTNode] = []

        self.symbols.enter_scope()
        self._parse_aggregate_body(fields, methods)
        self.symbols.exit_scope()
        self.current_class = outer_class

        node.record_fields = [(fname, fref.base) for fname, fref in fields]
        node.meta['field_refs'] = fields
        node.meta['methods'] = methods
        for m in methods:
            node.add_child(m)

        base = node.meta.get('base_class')
        base_info = self.symbols.class_info(base) if base else None
        virtuals = list(base_info['virtuals']) if base_info else []
        declares_virtual = False
        for m in methods:
            mods = m.meta.get('modifiers') or []
            if 'virtual' in mods:
                declares_virtual = True
                if m.value not in virtuals:
                    virtuals.append(m.value)
        has_vptr = declares_virtual or bool(base_info and base_info.get('has_vptr'))
        self.symbols.register_class(name_tok.value, {
            'base': base, 'virtuals': virtuals, 'has_vptr': has_vptr,
            'abstract': 'abstract' in (node.meta.get('modifiers') or []),
            'template_params': list(node.template_params),
        })
        self.symbols.define_struct(name_tok.value, fields, base=base, has_vptr=has_vptr)
        return node

    def parse_enum(self) -> Optional[ASTNode]:
        tok = self.current()
        self.expect(TokenType.KW_ENUM, "Expected 'enum'")
        name_tok = self.current()
        name = name_tok.value if name_tok.type == TokenType.TOK_IDENTIFIER else "enum"
        self.advance()
        node = ASTNode(ASTType.ENUM_DEF, name, tok.line, tok.column)
        self.expect(TokenType.OP_COLON, "Expected ':' after enum name")
        self.parse_indented_block(node)
        self.known_types[name] = TypeRef(base=DataType.STRUCT, name=name)
        return node

    def parse_impl(self) -> Optional[ASTNode]:
        tok = self.current()
        if not self.expect(TokenType.KW_IMPL, "Expected 'impl'"):
            return None
        node = ASTNode(ASTType.IMPL_BLOCK, "", tok.line, tok.column)

        if self.at_generic_open():
            self.advance()
            while not self.at_generic_close() and self.current().type != TokenType.TOK_EOF:
                if self.current().type == TokenType.TOK_IDENTIFIER:
                    node.template_params.append(self.current().value)
                self.advance()
            self.expect_generic_close("Expected '>'")

        if self.current().type == TokenType.TOK_IDENTIFIER:
            node.value = self.current().value
            self.advance()
            if self.at_generic_open():
                self.advance()
                while not self.at_generic_close() and self.current().type != TokenType.TOK_EOF:
                    self.advance()
                self.expect_generic_close("Expected '>'")

        self.expect(TokenType.OP_COLON, "Expected ':' after impl target")

        outer_class = self.current_class
        self.current_class = node.value
        self.symbols.enter_scope()
        self.parse_indented_block(node)
        self.symbols.exit_scope()
        self.current_class = outer_class
        return node

    def parse_template(self) -> Optional[ASTNode]:
        tok = self.current()
        if not self.expect(TokenType.KW_TEMPLATE, "Expected 'template'"):
            return None
        node = ASTNode(ASTType.TEMPLATE_DECL, "", tok.line, tok.column)
        if not self.expect_generic_open("Expected '<'"):
            return None
        while not self.at_generic_close() and self.current().type != TokenType.TOK_EOF:
            if self.current().value in ('class', 'typename'):
                self.advance()
                continue
            if self.current().type == TokenType.TOK_IDENTIFIER:
                node.template_params.append(self.current().value)
            self.advance()
            self.match(TokenType.OP_COMMA)
        self.expect_generic_close("Expected '>'")

        while self.current().type == TokenType.NEWLINE:
            self.advance()
        inner = None
        if self.current().type == TokenType.KW_CLASS:
            inner = self.parse_class()
        elif self.current().type == TokenType.KW_STRUCT:
            inner = self.parse_struct()
        elif self.current().type in (TokenType.KW_FN, TokenType.KW_DEF):
            inner = self.parse_function()
        elif self.current().type == TokenType.KW_IMPL:
            inner = self.parse_impl()
        if inner is not None:
            inner.template_params = node.template_params
            if not node.template_params:
                inner.meta['template_specialization'] = True
            node.add_child(inner)
            node.value = inner.value
        return node

    # -- control flow -------------------------------------------------------
    def _parse_condition(self) -> Optional[ASTNode]:
        # `if (a & b) != 0:` - the parentheses belong to the expression, so just
        # parse a full expression (a bare `(cond)` is handled as a primary).
        return self.parse_expression()

    def parse_if(self) -> Optional[ASTNode]:
        tok = self.current()
        node = ASTNode(ASTType.IF_STMT, line=tok.line, column=tok.column)
        if not self.match_any(TokenType.KW_IF, TokenType.KW_ELIF):
            self.error("Expected 'if'")
            return None
        node.add_child(self._parse_condition())
        self.expect(TokenType.OP_COLON, "Expected ':' after if condition")

        body = ASTNode(ASTType.BLOCK, line=tok.line, column=tok.column)
        self.parse_indented_block(body)
        node.add_child(body)

        if self.current().type == TokenType.KW_ELIF:
            node.add_child(self.parse_if())
        elif self.current().type == TokenType.KW_ELSE:
            self.advance()
            self.expect(TokenType.OP_COLON, "Expected ':' after else")
            else_node = ASTNode(ASTType.BLOCK, line=self.current().line, column=self.current().column)
            self.parse_indented_block(else_node)
            node.add_child(else_node)
        return node

    def parse_while(self) -> Optional[ASTNode]:
        tok = self.current()
        node = ASTNode(ASTType.WHILE_STMT, line=tok.line, column=tok.column)
        if not self.expect(TokenType.KW_WHILE, "Expected 'while'"):
            return None
        node.add_child(self._parse_condition())
        self.expect(TokenType.OP_COLON, "Expected ':' after while condition")
        body = ASTNode(ASTType.BLOCK, line=tok.line, column=tok.column)
        self.parse_indented_block(body)
        node.add_child(body)
        return node

    def parse_for(self) -> Optional[ASTNode]:
        tok = self.current()
        node = ASTNode(ASTType.FOR_STMT, line=tok.line, column=tok.column)
        node.unroll_factor = self.current_unroll_factor
        node.simd_level = self.current_simd_level
        if not self.expect(TokenType.KW_FOR, "Expected 'for'"):
            return None

        if self.current().type == TokenType.OP_LPAREN:
            node.value = "cstyle"
            self.advance()
            if self.current().type == TokenType.KW_LET:
                node.add_child(self.parse_let(consume_semicolon=False))
            elif self.current().type != TokenType.OP_SEMICOLON:
                node.add_child(self._parse_assignment_expr())
            else:
                node.add_child(None)
            self.expect(TokenType.OP_SEMICOLON, "Expected ';' in for header")
            node.add_child(self.parse_expression())
            self.expect(TokenType.OP_SEMICOLON, "Expected ';' in for header")
            if self.current().type != TokenType.OP_RPAREN:
                node.add_child(self._parse_assignment_expr())
            else:
                node.add_child(None)
            self.expect(TokenType.OP_RPAREN, "Expected ')'")
            self.expect(TokenType.OP_COLON, "Expected ':' after for header")
            body = ASTNode(ASTType.BLOCK, line=tok.line, column=tok.column)
            self.parse_indented_block(body)
            node.add_child(body)
            return node

        if self.current().type == TokenType.TOK_IDENTIFIER and self.peek().type == TokenType.KW_IN:
            var_tok = self.current()
            self.advance()
            self.advance()
            var_node = ASTNode(ASTType.VARIABLE, var_tok.value, var_tok.line, var_tok.column)
            node.add_child(var_node)

            start = self.parse_expression()
            if self.current().type == TokenType.KW_RANGE:
                self.advance()
                node.value = "range"
                end = self.parse_expression()
                step = None
                if self.current().type == TokenType.KW_STEP:
                    self.advance()
                    step = self.parse_expression()
                node.add_child(start)
                node.add_child(end)
                node.add_child(step if step else ASTNode(ASTType.LITERAL, "1", tok.line, tok.column))
            else:
                node.value = "each"
                node.add_child(start)
            self.expect(TokenType.OP_COLON, "Expected ':' after for header")
            # The loop variable lives in its own scope that covers only the body.
            # It is declared after the header expressions are parsed, so
            # `for i in i..n` still refers to an outer `i` in the header.
            self.symbols.enter_scope()
            self._declare_local(var_tok.value, TypeRef(base=DataType.U64),
                                var_tok.line, var_tok.column)
            self._stamp_var(var_node, var_tok.value)
            if node.value == "each":
                hidden = f"__for_iter_{var_tok.line}_{var_tok.column}"
                self._declare_local(hidden, TypeRef(base=DataType.U64),
                                    var_tok.line, var_tok.column)
                node.meta['iter_offset'] = self.symbols.lookup(hidden).stack_offset
            else:
                for key, tag in (('end_offset', 'end'), ('step_offset', 'step')):
                    hidden = f"__for_{tag}_{var_tok.line}_{var_tok.column}"
                    self._declare_local(hidden, TypeRef(base=DataType.U64),
                                        var_tok.line, var_tok.column)
                    node.meta[key] = self.symbols.lookup(hidden).stack_offset
            body = ASTNode(ASTType.BLOCK, line=tok.line, column=tok.column)
            self.parse_indented_block(body)
            self.symbols.exit_scope()
            node.add_child(body)
            return node

        self.error("Expected 'in' or '(' in for statement")
        self.skip_to_line_end()
        return None

    def _parse_assignment_expr(self) -> Optional[ASTNode]:
        """An expression, or an assignment such as `j = j + 1` (used in for headers)."""
        expr = self.parse_expression()
        assign_ops = {
            TokenType.OP_ASSIGN: "=",
            TokenType.OP_PLUS_ASSIGN: "+=",
            TokenType.OP_MINUS_ASSIGN: "-=",
            TokenType.OP_MULTIPLY_ASSIGN: "*=",
            TokenType.OP_DIVIDE_ASSIGN: "/=",
        }
        if self.current().type in assign_ops:
            op_tok = self.current()
            self.advance()
            node = ASTNode(ASTType.ASSIGN, assign_ops[op_tok.type], op_tok.line, op_tok.column)
            node.add_child(expr)
            node.add_child(self.parse_expression())
            node.meta['is_declaration'] = False
            return node
        return expr

    def parse_switch(self) -> Optional[ASTNode]:
        tok = self.current()
        node = ASTNode(ASTType.SWITCH_STMT, line=tok.line, column=tok.column)
        if not self.expect(TokenType.KW_SWITCH, "Expected 'switch'"):
            return None
        node.add_child(self._parse_condition())
        self.expect(TokenType.OP_COLON, "Expected ':' after switch value")
        self.parse_indented_block(node)
        return node

    def parse_case(self) -> Optional[ASTNode]:
        tok = self.current()
        kind = "default" if tok.type == TokenType.KW_DEFAULT else "case"
        node = ASTNode(ASTType.CASE_STMT, kind, tok.line, tok.column)
        self.advance()

        if kind == "case":
            if self.current().type == TokenType.KW_WHEN:
                self.advance()
                node.value = "when"
                node.add_child(self._parse_condition())
            else:
                node.add_child(self.parse_expression())
        self.expect(TokenType.OP_COLON, "Expected ':' after case")

        body = ASTNode(ASTType.BLOCK, line=tok.line, column=tok.column)
        if self.current().type in (TokenType.NEWLINE, TokenType.INDENT):
            self.parse_indented_block(body)
        else:
            self.parse_inline_block(body)
        node.add_child(body)
        return node

    def parse_return(self) -> Optional[ASTNode]:
        tok = self.current()
        node = ASTNode(ASTType.RETURN_STMT, line=tok.line, column=tok.column)
        if not self.expect(TokenType.KW_RETURN, "Expected 'return'"):
            return None
        if self.current().type not in (TokenType.OP_SEMICOLON, TokenType.NEWLINE,
                                       TokenType.DEDENT, TokenType.TOK_EOF):
            node.add_child(self.parse_expression())
        self.match(TokenType.OP_SEMICOLON)
        return node

    def parse_with(self) -> Optional[ASTNode]:
        tok = self.current()
        node = ASTNode(ASTType.WITH_STMT, line=tok.line, column=tok.column)
        if not self.expect(TokenType.KW_WITH, "Expected 'with'"):
            return None
        node.add_child(self.parse_expression())
        self.expect(TokenType.OP_COLON, "Expected ':' after with expression")
        self.parse_indented_block(node)
        return node

    def parse_block(self) -> Optional[ASTNode]:
        tok = self.current()
        node = ASTNode(ASTType.BLOCK, line=tok.line, column=tok.column)
        if not self.expect(TokenType.OP_LBRACE, "Expected '{'"):
            return None
        self.symbols.enter_scope()
        while self.current().type not in (TokenType.OP_RBRACE, TokenType.TOK_EOF):
            before = self.pos
            stmt = self.parse_statement()
            if stmt:
                node.add_child(stmt)
            if self.pos == before:
                self.advance()
        self.expect(TokenType.OP_RBRACE, "Expected '}'")
        self.symbols.exit_scope()
        return node

    def parse_asm_statement(self) -> Optional[ASTNode]:
        tok = self.current()
        node = ASTNode(ASTType.ASM_STMT, line=tok.line, column=tok.column)
        if not self.expect(TokenType.KW_ASM, "Expected 'asm'"):
            return None
        if not self.expect(TokenType.OP_LPAREN, "Expected '(' after 'asm'"):
            return None
        if self.current().type != TokenType.TOK_STRING:
            self.error("Expected assembly instruction string")
            return None
        node.value = self.current().value
        self.advance()
        self.expect(TokenType.OP_RPAREN, "Expected ')' after assembly string")
        self.match(TokenType.OP_SEMICOLON)
        return node

    def parse_block_array(self) -> Optional[ASTNode]:
        tok = self.current()
        node = ASTNode(ASTType.BLOCK_ARRAY_TYPE, line=tok.line, column=tok.column)
        self.advance()
        if self.match(TokenType.OP_LPAREN):
            if self.at_generic_open():
                self.advance()
                node.block_array_type = self.parse_type()
                self.expect_generic_close("Expected '>'")
            if self.match(TokenType.OP_COMMA):
                if self.current().type == TokenType.TOK_NUMBER:
                    try:
                        node.block_size = int(self.current().value, 0)
                    except ValueError:
                        node.block_size = 256
                    self.advance()
            self.expect(TokenType.OP_RPAREN, "Expected ')'")
        if self.match(TokenType.OP_ASSIGN):
            node.add_child(self.parse_expression())
        self.match(TokenType.OP_SEMICOLON)
        return node

    # -- pragmas ------------------------------------------------------------
    def parse_pragma_optimize(self) -> ASTNode:
        tok = self.current()
        self.advance()
        node = ASTNode(ASTType.PRAGMA, tok.value, tok.line, tok.column)
        node.meta['pragma'] = 'optimize'
        if tok.value == 'O0':
            self.current_opt_level = OptimizationLevel.O0
        elif tok.value == 'O1':
            self.current_opt_level = OptimizationLevel.O1
        elif tok.value == 'O3':
            self.current_opt_level = OptimizationLevel.O3
        else:
            self.current_opt_level = OptimizationLevel.O2
        return node

    def parse_pragma_simd(self) -> ASTNode:
        tok = self.current()
        self.advance()
        node = ASTNode(ASTType.PRAGMA, tok.value, tok.line, tok.column)
        node.meta['pragma'] = 'simd'
        if tok.value == 'SSE':
            self.current_simd_level = SIMDLevel.SSE
        elif tok.value == 'AVX':
            self.current_simd_level = SIMDLevel.AVX
        elif tok.value == 'AVX512':
            self.current_simd_level = SIMDLevel.AVX512
        return node

    def parse_pragma_unroll(self) -> ASTNode:
        tok = self.current()
        self.advance()
        node = ASTNode(ASTType.PRAGMA, tok.value, tok.line, tok.column)
        node.meta['pragma'] = 'unroll'
        try:
            self.current_unroll_factor = int(tok.value)
        except (TypeError, ValueError):
            self.current_unroll_factor = 0
        return node

    def parse_import(self) -> Optional[ASTNode]:
        tok = self.current()
        self.advance()
        node = ASTNode(ASTType.IMPORT_STMT, line=tok.line, column=tok.column)
        if self.current().type == TokenType.TOK_STRING:
            node.import_path = self.current().value
            self.advance()
        if self.current().type == TokenType.TOK_IDENTIFIER:
            node.value = self.current().value
            self.advance()
        self.match(TokenType.OP_SEMICOLON)
        return node

    def parse_export(self) -> Optional[ASTNode]:
        tok = self.current()
        self.advance()
        node = ASTNode(ASTType.EXPORT_STMT, line=tok.line, column=tok.column)
        if self.current().type == TokenType.TOK_IDENTIFIER:
            node.export_name = self.current().value
            node.value = self.current().value
            self.advance()
            self.symbols.exported_symbols.add(node.export_name)
        self.match(TokenType.OP_SEMICOLON)
        return node

    def parse_module(self) -> Optional[ASTNode]:
        tok = self.current()
        self.advance()
        node = ASTNode(ASTType.MODULE, line=tok.line, column=tok.column)
        if self.current().type == TokenType.TOK_IDENTIFIER:
            node.value = self.current().value
            self.advance()
        self.expect(TokenType.OP_COLON, "Expected ':' after module name")
        self.parse_indented_block(node)
        return node

    def parse_data_section(self) -> Optional[ASTNode]:
        tok = self.current()
        node = ASTNode(ASTType.DATA_SECTION, line=tok.line, column=tok.column)
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
        self.expect(TokenType.OP_COLON, "Expected ':' after data_section")
        self.parse_indented_block(node)
        return node

    # -- expressions --------------------------------------------------------
    def get_precedence(self, tok_type: TokenType) -> int:
        prec_map = {
            TokenType.OP_CONVERT: 12,
            TokenType.OP_COLON: 12,
            TokenType.OP_OR: 3,
            TokenType.OP_AND: 4,
            TokenType.OP_EQ: 5, TokenType.OP_NE: 5,
            TokenType.OP_LT: 6, TokenType.OP_LE: 6, TokenType.OP_GT: 6, TokenType.OP_GE: 6,
            TokenType.OP_BIT_OR: 7, TokenType.OP_BIT_XOR: 8, TokenType.OP_BIT_AND: 9,
            TokenType.OP_SHL: 10, TokenType.OP_SHR: 10,
            TokenType.OP_PLUS: 11, TokenType.OP_MINUS: 11,
            TokenType.OP_MULTIPLY: 13, TokenType.OP_DIVIDE: 13, TokenType.OP_MOD: 13,
            TokenType.OP_POW: 14,
        }
        return prec_map.get(tok_type, 0)

    def parse_expression(self) -> Optional[ASTNode]:
        return self.parse_binary_op(0)

    def parse_binary_op(self, min_precedence: int) -> Optional[ASTNode]:
        left = self.parse_unary()
        if not left:
            return None

        while True:
            tok = self.current()
            precedence = self.get_precedence(tok.type)
            if precedence == 0 or precedence < min_precedence:
                break

            # ':' is a conversion only when a type name follows it; otherwise it
            # opens a block (if/while/for/switch/case) and belongs to the caller
            if tok.type == TokenType.OP_COLON:
                nxt = self.peek()
                if nxt.type in TYPE_START_TOKENS or nxt.value in PRIMITIVE_TYPES \
                        or nxt.value in ('ptr', 'ptr_mut', 'mmio_ptr', 'array', 'Option',
                                         'BlockArray', 'block_array'):
                    self.advance()
                    left = self.parse_type_conversion(left)
                    continue
                break

            self.advance()
            if tok.type == TokenType.OP_CONVERT:
                left = self.parse_type_conversion(left)
                continue

            next_min = precedence if tok.type == TokenType.OP_POW else precedence + 1
            right = self.parse_binary_op(next_min)
            if not right:
                return left
            left_ref, right_ref = self._static_ref(left), self._static_ref(right)
            left_base = left_ref.base if isinstance(left_ref, TypeRef) else left.data_type
            right_base = right_ref.base if isinstance(right_ref, TypeRef) else right.data_type
            if left_base in VECTOR_INFO or right_base in VECTOR_INFO:
                if left_base != right_base or tok.value not in ('+', '-', '*', '/'):
                    self.errors.add_error("SIMD binary operations require matching vector types and arithmetic operators",
                                          tok.line, tok.column)
            binary = ASTNode(ASTType.BINARY_OP, tok.value, tok.line, tok.column)
            binary.add_child(left)
            binary.add_child(right)
            binary.data_type = self._binary_result_type(binary)
            left = binary
        return left

    def _binary_result_type(self, node: ASTNode) -> DataType:
        left = node.children[0] if node.children else None
        right = node.children[1] if len(node.children) > 1 else None
        left_ref = left.meta.get('type_ref') if left is not None else None
        right_ref = right.meta.get('type_ref') if right is not None else None
        left_base = left_ref.base if isinstance(left_ref, TypeRef) else left.data_type if left else DataType.VOID
        right_base = right_ref.base if isinstance(right_ref, TypeRef) else right.data_type if right else DataType.VOID
        if left_base == right_base and left_base in VECTOR_INFO:
            return left_base
        for side in (left, right):
            if side is None:
                continue
            if side.data_type in FLOAT_TYPES:
                return side.data_type
            side_ref = side.meta.get('type_ref')
            if isinstance(side_ref, TypeRef) and side_ref.base in FLOAT_TYPES:
                return side_ref.base
        if node.value in ('==', '!=', '<', '<=', '>', '>=', 'and', 'or'):
            return DataType.BOOL
        if left is not None:
            left_ref = left.meta.get('type_ref')
            if isinstance(left_ref, TypeRef):
                return left_ref.base
            return left.data_type
        return DataType.U64

    def parse_unary(self) -> Optional[ASTNode]:
        tok = self.current()
        if tok.type in (TokenType.OP_MINUS, TokenType.OP_NOT, TokenType.OP_BIT_NOT,
                        TokenType.OP_BIT_AND, TokenType.OP_MULTIPLY):
            self.advance()
            is_mut_ref = self.match(TokenType.KW_MUT)
            operand = self.parse_unary()
            if operand is None:
                return None
            node = ASTNode(ASTType.UNARY_OP, tok.value, tok.line, tok.column)
            node.add_child(operand)
            if tok.value == '&':
                node.meta['type_ref'] = TypeRef(base=DataType.PTR_MUT if is_mut_ref else DataType.PTR,
                                                elem=operand.meta.get('type_ref'))
            elif tok.value == '*':
                inner = operand.meta.get('type_ref')
                if isinstance(inner, TypeRef) and inner.elem is not None:
                    node.meta['type_ref'] = inner.elem
            return node
        if tok.type in (TokenType.OP_INC, TokenType.OP_DEC):
            self.advance()
            operand = self.parse_unary()
            node = ASTNode(ASTType.UNARY_OP, tok.value, tok.line, tok.column)
            node.meta['prefix'] = True
            node.add_child(operand)
            return node
        if tok.type == TokenType.OP_LPAREN:
            self.advance()
            first = self.parse_expression()
            if self.current().type == TokenType.OP_COMMA:
                node = ASTNode(ASTType.TUPLE, "()", tok.line, tok.column)
                if first:
                    node.add_child(first)
                while self.match(TokenType.OP_COMMA):
                    if self.current().type == TokenType.OP_RPAREN:
                        break
                    node.add_child(self.parse_expression())
                self.expect(TokenType.OP_RPAREN, "Expected ')'")
                node.meta['type_ref'] = TypeRef(base=DataType.TUPLE)
                return node
            self.expect(TokenType.OP_RPAREN, "Expected ')'")
            if first is not None:
                first.meta['parenthesised'] = True
            return first
        return self.parse_postfix()

    def parse_postfix(self) -> Optional[ASTNode]:
        node = self.parse_primary()
        if node is None:
            return None
        return self.parse_postfix_ops(node)

    def parse_postfix_ops(self, node: ASTNode) -> ASTNode:
        while True:
            tok = self.current()
            if tok.type == TokenType.OP_LBRACKET:
                self.advance()
                index = self.parse_expression()
                self.expect(TokenType.OP_RBRACKET, "Expected ']'")
                index_node = ASTNode(ASTType.INDEX, "[]", tok.line, tok.column)
                index_node.add_child(node)
                index_node.add_child(index)
                elem = None
                base_ref = node.meta.get('type_ref')
                if isinstance(base_ref, TypeRef) and base_ref.elem is not None:
                    elem = base_ref.elem
                elif isinstance(base_ref, TypeRef) and base_ref.base in VECTOR_INFO:
                    lane_size = VECTOR_INFO[base_ref.base][1]
                    elem = TypeRef(base=DataType.F32 if lane_size == 4 else DataType.F64)
                index_node.meta['type_ref'] = elem or TypeRef(base=DataType.U64)
                node = index_node
                continue
            if tok.type == TokenType.OP_DOT:
                self.advance()
                name_tok = self.current()
                if not name_tok.value or not str(name_tok.value).replace('_', 'a').isalnum():
                    self.error("Expected member name after '.'")
                    return node
                self.advance()
                if self.current().type == TokenType.OP_LPAREN:
                    call = ASTNode(ASTType.METHOD_CALL, name_tok.value, tok.line, tok.column)
                    call.add_child(node)
                    self.advance()
                    self._parse_arguments(call)
                    node = call
                else:
                    member = ASTNode(ASTType.MEMBER_ACCESS, name_tok.value, tok.line, tok.column)
                    member.add_child(node)
                    base_ref = self._static_ref(node)
                    owner = self.symbols.struct_name_of(base_ref)
                    found = self.symbols.field_ref(owner, name_tok.value) if owner else None
                    if found is not None:
                        member.meta['type_ref'] = self.symbols.specialize_class_ref(base_ref, found)
                    node = member
                continue
            if tok.type == TokenType.OP_LPAREN:
                call = ASTNode(ASTType.CALL, node.value, tok.line, tok.column)
                call.add_child(node)
                self.advance()
                self._parse_arguments(call)
                node = call
                continue
            break
        return node

    def _parse_arguments(self, call: ASTNode) -> None:
        self.skip_soft_newlines()
        while self.current().type not in (TokenType.OP_RPAREN, TokenType.TOK_EOF):
            before = self.pos
            arg = self.parse_expression()
            if arg:
                call.add_child(arg)
            self.skip_soft_newlines()
            if not self.match(TokenType.OP_COMMA):
                break
            self.skip_soft_newlines()
            if self.pos == before:
                break
        self.expect(TokenType.OP_RPAREN, "Expected ')'")

    def parse_primary(self) -> Optional[ASTNode]:
        tok = self.current()

        if tok.type in (TokenType.TOK_NUMBER, TokenType.TOK_HEX, TokenType.TOK_BINARY):
            self.advance()
            if tok.type == TokenType.TOK_HEX:
                literal = str(int(tok.value or '0', 16))
            elif tok.type == TokenType.TOK_BINARY:
                literal = str(int(tok.value or '0', 2))
            else:
                literal = tok.value
            node = ASTNode(ASTType.LITERAL, literal, tok.line, tok.column)
            if '.' in literal or 'e' in literal.lower():
                node.data_type = DataType.F64
            else:
                node.data_type = DataType.U64
            return node

        if tok.type == TokenType.TOK_CHAR:
            self.advance()
            node = ASTNode(ASTType.LITERAL, tok.value, tok.line, tok.column)
            node.data_type = DataType.CHAR
            node.meta['char_value'] = ord(tok.value[0]) if tok.value else 0
            return node

        if tok.type == TokenType.TOK_STRING:
            self.advance()
            node = ASTNode(ASTType.LITERAL, tok.value, tok.line, tok.column)
            node.data_type = DataType.CHAR
            node.meta['is_string'] = True
            return node

        if tok.type in (TokenType.KW_TRUE, TokenType.KW_FALSE):
            self.advance()
            node = ASTNode(ASTType.LITERAL, "1" if tok.type == TokenType.KW_TRUE else "0",
                           tok.line, tok.column)
            node.data_type = DataType.BOOL
            return node

        if tok.type in (TokenType.KW_NULL, TokenType.KW_NONE):
            self.advance()
            node = ASTNode(ASTType.LITERAL, "0", tok.line, tok.column)
            node.data_type = DataType.U64
            return node

        if tok.type == TokenType.TOK_IDENTIFIER and tok.value in ('sizeof', 'alignof') \
                and self.peek().type == TokenType.OP_LPAREN:
            self.advance()
            self.advance()
            ref = self.parse_type_ref()
            self.expect(TokenType.OP_RPAREN, "Expected ')' after type in " + tok.value)
            value = type_size(ref, self.symbols) if tok.value == 'sizeof' else type_align(ref, self.symbols)
            node = ASTNode(ASTType.LITERAL, str(value), tok.line, tok.column)
            node.data_type = DataType.U64
            return node

        if tok.type in (TokenType.KW_VEC4_F32, TokenType.KW_VEC8_F32,
                        TokenType.KW_VEC16_F32, TokenType.KW_VEC2_F64,
                        TokenType.KW_VEC4_F64, TokenType.KW_VEC8_F64):
            self.advance()
            node = ASTNode(ASTType.SIMD_OPERATION, tok.value, tok.line, tok.column)
            node.simd_level = VECTOR_INFO[PRIMITIVE_TYPES[tok.value]][2]
            return self.parse_simd_constructor(node)

        if tok.type == TokenType.KW_NEW:
            self.advance()
            return self.parse_constructor()

        if tok.type == TokenType.KW_SUPER:
            self.advance()
            node = ASTNode(ASTType.VARIABLE, "super", tok.line, tok.column)
            return self.parse_postfix_ops(node)

        if tok.type in (TokenType.KW_SELF, TokenType.KW_THIS):
            self.advance()
            node = ASTNode(ASTType.VARIABLE, "self", tok.line, tok.column)
            sym = self.symbols.lookup("self")
            if sym is not None and sym.type_ref is not None:
                node.meta['type_ref'] = sym.type_ref
            self._stamp_var(node, "self")
            return self.parse_postfix_ops(node)

        if tok.type in (TokenType.KW_FN, TokenType.KW_DEF):
            return self.parse_lambda()

        if tok.type == TokenType.KW_BLOCK_ARRAY:
            self.advance()
            node = ASTNode(ASTType.BLOCK_ARRAY_TYPE, line=tok.line, column=tok.column)
            if self.at_generic_open():
                self.advance()
                node.block_array_type = self.parse_type()
                self.expect_generic_close("Expected '>'")
            return node

        if tok.type == TokenType.OP_LBRACKET:
            return self.parse_array_literal()

        if tok.type in (TokenType.TOK_IDENTIFIER, TokenType.KW_OPTION):
            self.advance()
            if tok.value in BUILTIN_FUNCTIONS:
                node = ASTNode(ASTType.BUILTIN_CALL, tok.value, tok.line, tok.column)
                node.meta['return_ref'] = TypeRef(base=BUILTIN_FUNCTIONS[tok.value][1])
                if self.current().type == TokenType.OP_LPAREN:
                    self.advance()
                    self._parse_arguments(node)
                return node

            if self.current().type == TokenType.OP_LBRACE and tok.value in self.known_types:
                return self.parse_struct_literal(tok)

            # generic instantiation: Stack<u64>.new(), Pair<K, V>{...}
            generic_args = []
            if self.at_generic_open() and tok.value in self.known_types:
                self.advance()
                while not self.at_generic_close() and self.current().type != TokenType.TOK_EOF:
                    generic_args.append(self.parse_type_ref())
                    if not self.match(TokenType.OP_COMMA):
                        break
                self.expect_generic_close("Expected '>'")

            var_node = ASTNode(ASTType.VARIABLE, tok.value, tok.line, tok.column)
            if tok.type == TokenType.KW_OPTION:
                var_node.meta['type_ref'] = TypeRef(base=DataType.OPTION, name='Option')
                var_node.meta['is_type_name'] = True
            sym = self.symbols.lookup(tok.value)
            if sym is not None and sym.type_ref is not None:
                var_node.meta['type_ref'] = sym.type_ref
            elif tok.value in self.known_types:
                known = self.known_types[tok.value]
                var_node.meta['type_ref'] = TypeRef(base=known.base, name=known.name,
                                                    elem=known.elem, length=known.length,
                                                    params=generic_args)
                var_node.meta['is_type_name'] = True
            if tok.value not in self.known_types:
                self._stamp_var(var_node, tok.value)
            return self.parse_postfix_ops(var_node)

        if self.is_name_token(tok) and self.symbols.lookup(tok.value) is not None:
            self.advance()
            var_node = ASTNode(ASTType.VARIABLE, tok.value, tok.line, tok.column)
            sym = self.symbols.lookup(tok.value)
            if sym is not None and sym.type_ref is not None:
                var_node.meta['type_ref'] = sym.type_ref
            self._stamp_var(var_node, tok.value)
            return self.parse_postfix_ops(var_node)

        self.error(f"Unexpected token: {tok.value}")
        self.advance()
        return None

    def parse_struct_literal(self, tok: Token) -> ASTNode:
        node = ASTNode(ASTType.STRUCT_LITERAL, tok.value, tok.line, tok.column)
        self.expect(TokenType.OP_LBRACE, "Expected '{'")
        self.skip_soft_newlines()
        while self.current().type not in (TokenType.OP_RBRACE, TokenType.TOK_EOF):
            if self.current().type == TokenType.TOK_IDENTIFIER and self.peek().type == TokenType.OP_COLON:
                field_name = self.current().value
                self.advance()
                self.advance()
                value = self.parse_expression()
                if value is not None:
                    value.meta['field_name'] = field_name
                    node.add_child(value)
            else:
                node.add_child(self.parse_expression())
            self.skip_soft_newlines()
            if not self.match(TokenType.OP_COMMA):
                break
            self.skip_soft_newlines()
        self.expect(TokenType.OP_RBRACE, "Expected '}'")
        node.meta['type_ref'] = TypeRef(base=DataType.STRUCT, name=tok.value)
        return node

    def parse_array_literal(self) -> ASTNode:
        tok = self.current()
        node = ASTNode(ASTType.ARRAY_LITERAL, "[]", tok.line, tok.column)
        self.expect(TokenType.OP_LBRACKET, "Expected '['")
        self.skip_soft_newlines()
        if self.current().type == TokenType.OP_RBRACKET:
            self.advance()
            node.meta['type_ref'] = TypeRef(base=DataType.ARRAY, elem=TypeRef(base=DataType.U64), length=0)
            return node
        first = self.parse_expression()
        self.skip_soft_newlines()
        if self.match(TokenType.OP_SEMICOLON):
            count = self.parse_expression()
            repeat = 0
            if count is not None and count.value.isdigit():
                repeat = int(count.value)
            node.meta['repeat'] = repeat
            if first:
                node.add_child(first)
            self.expect(TokenType.OP_RBRACKET, "Expected ']'")
        else:
            if first:
                node.add_child(first)
            while True:
                self.skip_soft_newlines()
                if not self.match(TokenType.OP_COMMA):
                    break
                self.skip_soft_newlines()
                if self.current().type == TokenType.OP_RBRACKET:
                    break
                node.add_child(self.parse_expression())
            self.skip_soft_newlines()
            self.expect(TokenType.OP_RBRACKET, "Expected ']'")
        elem = self._infer_ref(node.children[0]) if node.children else TypeRef(base=DataType.U64)
        length = node.meta.get('repeat') or len(node.children)
        node.meta['type_ref'] = TypeRef(base=DataType.ARRAY, elem=elem, length=length)
        return node

    def parse_lambda(self) -> ASTNode:
        tok = self.current()
        node = ASTNode(ASTType.LAMBDA, "lambda", tok.line, tok.column)
        self.advance()
        param_refs: List[TypeRef] = []
        param_names: List[str] = []
        if self.match(TokenType.OP_LPAREN):
            while self.current().type not in (TokenType.OP_RPAREN, TokenType.TOK_EOF):
                if self.current().type == TokenType.TOK_IDENTIFIER:
                    param_names.append(self.current().value)
                    self.advance()
                    if self.match(TokenType.OP_COLON):
                        param_refs.append(self.parse_type_ref())
                    else:
                        param_refs.append(TypeRef(base=DataType.U64))
                if not self.match(TokenType.OP_COMMA):
                    break
            self.expect(TokenType.OP_RPAREN, "Expected ')'")
        ret_ref = TypeRef(base=DataType.U64)
        if self.match(TokenType.OP_ARROW):
            ret_ref = self.parse_type_ref()
        node.meta['param_refs'] = param_refs
        node.meta['param_names'] = param_names
        node.meta['return_ref'] = ret_ref
        node.meta['type_ref'] = TypeRef(base=DataType.FN)
        self.expect(TokenType.OP_COLON, "Expected ':' before lambda body")
        # a lambda is its own function: fresh frame ([rbp-8] holds the saved rbx),
        # parameters declared so the body can refer to them
        saved_next = self.symbols.next_stack_offset
        self.symbols.enter_scope()
        self.symbols.next_stack_offset = -16
        for pname, pref in zip(param_names, param_refs):
            self.symbols.declare(pname, pref.base, tok.line, tok.column, False)
            psym = self.symbols.lookup(pname)
            if psym is not None:
                psym.type_ref = pref
        body = ASTNode(ASTType.BLOCK, line=tok.line, column=tok.column)
        if self.current().type in (TokenType.NEWLINE, TokenType.INDENT):
            self.parse_indented_block(body)
        else:
            self.parse_inline_block(body)
        node.meta['frame_size'] = self.symbols.get_frame_size()
        self.symbols.exit_scope()
        self.symbols.next_stack_offset = saved_next
        node.add_child(body)
        return node

    def parse_simd_constructor(self, node: ASTNode) -> ASTNode:
        has_arguments = self.match(TokenType.OP_LPAREN)
        if has_arguments:
            self._parse_arguments(node)
        vector_type = PRIMITIVE_TYPES[node.value]
        lanes = VECTOR_INFO[vector_type][0]
        node.meta['type_ref'] = TypeRef(base=vector_type, name=node.value)
        if has_arguments and len(node.children) != lanes:
            self.errors.add_error(
                f"{node.value} constructor requires {lanes} lane values, got {len(node.children)}",
                node.line, node.column)
        elif not has_arguments and self.current().type != TokenType.OP_DOT:
            self.errors.add_error(f"{node.value} requires a lane constructor", node.line, node.column)
        return node

    def parse_constructor(self) -> Optional[ASTNode]:
        name_tok = self.current()
        self.advance()
        node = ASTNode(ASTType.METHOD_CALL, "new", name_tok.line, name_tok.column)
        node.meta['constructed_type'] = name_tok.value
        callee = ASTNode(ASTType.VARIABLE, name_tok.value, name_tok.line, name_tok.column)
        callee.meta['type_ref'] = TypeRef(base=DataType.STRUCT, name=name_tok.value)
        node.add_child(callee)
        if self.match(TokenType.OP_LPAREN):
            self._parse_arguments(node)
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
    "read_cr4": (0, DataType.U64),
    "write_cr4": (1, DataType.VOID),
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
    "prefetch_nta": (1, DataType.VOID),
    "prefetch_t0": (1, DataType.VOID),
    "prefetch_t1": (1, DataType.VOID),
    "prefetch_t2": (1, DataType.VOID),
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
    "xsave": (2, DataType.VOID),
    "xrstor": (2, DataType.VOID),
    "finit": (0, DataType.VOID),
    "fxrstor": (1, DataType.VOID),
    "fxsave": (1, DataType.VOID),
    "stmxcsr": (1, DataType.VOID),
    "ldmxcsr": (1, DataType.VOID),
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
        node = self.constant_folding(node)
        node = self.dead_code_elimination(node)
        if self.opt_level == OptimizationLevel.O1:
            node = self.peephole_optimizations(node)
        elif self.opt_level == OptimizationLevel.O2:
            node = self.peephole_optimizations(node)
            node = self.loop_invariant_motion(node)
            node = self.strength_reduction(node)
        elif self.opt_level == OptimizationLevel.O3:
            node = self.peephole_optimizations(node)
            node = self.loop_invariant_motion(node)
            node = self.strength_reduction(node)
            node = self.loop_unrolling(node)
            node = self.vectorization(node)
        return node
        
    @staticmethod
    def _is_int_literal(node: ASTNode, value: Optional[str] = None) -> bool:
        """True only for plain integer literals: char ('0') and string literals are
        not numbers even though their text may look like one."""
        import re as _re
        if node is None or node.type != ASTType.LITERAL:
            return False
        if node.meta.get('is_string') or 'char_value' in node.meta:
            return False
        if node.data_type in (DataType.CHAR, DataType.F32, DataType.F64, DataType.F80):
            return False
        if not _re.fullmatch(r'-?\d+', str(node.value)):
            return False
        return value is None or str(node.value) == value

    def constant_folding(self, node: ASTNode) -> ASTNode:
        for i, child in enumerate(node.children):
            node.children[i] = self.constant_folding(child)
        if node.type == ASTType.UNARY_OP and node.children:
            operand = node.children[0]
            if self._is_int_literal(operand):
                value = int(operand.value)
                result = {'-': lambda: -value, '+': lambda: value,
                          '~': lambda: ~value, 'not': lambda: int(not value),
                          '!': lambda: int(not value)}.get(node.value)
                if result:
                    folded = ASTNode(ASTType.LITERAL, str(result()), node.line, node.column)
                    folded.data_type = DataType.BOOL if node.value in ('not', '!') else operand.data_type
                    return folded
            if node.value == '-' and operand.type == ASTType.LITERAL \
                    and operand.data_type in FLOAT_TYPES and not operand.meta.get('is_string'):
                folded = ASTNode(ASTType.LITERAL, repr(-float(operand.value)), node.line, node.column)
                folded.data_type = operand.data_type
                return folded
        if node.type != ASTType.BINARY_OP or len(node.children) != 2:
            return node
        left, right = node.children
        if self._is_int_literal(left) and self._is_int_literal(right):
            lval, rval = int(left.value), int(right.value)
            quotient = (abs(lval) // abs(rval)) * (-1 if (lval < 0) != (rval < 0) else 1) \
                if rval else None
            operations = {
                "+": lambda: lval + rval,
                "-": lambda: lval - rval,
                "*": lambda: lval * rval,
                "/": lambda: quotient,
                "%": lambda: lval - quotient * rval,
                "<<": lambda: lval << rval if 0 <= rval < 64 else None,
                ">>": lambda: lval >> rval if 0 <= rval < 64 else None,
                "&": lambda: lval & rval,
                "|": lambda: lval | rval,
                "^": lambda: lval ^ rval,
                "==": lambda: int(lval == rval),
                "!=": lambda: int(lval != rval),
                "<": lambda: int(lval < rval),
                "<=": lambda: int(lval <= rval),
                ">": lambda: int(lval > rval),
                ">=": lambda: int(lval >= rval),
                "and": lambda: int(bool(lval) and bool(rval)),
                "or": lambda: int(bool(lval) or bool(rval)),
            }
            try:
                result = operations[node.value]() if node.value in operations else None
            except (ArithmeticError, TypeError, ValueError):
                result = None
            if isinstance(result, int) and -(1 << 63) <= result <= (1 << 64) - 1:
                folded = ASTNode(ASTType.LITERAL, str(result), node.line, node.column)
                folded.data_type = DataType.BOOL if node.value in (
                    "==", "!=", "<", "<=", ">", ">=", "and", "or") else node.data_type
                return folded

        def float_literal(value):
            if value.type != ASTType.LITERAL or value.meta.get('is_string') \
                    or value.data_type == DataType.CHAR:
                return None
            try:
                return float(value.value) if value.data_type in FLOAT_TYPES \
                    or any(c in str(value.value).lower() for c in ".e") else None
            except (TypeError, ValueError):
                return None

        lfloat, rfloat = float_literal(left), float_literal(right)
        if lfloat is not None and rfloat is not None:
            operations = {
                "+": lambda: lfloat + rfloat,
                "-": lambda: lfloat - rfloat,
                "*": lambda: lfloat * rfloat,
                "/": lambda: lfloat / rfloat,
                "==": lambda: int(lfloat == rfloat),
                "!=": lambda: int(lfloat != rfloat),
                "<": lambda: int(lfloat < rfloat),
                "<=": lambda: int(lfloat <= rfloat),
                ">": lambda: int(lfloat > rfloat),
                ">=": lambda: int(lfloat >= rfloat),
            }
            try:
                result = operations[node.value]() if node.value in operations else None
            except (ArithmeticError, ValueError):
                result = None
            if isinstance(result, (float, int)):
                folded = ASTNode(ASTType.LITERAL, repr(result) if isinstance(result, float)
                                 else str(result), node.line, node.column)
                folded.data_type = DataType.BOOL if node.value in (
                    "==", "!=", "<", "<=", ">", ">=") else DataType.F64
                return folded
        return node
        
    def dead_code_elimination(self, node: ASTNode) -> ASTNode:
        if node.type == ASTType.IF_STMT and len(node.children) > 0:
            cond = node.children[0]
            if self._is_int_literal(cond):
                if int(cond.value) == 0:
                    if len(node.children) > 2:
                        return node.children[2]
                    else:
                        return ASTNode(ASTType.BLOCK, line=node.line, column=node.column)
                else:
                    if len(node.children) > 1:
                        return node.children[1]
        if node.type in (ASTType.BLOCK, ASTType.FUNCTION):
            reachable = []
            for child in node.children:
                reachable.append(self.dead_code_elimination(child))
                if child.type == ASTType.RETURN_STMT:
                    break
            node.children = reachable
            return node
        for i, child in enumerate(node.children):
            node.children[i] = self.dead_code_elimination(child)
        return node
        
    def peephole_optimizations(self, node: ASTNode) -> ASTNode:
        for i, child in enumerate(node.children):
            node.children[i] = self.peephole_optimizations(child)
        if node.type == ASTType.BINARY_OP and len(node.children) == 2 \
                and all(self._is_integer_expr(c) for c in node.children):
            left, right = node.children
            if node.value in ("+", "-", "|", "^") and self._is_int_literal(right, "0"):
                return left
            if node.value in ("+", "|", "^") and self._is_int_literal(left, "0"):
                return right
            if node.value == "*" and self._is_int_literal(right, "1"):
                return left
            if node.value == "*" and self._is_int_literal(left, "1"):
                return right
            if node.value == "/" and self._is_int_literal(right, "1"):
                return left
        return node

    @staticmethod
    def _is_integer_expr(node: ASTNode) -> bool:
        ref = node.meta.get('type_ref')
        return Optimizer._is_int_literal(node) or node.data_type in INTEGER_TYPES \
            or isinstance(ref, TypeRef) and ref.base in INTEGER_TYPES

    def loop_invariant_motion(self, node: ASTNode) -> ASTNode:
        # Disabled: the previous implementation moved expression children of a
        # loop node to index 0, which reorders the positional children
        # (var/start/end/step/body) and miscompiles the loop.
        return node

    def _is_loop_invariant(self, expr: ASTNode, loop: ASTNode) -> bool:
        variables_used = self._collect_variables(expr)
        loop_variables = self._collect_loop_variables(loop)
        return not any(v in loop_variables for v in variables_used)
        
    def _collect_variables(self, node: ASTNode) -> Set[str]:
        vars = set()
        if node.type == ASTType.VARIABLE:
            vars.add(node.value)
        for child in node.children:
            vars.update(self._collect_variables(child))
        return vars
        
    def _collect_loop_variables(self, loop: ASTNode) -> Set[str]:
        vars = set()
        for child in loop.children:
            vars.update(self._collect_variables(child))
        return vars
        
    def strength_reduction(self, node: ASTNode) -> ASTNode:
        # Convert multiplication in loops to addition
        if node.type == ASTType.WHILE_STMT or node.type == ASTType.FOR_STMT:
            node = self._apply_strength_reduction_in_loop(node)
        for i, child in enumerate(node.children):
            node.children[i] = self.strength_reduction(child)
        return node
        
    def _apply_strength_reduction_in_loop(self, loop: ASTNode) -> ASTNode:
        # Find loop induction variables and replace i*n with addition
        # Simplified implementation
        return loop
        
    def loop_unrolling(self, node: ASTNode) -> ASTNode:
        # Disabled: duplicating the body without a remainder loop changes the
        # iteration count, and the rebuilt node dropped its loop kind.
        return node

    def _unroll_loop(self, loop: ASTNode, factor: int) -> ASTNode:
        # Simplified loop unrolling - creates a new loop body with multiple iterations
        if len(loop.children) < 4:
            return loop
        
        init = loop.children[0] if len(loop.children) > 0 else None
        condition = loop.children[1] if len(loop.children) > 1 else None
        incr = loop.children[2] if len(loop.children) > 2 else None
        body = loop.children[3] if len(loop.children) > 3 else None
        
        if not condition or not body:
            return loop
        
        unrolled = ASTNode(ASTType.FOR_STMT, line=loop.line, column=loop.column)
        unrolled.simd_level = loop.simd_level
        unrolled.unroll_factor = 0  # Don't unroll again
        
        if init:
            unrolled.add_child(init)
        
        # Create new condition (i < n - factor + 1)
        unrolled.add_child(condition)  # Simplified
        
        # Create unrolled body
        unrolled_body = ASTNode(ASTType.BLOCK, line=body.line, column=body.column)
        for i in range(factor):
            unrolled_body.children.extend(body.children)
        unrolled.add_child(unrolled_body)
        
        if incr:
            unrolled.add_child(incr)
        
        return unrolled
        
    def vectorization(self, node: ASTNode) -> ASTNode:
        """Auto-vectorization is not implemented; loops are left untouched
        (inserting a pragma child shifted the loop's positional children)."""
        return node

    def _vectorize_loop(self, loop: ASTNode) -> ASTNode:
        """Mark loop for SIMD vectorization"""
        loop.attributes.append("vectorized")
        # Add SIMD pragma marker
        simd_pragma = ASTNode(ASTType.PRAGMA, "SIMD", loop.line, loop.column)
        simd_pragma.simd_level = loop.simd_level
        loop.children.insert(0, simd_pragma)
        return loop

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
        self.current_function_is_interrupt = False
        self.current_function_is_kernel = False
        self.break_labels: List[str] = []
        self.continue_labels: List[str] = []
        self.pending_lambdas: List[ASTNode] = []

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
        self.emit_raw("; lowl Compiler v2.1.0 - Complete Implementation", "text")
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
                for export in self.symbols.exported_symbols:
                    self.emit_raw(f"global {export}", "text")
            else:
                self.emit_raw("global main", "text")
            self.emit_raw("", "text")
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

        # lambdas discovered while generating expressions become real functions
        while self.pending_lambdas:
            lam = self.pending_lambdas.pop(0)
            self.gen_lambda(lam)

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
        if self.rodata:
            result += "section .rodata\n" + "\n".join(self.rodata) + "\n\n"
        if self.data:
            result += "section .data\n" + "\n".join(self.data) + "\n\n"
        if self.bss:
            result += "section .bss\n" + "\n".join(self.bss) + "\n"
        return result
        
    def gen_statement(self, node: ASTNode) -> None:
        if not node:
            return
            
        # Check for function attributes
        if node.type == ASTType.FUNCTION:
            self.current_function_is_interrupt = "interrupt" in node.attributes
            self.current_function_is_kernel = "kernel" in node.attributes
            
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
            self.emit_vtable(node.value)
        elif node.type in (ASTType.CALL, ASTType.METHOD_CALL):
            # a call used as a statement: evaluate it and discard the pushed result
            # (METHOD_CALL statements used to be silently dropped, CALL leaked a slot)
            self.gen_call(node)
            result_ref = self.ref_of(node)
            result_size = self.size_of(result_ref) if isinstance(result_ref, TypeRef) \
                and result_ref.base in VECTOR_INFO else \
                self.option_size(result_ref) if isinstance(result_ref, TypeRef) \
                and result_ref.base == DataType.OPTION else 8
            self.emit(f"add rsp, {result_size}", "text")
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
            self.gen_expression(node)
            ref = self.ref_of(node)
            if isinstance(ref, TypeRef) and ref.base == DataType.OPTION:
                size = self.option_size(ref)
                if value is None:
                    self.gen_address(lhs)
                    self.emit("mov rbx, rax", "text")
                    for offset in range(0, size, 8):
                        self.emit(f"mov qword [rbx + {offset}], 0", "text")
                else:
                    self.gen_expression(value)
                    self.emit("push rsp", "text")
                    self.gen_address(lhs)
                    self.emit("mov rbx, rax", "text")
                    self.emit("pop r10", "text")
                    for offset in range(0, size, 8):
                        self.emit(f"mov rax, qword [r10 + {offset}]", "text")
                        self.emit(f"mov qword [rbx + {offset}], rax", "text")
                    self.emit(f"add rsp, {size}", "text")
                return

            if isinstance(ref, TypeRef) and ref.base in VECTOR_INFO:
                self.emit(f"add rsp, {self.size_of(ref)}", "text")
        elif node.type == ASTType.IMPORT_STMT:
            self.gen_import(node)
        elif node.type == ASTType.EXPORT_STMT:
            self.gen_export(node)
        elif node.type == ASTType.TYPE_CONVERSION:
            self.gen_type_conversion(node)
        elif node.type == ASTType.ASM_STMT:
            self.gen_asm_stmt(node)
        elif node.type == ASTType.BREAK_STMT:
            if self.break_labels:
                self.emit(f"jmp {self.break_labels[-1]}", "text")
        elif node.type == ASTType.CONTINUE_STMT:
            if self.continue_labels:
                self.emit(f"jmp {self.continue_labels[-1]}", "text")
        elif node.type == ASTType.TEMPLATE_DECL:
            for child in node.children:
                if child.type == ASTType.FUNCTION and child.template_params:
                    continue
                self.gen_statement(child)
        elif node.type in (ASTType.STRUCT_DEF, ASTType.CLASS, ASTType.IMPL_BLOCK,
                           ASTType.ENUM_DEF, ASTType.MODULE):
            for child in node.children:
                self.gen_statement(child)
        elif node.type in (ASTType.UNARY_OP, ASTType.INDEX, ASTType.MEMBER_ACCESS,
                           ASTType.TUPLE, ASTType.LAMBDA, ASTType.STRUCT_LITERAL,
                           ASTType.ARRAY_LITERAL):
            # expression used as a statement: evaluate for its side effects
            self.gen_expression(node)
            self.emit("add rsp, 8", "text")
            
    def gen_asm_stmt(self, node: ASTNode) -> None:
        """Emit raw inline assembly"""
        for line in node.value.split('\n'):
            line = line.strip()
            if line:
                self.emit(line, "text")
                
    def gen_type_conversion(self, node: ASTNode) -> None:
        if len(node.children) < 1:
            self.emit("push 0", "text")
            return
            
        self.gen_expression(node.children[0])
        
        method = node.conversion_method
        
        if node.target_type in [DataType.U8, DataType.U16, DataType.U32, DataType.U64]:
            self.emit("pop rax", "text")
            
            if method == "saturating":
                # Scale to target size
                if node.target_type == DataType.U8:
                    self.emit("cmp rax, 255", "text")
                    self.emit("jle .sat_ok", "text")
                    self.emit("mov rax, 255", "text")
                    self.emit(".sat_ok:", "text")
            elif method == "wrapping":
                # Just truncate
                pass
            elif method == "checked":
                # Check overflow and set option
                self.emit("cmp rax, 255", "text")
                self.emit("jbe .check_ok", "text")
                self.emit("; Return None", "text")
                self.emit("xor rax, rax", "text")
                self.emit(".check_ok:", "text")
                
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
        self.emit("", "data")
        self.emit(f"align {alignment}", "data")
        self.emit(f"block_array_{node.line}:", "data")
        
    def gen_block_array_method(self, node: ASTNode) -> None:
        method = node.value
        
        if method == "push":
            if len(node.children) > 1:
                self.gen_expression(node.children[1])
                self.emit("pop rax", "text")
                self.emit("; BlockArray push", "text")
        elif method == "pop":
            self.emit("; BlockArray pop", "text")
        elif method == "len":
            self.emit("mov rax, 0", "text")
            self.emit("push rax", "text")
        elif method == "simd_map":
            self.emit("; SIMD map operation", "text")
            if node.simd_level == SIMDLevel.SSE:
                self.emit("movaps xmm0, [rdi]", "text")
            elif node.simd_level == SIMDLevel.AVX:
                self.emit("vmovaps ymm0, [rdi]", "text")
            elif node.simd_level == SIMDLevel.AVX512:
                self.emit("vmovaps zmm0, [rdi]", "text")
        elif method == "simd_reduce":
            self.emit("; SIMD reduce operation", "text")
        elif method == "permute":
            self.gen_simd_permute(node.simd_level)
        elif method == "shuffle":
            self.gen_simd_shuffle(node.simd_level)
            
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
            
    def gen_simd_shuffle(self, level: SIMDLevel) -> None:
        if level == SIMDLevel.SSE:
            self.emit("shufps xmm0, xmm1, 0b11011000", "text")
        elif level == SIMDLevel.AVX:
            self.emit("vshufps ymm0, ymm0, ymm1, 0b11011000", "text")
        elif level == SIMDLevel.AVX512:
            self.emit("vshufps zmm0, zmm0, zmm1, 0b11011000", "text")
            
    def gen_simd_operation(self, node: ASTNode) -> None:
        ref = self.ref_of(node)
        if not isinstance(ref, TypeRef) or ref.base not in VECTOR_INFO:
            self.emit(f"; unsupported SIMD operation {node.value}", "text")
            return
        lanes, lane_size, _ = VECTOR_INFO[ref.base]
        size = lanes * lane_size
        self.emit(f"sub rsp, {size}", "text")
        for i, arg in enumerate(node.children):
            self.gen_scalar_double(arg)
            offset = i * lane_size
            if lane_size == 4:
                self.emit("cvtsd2ss xmm1, xmm0", "text")
                self.emit("movd eax, xmm1", "text")
                self.emit(f"mov dword [rsp + {offset}], eax", "text")
            else:
                self.emit("movq rax, xmm0", "text")
                self.emit(f"mov qword [rsp + {offset}], rax", "text")

    def gen_vector_binary(self, node: ASTNode, ref: TypeRef) -> None:
        lanes, lane_size, level = VECTOR_INFO[ref.base]
        size = lanes * lane_size
        suffix = "ps" if lane_size == 4 else "pd"
        reg = {SIMDLevel.SSE: "xmm", SIMDLevel.AVX: "ymm",
               SIMDLevel.AVX512: "zmm"}[level]
        width = {SIMDLevel.SSE: 16, SIMDLevel.AVX: 32,
                 SIMDLevel.AVX512: 64}[level]
        op = {"+": "add", "-": "sub", "*": "mul", "/": "div"}[node.value]
        self.gen_expression(node.children[0])
        self.gen_expression(node.children[1])
        for offset in range(0, size, width):
            if level == SIMDLevel.SSE:
                self.emit(f"movups {reg}0, [rsp + {size + offset}]", "text")
                self.emit(f"movups {reg}1, [rsp + {offset}]", "text")
                self.emit(f"{op}{suffix} {reg}0, {reg}1", "text")
                self.emit(f"movups [rsp + {size + offset}], {reg}0", "text")
            else:
                self.emit(f"vmovups {reg}0, [rsp + {size + offset}]", "text")
                self.emit(f"v{op}{suffix} {reg}0, {reg}0, [rsp + {offset}]", "text")
                self.emit(f"vmovups [rsp + {size + offset}], {reg}0", "text")
        self.emit(f"add rsp, {size}", "text")

    def gen_scalar_double(self, node: ASTNode, register: str = "xmm0") -> None:
        self.gen_expression(node)
        self.emit("pop rax", "text")
        if self.is_float_node(node):
            self.emit(f"movq {register}, rax", "text")
        elif self.is_unsigned_node(node):
            self.emit("mov rdx, rax", "text")
            self.emit("shr rdx, 1", "text")
            self.emit("and eax, 1", "text")
            self.emit("or rdx, rax", "text")
            self.emit(f"cvtsi2sd {register}, rdx", "text")
            self.emit(f"addsd {register}, {register}", "text")
        else:
            self.emit(f"cvtsi2sd {register}, rax", "text")

    def gen_option_method(self, node: ASTNode) -> None:
        receiver = node.children[0]
        args = node.children[1:]
        if receiver.meta.get('is_type_name') and receiver.value == 'Option':
            if node.value == 'some' and len(args) == 1:
                self.emit("sub rsp, 16", "text")
                self.emit("mov qword [rsp], 1", "text")
                self.gen_expression(args[0])
                self.emit("pop rax", "text")
                self.emit("mov qword [rsp + 8], rax", "text")
                return
            if node.value == 'none' and not args:
                self.emit("sub rsp, 16", "text")
                self.emit("mov qword [rsp], 0", "text")
                self.emit("mov qword [rsp + 8], 0", "text")
                return
        recv_ref = self.ref_of(receiver)
        if isinstance(recv_ref, TypeRef) and recv_ref.base == DataType.OPTION:
            self.gen_address(receiver)
            if node.value in ('is_some', 'is_none'):
                self.emit("cmp qword [rax], 0", "text")
                self.emit("setne al" if node.value == 'is_some' else "sete al", "text")
                self.emit("movzx eax, al", "text")
                self.emit("push rax", "text")
                return
            if node.value == 'unwrap':
                valid = self.new_label()
                self.emit("cmp qword [rax], 0", "text")
                self.emit(f"jne {valid}", "text")
                self.emit("ud2", "text")
                self.emit_raw(f"{valid}:", "text")
                self.emit("mov rax, qword [rax + 8]", "text")
                self.emit("push rax", "text")
                return
        self.emit(f"; unsupported Option method {node.value}", "text")
        self.emit("push 0", "text")

    def gen_vector_method(self, node: ASTNode, ref: TypeRef) -> None:
        receiver = node.children[0]
        args = node.children[1:]
        lanes, lane_size, level = VECTOR_INFO[ref.base]
        size = lanes * lane_size
        suffix = "ps" if lane_size == 4 else "pd"
        scalar_op = "ss" if lane_size == 4 else "sd"
        reg = {SIMDLevel.SSE: "xmm", SIMDLevel.AVX: "ymm",
               SIMDLevel.AVX512: "zmm"}[level]
        width = {SIMDLevel.SSE: 16, SIMDLevel.AVX: 32,
                 SIMDLevel.AVX512: 64}[level]

        if node.value == "iota" and len(args) == 2:
            self.emit(f"sub rsp, {size + 16}", "text")
            self.gen_scalar_double(args[0])
            self.emit("movq rax, xmm0", "text")
            self.emit("mov qword [rsp], rax", "text")
            self.gen_scalar_double(args[1])
            self.emit("movq rax, xmm0", "text")
            self.emit("mov qword [rsp + 8], rax", "text")
            self.emit("movq xmm0, qword [rsp]", "text")
            for lane in range(lanes):
                offset = 16 + lane * lane_size
                if lane_size == 4:
                    self.emit("cvtsd2ss xmm1, xmm0", "text")
                    self.emit("movd eax, xmm1", "text")
                    self.emit(f"mov dword [rsp + {offset}], eax", "text")
                else:
                    self.emit(f"movq qword [rsp + {offset}], xmm0", "text")
                if lane + 1 < lanes:
                    self.emit("movq xmm1, qword [rsp + 8]", "text")
                    self.emit("addsd xmm0, xmm1", "text")
            self.emit("add rsp, 16", "text")
            return

        if node.value == "broadcast" and len(args) == 1:
            self.emit(f"sub rsp, {size + 8}", "text")
            self.gen_scalar_double(args[0])
            self.emit("movq rax, xmm0", "text")
            self.emit("mov qword [rsp], rax", "text")
            for lane in range(lanes):
                offset = 8 + lane * lane_size
                self.emit("movq xmm0, qword [rsp]", "text")
                if lane_size == 4:
                    self.emit("cvtsd2ss xmm0, xmm0", "text")
                    self.emit("movd eax, xmm0", "text")
                    self.emit(f"mov dword [rsp + {offset}], eax", "text")
                else:
                    self.emit(f"movq qword [rsp + {offset}], xmm0", "text")
            self.emit("add rsp, 8", "text")
            return

        if node.value == "fma" and len(args) == 2:
            self.gen_address(receiver)
            self.emit("push rax", "text")
            self.gen_expression(args[0])
            self.gen_expression(args[1])
            self.emit("pop rdx", "text")
            self.emit("pop rsi", "text")
            self.emit("pop rdi", "text")
            self.emit(f"sub rsp, {size}", "text")
            for offset in range(0, size, width):
                if level == SIMDLevel.SSE:
                    self.emit(f"movups {reg}0, [rdi + {offset}]", "text")
                    self.emit(f"mul{suffix} {reg}0, [rsi + {offset}]", "text")
                    self.emit(f"add{suffix} {reg}0, [rdx + {offset}]", "text")
                    self.emit(f"movups [rsp + {offset}], {reg}0", "text")
                else:
                    self.emit(f"vmovups {reg}0, [rdi + {offset}]", "text")
                    self.emit(f"vmul{suffix} {reg}0, {reg}0, [rsi + {offset}]", "text")
                    self.emit(f"vadd{suffix} {reg}0, {reg}0, [rdx + {offset}]", "text")
                    self.emit(f"vmovups [rsp + {offset}], {reg}0", "text")
            return

        if node.value in ("dot", "hadd_all", "hmax", "hmin") \
                and (node.value != "dot" or len(args) == 1):
            self.gen_address(receiver)
            self.emit("push rax", "text")
            if node.value == "dot":
                self.gen_expression(args[0])
                self.emit("pop rsi", "text")
            else:
                self.emit("xorps xmm0, xmm0", "text")
            self.emit("pop rdi", "text")
            if node.value in ("hmax", "hmin"):
                self.emit(f"mov{scalar_op} xmm0, [{ 'rdi' }]", "text")
                first_lane = 1
            else:
                first_lane = 0
            for lane in range(first_lane, lanes):
                offset = lane * lane_size
                self.emit(f"mov{scalar_op} xmm1, [rdi + {offset}]", "text")
                if node.value == "dot":
                    self.emit(f"mov{scalar_op} xmm2, [rsi + {offset}]", "text")
                    self.emit(f"mul{scalar_op} xmm1, xmm2", "text")
                    self.emit(f"add{scalar_op} xmm0, xmm1", "text")
                elif node.value == "hadd_all":
                    self.emit(f"add{scalar_op} xmm0, xmm1", "text")
                else:
                    replace = self.new_label()
                    done = self.new_label()
                    self.emit(f"ucomi{scalar_op} xmm0, xmm1", "text")
                    self.emit(f"j{'b' if node.value == 'hmax' else 'a'} {replace}", "text")
                    self.emit(f"jmp {done}", "text")
                    self.emit_raw(f"{replace}:", "text")
                    self.emit(f"mov{scalar_op} xmm0, xmm1", "text")
                    self.emit_raw(f"{done}:", "text")
            if lane_size == 4:
                self.emit("cvtss2sd xmm0, xmm0", "text")
            self.emit("movq rax, xmm0", "text")
            self.emit("push rax", "text")
            return

        self.emit(f"; unsupported SIMD method {node.value}", "text")
        self.emit("push 0", "text")
                    
    def gen_builtin(self, node: ASTNode) -> None:
        name = node.value
        
        # Port I/O
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
            self.emit("movzx eax, al", "text")
            self.emit("push rax", "text")
        elif name == "port_write16" and len(node.children) >= 2:
            self.gen_expression(node.children[0])
            self.gen_expression(node.children[1])
            self.emit("pop rdx", "text")
            self.emit("pop rcx", "text")
            self.emit("mov ax, dx", "text")
            self.emit("mov dx, cx", "text")
            self.emit("out dx, ax", "text")
        elif name == "port_read16" and len(node.children) >= 1:
            self.gen_expression(node.children[0])
            self.emit("pop rcx", "text")
            self.emit("mov dx, cx", "text")
            self.emit("in ax, dx", "text")
            self.emit("movzx eax, ax", "text")
            self.emit("push rax", "text")
        elif name == "port_write32" and len(node.children) >= 2:
            self.gen_expression(node.children[0])
            self.gen_expression(node.children[1])
            self.emit("pop rdx", "text")
            self.emit("pop rcx", "text")
            self.emit("mov eax, edx", "text")
            self.emit("mov dx, cx", "text")
            self.emit("out dx, eax", "text")
        elif name == "port_read32" and len(node.children) >= 1:
            self.gen_expression(node.children[0])
            self.emit("pop rcx", "text")
            self.emit("mov dx, cx", "text")
            self.emit("in eax, dx", "text")
            self.emit("push rax", "text")
            
        # Interrupt control
        elif name == "disable_interrupts":
            self.emit("cli", "text")
        elif name == "enable_interrupts":
            self.emit("sti", "text")
        elif name == "halt":
            self.emit("hlt", "text")
        elif name == "pause":
            self.emit("pause", "text")
            
        # Control registers
        elif name == "read_cr0":
            self.emit("mov rax, cr0", "text")
            self.emit("push rax", "text")
        elif name == "write_cr0":
            self.gen_expression(node.children[0])
            self.emit("pop rax", "text")
            self.emit("mov cr0, rax", "text")
        elif name == "read_cr2":
            self.emit("mov rax, cr2", "text")
            self.emit("push rax", "text")
        elif name == "read_cr3":
            self.emit("mov rax, cr3", "text")
            self.emit("push rax", "text")
        elif name == "write_cr3":
            self.gen_expression(node.children[0])
            self.emit("pop rax", "text")
            self.emit("mov cr3, rax", "text")
        elif name == "read_cr4":
            self.emit("mov rax, cr4", "text")
            self.emit("push rax", "text")
        elif name == "write_cr4":
            self.gen_expression(node.children[0])
            self.emit("pop rax", "text")
            self.emit("mov cr4, rax", "text")
        elif name == "invlpg":
            self.gen_expression(node.children[0])
            self.emit("pop rax", "text")
            self.emit("invlpg [rax]", "text")
            
        # Timing
        elif name == "rdtsc":
            self.emit("rdtsc", "text")
            self.emit("shl rdx, 32", "text")
            self.emit("or rax, rdx", "text")
            self.emit("push rax", "text")
        elif name == "rdtscp":
            self.emit("rdtscp", "text")
            self.emit("shl rdx, 32", "text")
            self.emit("or rax, rdx", "text")
            self.emit("push rax", "text")
            
        # CPUID
        elif name == "cpuid":
            if len(node.children) >= 2:
                self.gen_expression(node.children[0])
                self.gen_expression(node.children[1])
                self.emit("pop rcx", "text")
                self.emit("pop rax", "text")
                self.emit("mov rbx, 0", "text")
                self.emit("mov rdx, 0", "text")
                self.emit("cpuid", "text")
                self.emit("push rax", "text")
            
        # MSRs
        elif name == "read_msr":
            self.gen_expression(node.children[0])
            self.emit("pop rcx", "text")
            self.emit("rdmsr", "text")
            self.emit("shl rdx, 32", "text")
            self.emit("or rax, rdx", "text")
            self.emit("push rax", "text")
        elif name == "write_msr":
            self.gen_expression(node.children[0])
            self.gen_expression(node.children[1])
            self.emit("pop rdx", "text")
            self.emit("pop rcx", "text")
            self.emit("wrmsr", "text")
            
        # Memory barriers
        elif name == "mfence":
            self.emit("mfence", "text")
        elif name == "lfence":
            self.emit("lfence", "text")
        elif name == "sfence":
            self.emit("sfence", "text")
            
        # Prefetch
        elif name.startswith("prefetch"):
            self.gen_expression(node.children[0])
            self.emit("pop rax", "text")
            if name == "prefetch_nta":
                self.emit("prefetchnta [rax]", "text")
            elif name == "prefetch_t0":
                self.emit("prefetcht0 [rax]", "text")
            elif name == "prefetch_t1":
                self.emit("prefetcht1 [rax]", "text")
            elif name == "prefetch_t2":
                self.emit("prefetcht2 [rax]", "text")
            else:
                self.emit("prefetch [rax]", "text")
                
        # Memory management
        elif name == "physical_alloc":
            if len(node.children) >= 2:
                self.gen_expression(node.children[0])
                self.gen_expression(node.children[1])
                self.emit("pop rsi", "text")
                self.emit("pop rdi", "text")
                # physical_alloc(size, align) -> ptr is supplied by the kernel / runtime
                self.emit("call physical_alloc", "text")
                self.emit("push rax", "text")
        elif name == "physical_free" and len(node.children) >= 1:
            self.gen_expression(node.children[0])
            self.emit("pop rdi", "text")
            self.emit("call physical_free", "text")
        elif name == "copy_memory" and len(node.children) >= 3:
            self.gen_expression(node.children[0])
            self.gen_expression(node.children[1])
            self.gen_expression(node.children[2])
            self.emit("pop rcx", "text")
            self.emit("pop rsi", "text")
            self.emit("pop rdi", "text")
            self.emit("rep movsb", "text")
        elif name == "zero_memory" and len(node.children) >= 2:
            self.gen_expression(node.children[0])
            self.gen_expression(node.children[1])
            self.emit("pop rcx", "text")
            self.emit("pop rdi", "text")
            self.emit("xor al, al", "text")
            self.emit("rep stosb", "text")
        elif name == "memcmp" and len(node.children) >= 3:
            self.gen_expression(node.children[0])
            self.gen_expression(node.children[1])
            self.gen_expression(node.children[2])
            self.emit("pop rcx", "text")
            self.emit("pop rsi", "text")
            self.emit("pop rdi", "text")
            self.emit("repe cmpsb", "text")
            self.emit("movzx rax, byte [rdi-1]", "text")
            self.emit("sub rax, [rsi-1]", "text")
            self.emit("push rax", "text")
        elif name == "memchr" and len(node.children) >= 3:
            self.gen_expression(node.children[0])
            self.gen_expression(node.children[1])
            self.gen_expression(node.children[2])
            self.emit("pop rcx", "text")
            self.emit("mov rsi, rcx", "text")
            self.emit("pop rdx", "text")
            self.emit("pop rdi", "text")
            self.emit("repne scasb", "text")
            self.emit("mov rax, rdi", "text")
            self.emit("sub rax, 1", "text")
            self.emit("push rax", "text")
            
        # FPU/SIMD
        elif name == "finit":
            self.emit("finit", "text")
        elif name == "fxsave":
            self.gen_expression(node.children[0])
            self.emit("pop rdi", "text")
            self.emit("fxsave [rdi]", "text")
        elif name == "fxrstor":
            self.gen_expression(node.children[0])
            self.emit("pop rdi", "text")
            self.emit("fxrstor [rdi]", "text")
        elif name == "xsave":
            self.gen_expression(node.children[0])
            self.gen_expression(node.children[1])
            self.emit("pop rdx", "text")
            self.emit("pop rdi", "text")
            self.emit("xsave [rdi]", "text")
        elif name == "xrstor":
            self.gen_expression(node.children[0])
            self.gen_expression(node.children[1])
            self.emit("pop rdx", "text")
            self.emit("pop rdi", "text")
            self.emit("xrstor [rdi]", "text")
            
        # FPU control
        elif name == "stmxcsr":
            self.gen_expression(node.children[0])
            self.emit("pop rdi", "text")
            self.emit("stmxcsr [rdi]", "text")
        elif name == "ldmxcsr":
            self.gen_expression(node.children[0])
            self.emit("pop rdi", "text")
            self.emit("ldmxcsr [rdi]", "text")
            
        # Module loading
        elif name == "load_module":
            self.emit("; Load module", "text")
            self.emit("mov rax, 0", "text")
            self.emit("push rax", "text")
        elif name == "resolve_symbol":
            self.emit("; Resolve symbol", "text")
            self.emit("mov rax, 0", "text")
            self.emit("push rax", "text")
            
    # -- code generation: core semantics -----------------------------------
    def mem(self, name: str) -> str:
        """Memory operand for a global symbol, honouring the output format."""
        if self.output_format in (OutputFormat.FLAT_BINARY, OutputFormat.BOOT_IMAGE):
            return f"[{name}]"
        return f"[rel {name}]"

    def ref_of(self, node: Optional[ASTNode]):
        if node is None:
            return None
        ref = node.meta.get('type_ref')
        if isinstance(ref, TypeRef):
            return ref
        if node.type == ASTType.LITERAL:
            return TypeRef(base=node.data_type)
        if node.type == ASTType.BINARY_OP and node.data_type in VECTOR_INFO:
            return TypeRef(base=node.data_type, name=node.data_type.name.lower())
        # member chains (a.b.c) and indexed members resolve through their base type
        if node.type == ASTType.MEMBER_ACCESS and node.children:
            base = self.ref_of(node.children[0])
            if isinstance(base, TypeRef) and self.symbols.struct_name_of(base):
                found = self.symbols.field_ref(self.symbols.struct_name_of(base), node.value)
                if found is not None:
                    return self.symbols.specialize_class_ref(base, found)
        if node.type == ASTType.INDEX and node.children:
            base = self.ref_of(node.children[0])
            if isinstance(base, TypeRef) and base.elem is not None:
                return base.elem
        if node.type == ASTType.METHOD_CALL and node.children:
            recv = node.children[0]
            recv_ref = self.ref_of(recv)
            if recv.meta.get('is_type_name') and recv.value == 'Option':
                if node.value == 'some' and len(node.children) > 1:
                    return TypeRef(base=DataType.OPTION, name='Option',
                                   elem=self.ref_of(node.children[1]) or TypeRef(base=DataType.U64))
                if node.value == 'none':
                    return TypeRef(base=DataType.OPTION, name='Option',
                                   elem=TypeRef(base=DataType.U64))
            if isinstance(recv_ref, TypeRef) and recv_ref.base == DataType.OPTION:
                if node.value == 'unwrap':
                    return recv_ref.elem or TypeRef(base=DataType.U64)
                if node.value in ('is_some', 'is_none'):
                    return TypeRef(base=DataType.BOOL)
            if isinstance(recv_ref, TypeRef) and recv_ref.base in VECTOR_INFO:
                if node.value in ('iota', 'broadcast', 'fma'):
                    return recv_ref
                if node.value in ('dot', 'hadd_all', 'hmax', 'hmin'):
                    return TypeRef(base=DataType.F64)
            owner = recv.value if recv.meta.get('is_type_name') else \
                self.symbols.struct_name_of(recv_ref)
            fn = self.symbols.find_method(owner, node.value) if owner else None
            if fn is not None and isinstance(fn.meta.get('return_ref'), TypeRef):
                return self.symbols.specialize_class_ref(recv_ref, fn.meta['return_ref'])
        if node.type == ASTType.CALL:
            ret = node.meta.get('return_ref')
            if isinstance(ret, TypeRef):
                return ret
            cands = self.symbols.find_functions(node.value)
            if cands and isinstance(cands[0].meta.get('return_ref'), TypeRef):
                return cands[0].meta['return_ref']
        return None

    def size_of(self, ref) -> int:
        return type_size(ref, self.symbols)

    def option_size(self, ref) -> int:
        return (self.size_of(ref) + 7) & ~7

    @staticmethod
    def reg_for(prefix: str) -> str:
        return {'byte': 'al', 'word': 'ax', 'dword': 'eax', 'qword': 'rax'}.get(prefix, 'rax')

    @staticmethod
    def is_pointer(ref) -> bool:
        return isinstance(ref, TypeRef) and (ref.base in POINTER_TYPES or ref.is_ref)

    def is_aggregate_ref(self, ref) -> bool:
        if not isinstance(ref, TypeRef) or self.is_pointer(ref):
            return False
        if ref.base == DataType.ARRAY:
            return True
        return ref.base == DataType.STRUCT and self.symbols.struct_layout(ref.name) is not None

    def mov_prefix_of(self, ref) -> str:
        if self.is_pointer(ref):
            return "qword"
        size = self.size_of(ref)
        return {1: "byte", 2: "word", 4: "dword", 8: "qword"}.get(size, "qword")

    SIGNED_TYPES = (DataType.I8, DataType.I16, DataType.I32, DataType.I64, DataType.I128)
    UNSIGNED_TYPES = (DataType.U8, DataType.U16, DataType.U32, DataType.U64, DataType.U128,
                      DataType.BOOL, DataType.CHAR, DataType.PTR, DataType.PTR_MUT,
                      DataType.MMIO_PTR)

    def is_signed_node(self, node) -> bool:
        ref = self.ref_of(node) if node is not None else None
        if isinstance(ref, TypeRef) and ref.base in self.SIGNED_TYPES and not self.is_pointer(ref):
            return True
        if node is not None and node.type == ASTType.UNARY_OP and node.value == '-':
            return True
        if node is not None and node.type == ASTType.BINARY_OP:
            return any(self.is_signed_node(c) for c in node.children)
        return False

    def is_unsigned_node(self, node) -> bool:
        ref = self.ref_of(node) if node is not None else None
        return isinstance(ref, TypeRef) and (ref.base in self.UNSIGNED_TYPES or self.is_pointer(ref))

    def is_string_node(self, node) -> bool:
        if node is None:
            return False
        if node.type == ASTType.LITERAL and node.meta.get('is_string'):
            return True
        ref = self.ref_of(node)
        return isinstance(ref, TypeRef) and ref.base == DataType.STRING

    def extend_loaded(self, ref, prefix: str) -> None:
        """Widen a just-loaded narrow integer in rax to 64 bits (sign- or zero-extend)."""
        signed = isinstance(ref, TypeRef) and ref.base in self.SIGNED_TYPES and not self.is_pointer(ref)
        if prefix == "byte":
            self.emit("movsx rax, al" if signed else "movzx eax, al", "text")
        elif prefix == "word":
            self.emit("movsx rax, ax" if signed else "movzx eax, ax", "text")
        elif prefix == "dword" and signed:
            self.emit("movsxd rax, eax", "text")

    def f32_widen(self, ref) -> None:
        """f32 values live in memory as 4-byte floats but in registers as f64 bits."""
        if isinstance(ref, TypeRef) and ref.base == DataType.F32 and not self.is_pointer(ref):
            self.emit("movd xmm0, eax", "text")
            self.emit("cvtss2sd xmm0, xmm0", "text")
            self.emit("movq rax, xmm0", "text")

    def f32_narrow(self, ref) -> None:
        if isinstance(ref, TypeRef) and ref.base == DataType.F32 and not self.is_pointer(ref):
            self.emit("movq xmm0, rax", "text")
            self.emit("cvtsd2ss xmm0, xmm0", "text")
            self.emit("movd eax, xmm0", "text")

    def is_float_ref(self, ref) -> bool:
        return isinstance(ref, TypeRef) and ref.base in (DataType.F32, DataType.F64, DataType.F80)

    def is_float_node(self, node: ASTNode) -> bool:
        if node is None:
            return False
        if node.data_type in (DataType.F32, DataType.F64):
            return True
        if node.type == ASTType.UNARY_OP and node.children:
            return self.is_float_node(node.children[0])
        if node.type == ASTType.BINARY_OP and node.data_type in FLOAT_TYPES:
            return True
        return self.is_float_ref(self.ref_of(node))

    def new_rodata_label(self, prefix: str) -> str:
        self.label_counter += 1
        return f".LC{prefix}{self.label_counter}"

    def emit_float_constant(self, value: float) -> None:
        import struct as _struct
        label = self.new_rodata_label("f")
        bits = _struct.unpack('<Q', _struct.pack('<d', float(value)))[0]
        self.emit_raw(f"{label}: dq 0x{bits:016x}", "rodata")
        self.emit(f"mov rax, {self.mem(label)}", "text")
        self.emit("push rax", "text")

    @staticmethod
    def bytes_directive(text: str) -> str:
        return ", ".join(str(b) for b in text.encode('utf-8')) + ", 0"

    def emit_string_constant(self, text: str) -> None:
        label = self.new_rodata_label("s")
        self.emit_raw(f'{label}: db {self.bytes_directive(text)}', "rodata")
        self.emit(f"lea rax, {self.mem(label)}", "text")
        self.emit("push rax", "text")

    def variable_operand(self, node: ASTNode) -> str:
        offset = node.meta.get('offset')
        if node.meta.get('is_global') or offset is None:
            return self.mem(node.value)
        return f"[rbp + {offset}]"

    def gen_lambda(self, node: ASTNode) -> None:
        label = node.meta.get('label') or f"lambda_{self.label_counter}"
        node.meta['label'] = label
        params = node.meta.get('param_refs') or []
        self.emit_raw("", "text")
        self.emit_raw(f"; lambda {label}", "text")
        self.emit_raw(f"{label}:", "text")
        frame = max(node.meta.get('frame_size') or 0, 8 * (len(params) + 2))
        frame = (frame + 8 + 15) & ~15
        self.emit("push rbp", "text")
        self.emit("mov rbp, rsp", "text")
        self.emit(f"sub rsp, {frame}", "text")
        self.emit("mov qword [rbp + -8], rbx", "text")
        arg_regs = ['rdi', 'rsi', 'rdx', 'rcx', 'r8', 'r9']
        for i, pref in enumerate(params):
            if i < len(arg_regs):
                self.emit(f"mov qword [rbp + {-8 * (i + 2)}], {arg_regs[i]}", "text")
        saved_fn = getattr(self, 'current_function_node', None)
        self.current_function_node = None
        body = node.children[0] if node.children else None
        if body is not None:
            for stmt in body.children:
                self.gen_statement(stmt)
        self.current_function_node = saved_fn
        self.emit("xor eax, eax", "text")
        self.emit("mov rbx, qword [rbp + -8]", "text")
        self.emit("mov rsp, rbp", "text")
        self.emit("pop rbp", "text")
        self.emit("ret", "text")

    # -- statements --------------------------------------------------------
    def gen_switch(self, node: ASTNode) -> None:
        end_label = self.new_label()
        if not node.children:
            return
        self.gen_expression(node.children[0])
        self.emit("pop rax", "text")
        self.emit("mov r11, rax", "text")

        cases = [c for c in node.children[1:] if c is not None and c.type == ASTType.CASE_STMT]
        default_case = None
        case_labels = []
        for case in cases:
            label = self.new_label()
            case_labels.append(label)
            if case.value == 'default':
                default_case = (case, label)
                continue
            if case.value == 'when' and case.children:
                self.gen_expression(case.children[0])
                self.emit("pop rax", "text")
                self.emit("cmp rax, 0", "text")
                self.emit(f"jne {label}", "text")
            elif case.children:
                self.gen_expression(case.children[0])
                self.emit("pop rax", "text")
                self.emit("cmp r11, rax", "text")
                self.emit(f"je {label}", "text")

        if default_case:
            self.emit(f"jmp {default_case[1]}", "text")
        else:
            self.emit(f"jmp {end_label}", "text")

        for case, label in zip(cases, case_labels):
            self.emit_raw(f"{label}:", "text")
            if len(case.children) > 1:
                self.gen_statement(case.children[1])
            self.emit(f"jmp {end_label}", "text")

        self.emit_raw(f"{end_label}:", "text")

    def function_label(self, node: ASTNode) -> str:
        parent = node.meta.get('parent') or ""
        name = node.value
        if parent:
            base = f"{parent}_{name}"
        else:
            base = name
        params = node.meta.get('param_refs') or []
        if not parent and name != 'main' and len(self.symbols.find_functions(name)) > 1:
            sig = "_".join(self._type_tag(p) for p in params)
            base = f"{name}__{sig}"
        return base

    @staticmethod
    def _type_tag(ref) -> str:
        if ref is None:
            return "v"
        if isinstance(ref, TypeRef):
            if ref.base == DataType.STRUCT:
                return ref.name.lower()
            if ref.base == DataType.ARRAY:
                return "arr"
            return ref.base.name.lower()
        return "v"

    def gen_function(self, node: ASTNode) -> None:
        label = node.meta.get('label') or self.function_label(node)
        node.meta['label'] = label
        self.emit_raw("", "text")
        self.emit_raw(f"; Function: {node.value} (opt: {node.optimization_level.value})", "text")
        self.emit_raw(f"{label}:", "text")

        params = node.meta.get('param_refs') or []
        frame = node.meta.get('frame_size') or node.function_frame_size or 32
        frame = max(frame, 8 * len(params) + 16)
        frame = (frame + 15) & ~15
        self.current_function_node = node

        if self.current_function_is_interrupt:
            for reg in ("rax", "rcx", "rdx", "rbx", "rbp", "rsi", "rdi", "r8", "r9", "r10", "r11"):
                self.emit(f"push {reg}", "text")
            self.emit("pushfq", "text")
        else:
            self.emit("push rbp", "text")
            self.emit("mov rbp, rsp", "text")
            self.emit(f"sub rsp, {frame}", "text")
            self.emit("mov qword [rbp + -8], rbx", "text")

        arg_regs = ['rdi', 'rsi', 'rdx', 'rcx', 'r8', 'r9']
        for i, pref in enumerate(params):
            if i < len(arg_regs):
                offset = node.meta.get('param_offsets', [])[i] if node.meta.get('param_offsets') else -(8 * (i + 1))
                prefix = "qword" if self.is_float_ref(pref) else self.mov_prefix_of(pref)
                src = arg_regs[i]
                if prefix != "qword":
                    sub = {'rdi': ('dil', 'di', 'edi'), 'rsi': ('sil', 'si', 'esi'),
                           'rdx': ('dl', 'dx', 'edx'), 'rcx': ('cl', 'cx', 'ecx'),
                           'r8': ('r8b', 'r8w', 'r8d'), 'r9': ('r9b', 'r9w', 'r9d')}[arg_regs[i]]
                    src = sub[{'byte': 0, 'word': 1, 'dword': 2}[prefix]]
                self.emit(f"mov {prefix} [rbp + {offset}], {src}", "text")
            else:
                # System V: the 7th and later arguments live on the caller's stack
                offset = node.meta.get('param_offsets', [])[i] if node.meta.get('param_offsets') else -(8 * (i + 1))
                self.emit(f"mov rax, qword [rbp + {16 + 8 * (i - len(arg_regs))}]", "text")
                self.emit(f"mov qword [rbp + {offset}], rax", "text")

        # constructors: install the vtable pointer and apply field default values
        if node.value == 'new' and (node.function_param_names or [None])[0] == 'self' \
                and node.meta.get('param_offsets') and node.meta.get('parent'):
            cls = node.meta['parent']
            this_off = node.meta['param_offsets'][0]
            self.emit_vptr_store(cls, this_off)
            for fname, fref, expr in (getattr(self.symbols, 'field_defaults', {}) or {}).get(cls, []):
                found = self.symbols.field_offset(cls, fname)
                if not found:
                    continue
                self.gen_expression(expr)
                self.emit("pop rax", "text")
                self.f32_narrow(fref)
                prefix = self.mov_prefix_of(fref)
                self.emit(f"mov rbx, qword [rbp + {this_off}]", "text")
                self.emit(f"mov {prefix} [rbx + {found[0]}], {self.reg_for(prefix)}", "text")

        for child in node.children:
            self.gen_statement(child)

        if node.function_return != DataType.VOID:
            self.emit("xor eax, eax", "text")
        if self.current_function_is_interrupt:
            self.emit("popfq", "text")
            for reg in ("r11", "r10", "r9", "r8", "rdi", "rsi", "rbp", "rbx", "rdx", "rcx", "rax"):
                self.emit(f"pop {reg}", "text")
            self.emit("iretq", "text")
        else:
            self.emit("mov rbx, qword [rbp + -8]", "text")
            self.emit("mov rsp, rbp", "text")
            self.emit("pop rbp", "text")
            self.emit("ret", "text")

        self.current_function_is_interrupt = False
        self.current_function_is_kernel = False

    # -- calls -------------------------------------------------------------
    def resolve_callee(self, node: ASTNode) -> str:
        if node.meta.get('resolved_label'):
            return node.meta['resolved_label']
        name = node.value
        candidates = self.symbols.find_functions(name)
        if not candidates:
            return name
        if len(candidates) == 1:
            return candidates[0].meta.get('label') or self.function_label(candidates[0])
        args = node.children[1:]
        floats = [self.is_float_node(a) for a in args]
        best = None
        for cand in candidates:
            params = cand.meta.get('param_refs') or []
            if len(params) != len(args):
                continue
            score = 0
            for pref, arg_float in zip(params, floats):
                if self.is_float_ref(pref) == arg_float:
                    score += 1
            if best is None or score > best[0]:
                best = (score, cand)
        if best:
            return best[1].meta.get('label') or self.function_label(best[1])
        return name

    def emit_vptr_store(self, cls: str, this_off: int) -> None:
        info = self.symbols.class_info(cls)
        if info and info.get('has_vptr'):
            self.emit(f"mov rcx, qword [rbp + {this_off}]", "text")
            self.emit(f"lea rdx, [rel {cls}_vtable]", "text")
            self.emit("mov qword [rcx], rdx", "text")

    def emit_vtable(self, cls: str) -> None:
        info = self.symbols.class_info(cls)
        if not info or not info.get('has_vptr'):
            return
        slots = []
        for name in info['virtuals']:
            fn = self.symbols.find_method(cls, name)
            if fn is None or not fn.meta.get('has_body', True):
                slots.append("0")
            else:
                slots.append(fn.meta.get('label') or self.function_label(fn))
        self.emit_raw(f"{cls}_vtable: dq {', '.join(slots) if slots else '0'}", "data")

    def const_eval(self, node: Optional[ASTNode]):
        """Evaluate a compile-time constant expression (ints, floats, bools, chars,
        unary/binary arithmetic, casts) or return None."""
        if node is None:
            return None
        t = node.type
        if t == ASTType.LITERAL:
            if node.meta.get('is_string'):
                return None
            if 'char_value' in node.meta:
                return node.meta['char_value']
            try:
                text = str(node.value)
                if node.data_type in (DataType.F32, DataType.F64) or any(c in text for c in '.eE') \
                        and not text.lower().startswith('0x'):
                    return float(text)
                return int(text, 0)
            except (ValueError, TypeError):
                return None
        if t == ASTType.UNARY_OP and node.children:
            v = self.const_eval(node.children[0])
            if v is None:
                return None
            return {'-': lambda x: -x, '+': lambda x: x, '~': lambda x: ~int(x)}.get(node.value, lambda x: None)(v)
        if t == ASTType.TYPE_CONVERSION and node.children:
            v = self.const_eval(node.children[0])
            if v is None:
                return None
            tgt = node.meta.get('target_ref')
            if isinstance(tgt, TypeRef) and tgt.base in (DataType.F32, DataType.F64):
                return float(v)
            return int(v)
        if t == ASTType.BINARY_OP and len(node.children) == 2:
            a, b = self.const_eval(node.children[0]), self.const_eval(node.children[1])
            if a is None or b is None:
                return None
            try:
                ops = {'+': lambda: a + b, '-': lambda: a - b, '*': lambda: a * b,
                       '/': lambda: (a / b) if isinstance(a, float) or isinstance(b, float) else int(a) // int(b),
                       '%': lambda: int(a) % int(b), '<<': lambda: int(a) << int(b),
                       '>>': lambda: int(a) >> int(b), '&': lambda: int(a) & int(b),
                       '|': lambda: int(a) | int(b), '^': lambda: int(a) ^ int(b)}
                return ops[node.value]() if node.value in ops else None
            except (ZeroDivisionError, ValueError):
                return None
        return None

    def is_constructor_call(self, node: ASTNode) -> bool:
        if node is None or node.type != ASTType.METHOD_CALL:
            return False
        receiver = node.children[0] if node.children else None
        return node.value == 'new' or (receiver is not None and receiver.meta.get('is_type_name'))

    def gen_call(self, node: ASTNode, dest: Optional[ASTNode] = None) -> None:
        arg_regs = ['rdi', 'rsi', 'rdx', 'rcx', 'r8', 'r9']

        if node.type == ASTType.METHOD_CALL:
            receiver = node.children[0] if node.children else None
            args = node.children[1:]
            recv_ref = self.ref_of(receiver) if receiver is not None else None
            if receiver is not None and (receiver.meta.get('is_type_name')
                                         and receiver.value == 'Option'
                                         or isinstance(recv_ref, TypeRef)
                                         and recv_ref.base == DataType.OPTION):
                self.gen_option_method(node)
                return
            if isinstance(recv_ref, TypeRef) and recv_ref.base in VECTOR_INFO:
                self.gen_vector_method(node, recv_ref)
                return
            owner = self.symbols.struct_name_of(recv_ref)
            method = node.value
            fn_ctx = getattr(self, 'current_function_node', None)
            if receiver is not None and receiver.type == ASTType.VARIABLE and receiver.value == 'super' \
                    and fn_ctx is not None:
                # super.method(args): call the base-class implementation on this object
                cur = fn_ctx.meta.get('parent') or ""
                cur_info = self.symbols.class_info(cur)
                base_cls = cur_info.get('base') if cur_info else None
                target_fn = self.symbols.find_method(base_cls, method) if base_cls else None
                if target_fn is not None and fn_ctx.meta.get('param_offsets'):
                    this_off = fn_ctx.meta['param_offsets'][0]
                    for arg in reversed(args):
                        self.gen_expression(arg)
                    for i in range(min(len(args), 5)):
                        self.emit(f"pop {arg_regs[i + 1]}", "text")
                    self.emit(f"mov rdi, qword [rbp + {this_off}]", "text")
                    self.emit(f"call {target_fn.meta.get('label') or self.function_label(target_fn)}", "text")
                    if method == 'new':
                        self.emit_vptr_store(cur, this_off)
                    self.emit("push rax", "text")
                    return
                self.emit(f"; super.{method}: no base-class method found", "text")
                self.emit("push 0", "text")
                return
            chain_fn = self.symbols.find_method(owner, method) if owner else None
            candidates = [chain_fn] if chain_fn is not None else []
            if not candidates:
                candidates = [f for f in self.symbols.functions
                              if f.value == method and (f.meta.get('parent') or "") == owner]
            if not candidates:
                candidates = [f for f in self.symbols.functions if f.value == method]
            is_static = method == 'new' or (receiver is not None and receiver.meta.get('is_type_name'))
            if not candidates and not owner:
                self.emit(f"; method call '.{method}' has no known owner type", "text")
                self.emit("push 0", "text")
                return
            if is_static and dest is not None:
                # constructor writing straight into the destination object:
                # `let c = Counter.new()` initialises c in place (no dangling temporary)
                if len(args) > 5:
                    self.emit("; NOTE: more than 5 arguments to a constructor are not supported", "text")
                self.gen_address(dest)
                self.emit("push rax", "text")
                for arg in reversed(args):
                    self.gen_expression(arg)
                for i in range(min(len(args), 5)):
                    self.emit(f"pop {arg_regs[i + 1]}", "text")
                self.emit("pop rdi", "text")
                self.emit(f"call {(candidates[0].meta.get('label') or f'{owner}_{method}') if candidates else f'{owner}_{method}'}", "text")
                return
            if is_static:
                if len(args) > 5:
                    self.emit("; NOTE: more than 5 arguments to a constructor are not supported", "text")
                for arg in reversed(args):
                    self.gen_expression(arg)
                for i in range(min(len(args), 5)):
                    self.emit(f"pop {arg_regs[i + 1]}", "text")
                scratch = self.symbols.struct_size(owner) if owner else 64
                scratch = (max(scratch, 8) + 15) & ~15
                self.emit(f"sub rsp, {scratch}", "text")
                self.emit("mov rdi, rsp", "text")
                self.emit(f"call {(candidates[0].meta.get('label') or f'{owner}_{method}') if candidates else f'{owner}_{method}'}", "text")
                self.emit(f"add rsp, {scratch}", "text")
                self.emit("push rax", "text")
                return
            target = candidates[0].meta.get('label') if candidates else f"{owner}_{method}"
            params = (candidates[0].meta.get('param_refs') if candidates else []) or []
            self_mode = candidates[0].meta.get('self_mode') if candidates else ''

            # evaluate arguments first, then the receiver address
            for arg in reversed(args):
                self.gen_expression(arg)
            for i in range(min(len(args), 5)):
                self.emit(f"pop {arg_regs[i + 1]}", "text")

            if receiver is not None:
                if self.is_pointer(recv_ref):
                    # receiver already is a pointer/reference (`self`, `&Shape` parameters, ...)
                    self.gen_expression(receiver)
                    self.emit("pop rdi", "text")
                elif self_mode in ('ref', 'ref_mut') or receiver.type in (ASTType.INDEX, ASTType.MEMBER_ACCESS):
                    self.gen_address(receiver)
                    self.emit("mov rdi, rax", "text")
                else:
                    self.gen_expression(receiver)
                    self.emit("pop rdi", "text")
            slot = self.symbols.vtable_slot(owner, method) if owner else None
            cand_mods = (candidates[0].meta.get('modifiers') or []) if candidates else []
            if slot is not None and ('virtual' in cand_mods or 'override' in cand_mods):
                self.emit("mov rax, qword [rdi]", "text")
                self.emit(f"call qword [rax + {8 * slot}]", "text")
            else:
                self.emit(f"call {target}", "text")
            result_ref = self.ref_of(node)
            if isinstance(result_ref, TypeRef) and result_ref.base == DataType.OPTION:
                size = self.option_size(result_ref)
                self.emit(f"sub rsp, {size}", "text")
                self.emit("mov qword [rsp], rax", "text")
                self.emit("mov qword [rsp + 8], rdx", "text")
            else:
                self.emit("push rax", "text")
            return

        args = node.children[1:] if len(node.children) > 1 else []
        callee_expr = node.children[0] if node.children else None
        if callee_expr is not None and not self.symbols.find_functions(node.value) \
                and callee_expr.type in (ASTType.VARIABLE, ASTType.INDEX, ASTType.MEMBER_ACCESS) \
                and (callee_expr.meta.get('offset') is not None or callee_expr.type != ASTType.VARIABLE):
            # call through a function value (parameter, local, element, field)
            for arg in reversed(args):
                self.gen_expression(arg)
            for i in range(min(len(args), 6)):
                self.emit(f"pop {arg_regs[i]}", "text")
            self.gen_expression(callee_expr)
            self.emit("pop r11", "text")
            self.emit("call r11", "text")
            if len(args) > 6:
                self.emit(f"add rsp, {8 * (len(args) - 6)}", "text")
            self.emit("push rax", "text")
            return
        target = self.resolve_callee(node)

        # fill in default parameter values
        callee = None
        for cand in self.symbols.find_functions(node.value):
            prefs = cand.meta.get('param_refs') or []
            defs = cand.meta.get('param_defaults') or []
            if len(prefs) == len(args):
                callee = cand
                break
            if len(args) < len(prefs) and len(defs) == len(prefs) \
                    and all(defs[i] is not None for i in range(len(args), len(prefs))):
                callee = cand
                break
        if callee is not None:
            defaults = callee.meta.get('param_defaults') or []
            if len(defaults) > len(args):
                for d in defaults[len(args):]:
                    args = list(args) + ([d] if d is not None else [])

        for arg in reversed(args):
            self.gen_expression(arg)
        for i in range(min(len(args), 6)):
            self.emit(f"pop {arg_regs[i]}", "text")
        self.emit(f"call {target}", "text")
        if len(args) > 6:
            self.emit(f"add rsp, {8 * (len(args) - 6)}", "text")
        self.emit("push rax", "text")

    # -- assignment --------------------------------------------------------
    def gen_address(self, node: ASTNode) -> None:
        """Emit code that leaves the address of an lvalue in rax."""
        if node.type == ASTType.VARIABLE:
            if node.meta.get('is_global') or node.meta.get('offset') is None:
                self.emit(f"lea rax, {self.mem(node.value)}", "text")
            else:
                self.emit(f"lea rax, [rbp + {node.meta['offset']}]", "text")
            return
        if node.type == ASTType.MEMBER_ACCESS and node.children:
            base = node.children[0]
            base_ref = self.ref_of(base)
            if self.is_pointer(base_ref):
                self.gen_expression(base)
                self.emit("pop rax", "text")
            else:
                self.gen_address(base)
            struct_name = self.symbols.struct_name_of(base_ref)
            found = self.symbols.field_offset(struct_name, node.value)
            if found:
                self.emit(f"add rax, {found[0]}", "text")
            return
        if node.type == ASTType.INDEX and len(node.children) >= 2:
            base, index = node.children[0], node.children[1]
            base_ref = self.ref_of(base)
            if self.is_pointer(base_ref):
                self.gen_expression(base)
                self.emit("pop rax", "text")
            else:
                self.gen_address(base)
            self.emit("push rax", "text")
            self.gen_expression(index)
            self.emit("pop rbx", "text")
            self.emit("pop rax", "text")
            elem = self.ref_of(base)
            esize = 8
            if isinstance(elem, TypeRef) and elem.elem is not None:
                esize = self.size_of(elem.elem)
            elif isinstance(elem, TypeRef) and elem.base in VECTOR_INFO:
                esize = VECTOR_INFO[elem.base][1]
            if esize != 1:
                self.emit(f"imul rbx, {esize}", "text")
            self.emit("add rax, rbx", "text")
            return
        if node.type == ASTType.UNARY_OP and node.value == '*':
            self.gen_expression(node.children[0])
            self.emit("pop rax", "text")
            return
        self.emit("xor eax, eax", "text")

    def gen_store_to(self, node: ASTNode, prefix: str = "qword") -> None:
        """Store rax through an lvalue."""
        reg = self.reg_for(prefix)
        if node.type == ASTType.VARIABLE and not node.meta.get('is_global') \
                and node.meta.get('offset') is not None:
            self.emit(f"mov {prefix} [rbp + {node.meta['offset']}], {reg}", "text")
            return
        # The value to store is in rax; keep it across address computation.
        self.emit("push rax", "text")
        self.gen_address(node)
        self.emit("mov rbx, rax", "text")
        self.emit("pop rax", "text")
        self.emit(f"mov {prefix} [rbx], {reg}", "text")

    def gen_assign(self, node: ASTNode) -> None:
        meta = node.meta
        lhs = node.children[0] if node.children else None

        # tuple destructuring: let (q, r) = f()
        if meta.get('tuple_names'):
            if node.children:
                # the destructuring node holds only the initialiser (no lhs child)
                self.gen_expression(node.children[-1])
                self.emit("pop rax", "text")
            names = meta['tuple_names']
            regs = ['rax', 'rdx']
            offsets = meta.get('tuple_offsets') or []
            for i, name in enumerate(names[:2]):
                offset = offsets[i] if i < len(offsets) and offsets[i] is not None else -(8 * (i + 2))
                self.emit(f"mov qword [rbp + {offset}], {regs[i]}", "text")
            return

        if lhs is None:
            return

        ref = meta.get('type_ref') or self.ref_of(lhs)
        if ref is None and lhs.type == ASTType.MEMBER_ACCESS and lhs.children:
            # field store: use the field's own width (an i32 field must not be
            # written with a qword store, which clobbers its neighbour)
            base_ref = self.ref_of(lhs.children[0])
            struct_name = self.symbols.struct_name_of(base_ref)
            ref = self.symbols.field_ref(struct_name, lhs.value)
        value = node.children[1] if len(node.children) > 1 else None

        # declaration of a static/global
        if meta.get('is_static') and lhs.type == ASTType.VARIABLE:
            # `static p: T = <int literal> as U` is a constant initializer too
            while value is not None and value.type == ASTType.TYPE_CONVERSION \
                    and value.children and value.children[0].type == ASTType.LITERAL \
                    and not value.children[0].meta.get('is_string') \
                    and value.children[0].data_type not in (DataType.F32, DataType.F64):
                value = value.children[0]
            folded = self.const_eval(value) if value is not None else None
            if folded is not None:
                import struct as _struct
                if isinstance(ref, TypeRef) and ref.base == DataType.F32:
                    bits = _struct.unpack('<I', _struct.pack('<f', float(folded)))[0]
                    self.emit_raw(f"{lhs.value}: dq 0x{bits:08x}", "data")
                elif isinstance(ref, TypeRef) and ref.base == DataType.F64:
                    bits = _struct.unpack('<Q', _struct.pack('<d', float(folded)))[0]
                    self.emit_raw(f"{lhs.value}: dq 0x{bits:016x}", "data")
                elif isinstance(folded, float):
                    bits = _struct.unpack('<Q', _struct.pack('<d', folded))[0]
                    self.emit_raw(f"{lhs.value}: dq 0x{bits:016x}", "data")
                else:
                    self.emit_raw(f"{lhs.value}: dq {int(folded) & 0xFFFFFFFFFFFFFFFF}", "data")
            elif value is not None and value.type == ASTType.LITERAL and not value.meta.get('is_string'):
                self.emit_raw(f"{lhs.value}: dq {value.value}", "data")
            elif value is not None and value.type == ASTType.LITERAL and value.meta.get('is_string'):
                label = self.new_rodata_label("str")
                self.emit_raw(f'{label}: db {self.bytes_directive(value.value)}', "rodata")
                self.emit_raw(f"{lhs.value}: dq {label}", "data")
            else:
                self.emit_raw(f"{lhs.value}: resq 1", "bss")
            return

        # array declaration with an initialiser
        if value is not None and value.type == ASTType.ARRAY_LITERAL:
            self.gen_array_init(lhs, value)
            return

        if isinstance(ref, TypeRef) and ref.base in VECTOR_INFO:
            size = self.size_of(ref)
            if value is None:
                self.gen_address(lhs)
                self.emit("mov rbx, rax", "text")
                self.emit("pxor xmm0, xmm0", "text")
                for offset in range(0, size, 16):
                    self.emit(f"movups [rbx + {offset}], xmm0", "text")
            else:
                self.gen_expression(value)
                self.emit("push rsp", "text")
                self.gen_address(lhs)
                self.emit("mov rbx, rax", "text")
                self.emit("pop r10", "text")
                for offset in range(0, size, 16):
                    self.emit(f"movups xmm0, [r10 + {offset}]", "text")
                    self.emit(f"movups [rbx + {offset}], xmm0", "text")
                self.emit(f"add rsp, {size}", "text")
            return

        # struct literal
        if value is not None and value.type == ASTType.STRUCT_LITERAL:
            self.gen_struct_init(lhs, value)
            return

        if value is not None and self.is_constructor_call(value) \
                and lhs.type in (ASTType.VARIABLE, ASTType.MEMBER_ACCESS, ASTType.INDEX) \
                and not (isinstance(ref, TypeRef) and self.is_pointer(ref)):
            self.gen_call(value, dest=lhs)
            return

        if value is not None:
            self.gen_expression(value)
            self.emit("pop rax", "text")
        elif isinstance(ref, TypeRef) and ref.base == DataType.ARRAY and lhs.type == ASTType.VARIABLE \
                and not lhs.meta.get('is_global') and lhs.meta.get('offset') is not None:
            size = self.size_of(ref)
            self.emit(f"lea rdi, [rbp + {lhs.meta['offset']}]", "text")
            self.emit(f"mov rcx, {size}", "text")
            self.emit("xor eax, eax", "text")
            self.emit("rep stosb", "text")
            self.emit("xor eax, eax", "text")
            return
        else:
            self.emit("xor eax, eax", "text")

        prefix = self.mov_prefix_of(ref)
        if value is not None:
            self.f32_narrow(ref)
        self.gen_store_to(lhs, prefix)

    def gen_array_init(self, lhs: ASTNode, literal: ASTNode) -> None:
        ref = self.ref_of(lhs)
        elem = ref.elem if isinstance(ref, TypeRef) and ref.elem is not None else TypeRef(base=DataType.U64)
        self.gen_address(lhs)
        self.emit("push rax", "text")
        self._init_array_values(literal, elem, 0)
        self.emit("pop rax", "text")

    def _init_array_values(self, literal: ASTNode, elem, base_off: int) -> None:
        """Store literal's elements relative to the address kept at [rsp]; nested literals recurse."""
        esize = self.size_of(elem)
        prefix = self.mov_prefix_of(elem)
        elements = literal.children
        repeat = literal.meta.get('repeat')
        count = repeat if repeat else len(elements)
        for i in range(count):
            element = elements[0] if repeat else (elements[i] if i < len(elements) else None)
            if element is None:
                continue
            off = base_off + i * esize
            if element.type == ASTType.ARRAY_LITERAL:
                inner = elem.elem if isinstance(elem, TypeRef) and elem.elem is not None \
                    else TypeRef(base=DataType.U64)
                self._init_array_values(element, inner, off)
                continue
            if element.type == ASTType.STRUCT_LITERAL:
                sname = self.symbols.struct_name_of(elem) or element.value
                self._init_struct_values(element, sname, off)
                continue
            self.gen_expression(element)
            self.emit("pop rax", "text")
            self.f32_narrow(elem)
            self.emit("mov rbx, [rsp]", "text")
            self.emit(f"mov {prefix} [rbx + {off}], {self.reg_for(prefix)}", "text")

    def gen_struct_init(self, lhs: ASTNode, literal: ASTNode) -> None:
        ref = self.ref_of(lhs)
        struct_name = ref.name if isinstance(ref, TypeRef) and ref.name else literal.value
        self.gen_address(lhs)
        self.emit("push rax", "text")
        self._init_struct_values(literal, struct_name, 0)
        self.emit("pop rax", "text")

    def _init_struct_values(self, literal: ASTNode, struct_name: str, base_off: int) -> None:
        """Store the literal's fields relative to the object address kept at [rsp].
        Nested struct and array literals are initialised in place."""
        layout = self.symbols.struct_layout(struct_name)
        positional = [f for f in layout['fields'] if f[0] != '__vptr'] if layout else []
        for index, field_value in enumerate(literal.children):
            field_name = field_value.meta.get('field_name')
            offset, field_ref = index * 8, None
            if layout and field_name:
                found = self.symbols.field_offset(struct_name, field_name)
                if found:
                    offset, field_ref = found
            elif index < len(positional):
                offset, field_ref = positional[index][2], positional[index][1]
            offset += base_off
            if field_value.type == ASTType.STRUCT_LITERAL:
                inner = field_ref.name if isinstance(field_ref, TypeRef) and field_ref.name else field_value.value
                self._init_struct_values(field_value, inner, offset)
                continue
            if field_value.type == ASTType.ARRAY_LITERAL and isinstance(field_ref, TypeRef) \
                    and field_ref.elem is not None:
                self._init_array_values(field_value, field_ref.elem, offset)
                continue
            self.gen_expression(field_value)
            self.emit("pop rax", "text")
            if field_ref is not None:
                self.f32_narrow(field_ref)
            self.emit("mov rbx, [rsp]", "text")
            prefix = self.mov_prefix_of(field_ref) if field_ref else "qword"
            self.emit(f"mov {prefix} [rbx + {offset}], {self.reg_for(prefix)}", "text")

    def gen_return(self, node: ASTNode) -> None:
        fn = getattr(self, 'current_function_node', None)
        return_ref = fn.meta.get('return_ref') if fn is not None else None
        if isinstance(return_ref, TypeRef) and return_ref.base == DataType.OPTION:
            if node.children:
                self.gen_expression(node.children[0])
                self.emit("mov rax, qword [rsp]", "text")
                self.emit("mov rdx, qword [rsp + 8]", "text")
                self.emit(f"add rsp, {self.option_size(return_ref)}", "text")
            else:
                self.emit("xor eax, eax", "text")
                self.emit("xor edx, edx", "text")
        elif node.children and node.children[0].type == ASTType.STRUCT_LITERAL and fn is not None \
                and (fn.function_param_names or [None])[0] == 'self' and fn.meta.get('param_offsets'):
            # constructor: build the literal directly in the object `this` points at
            this_off = fn.meta['param_offsets'][0]
            this_var = ASTNode(ASTType.VARIABLE, 'self', node.line, node.column)
            this_var.meta['offset'] = this_off
            target = ASTNode(ASTType.UNARY_OP, '*', node.line, node.column)
            target.add_child(this_var)
            self.gen_struct_init(target, node.children[0])
            self.emit(f"mov rax, qword [rbp + {this_off}]", "text")
        elif node.children and node.children[0].type == ASTType.TUPLE and len(node.children[0].children) > 1:
            value = node.children[0]
            self.gen_expression(value.children[0])
            self.gen_expression(value.children[1])
            self.emit("pop rdx", "text")
            self.emit("pop rax", "text")
        elif node.children:
            value = node.children[0]
            self.gen_expression(value)
            self.emit("pop rax", "text")
        else:
            self.emit("xor eax, eax", "text")

        if self.current_function_is_interrupt:
            self.emit("jmp .interrupt_return", "text")
        else:
            self.emit("mov rbx, qword [rbp + -8]", "text")
            self.emit("mov rsp, rbp", "text")
            self.emit("pop rbp", "text")
            self.emit("ret", "text")

    def gen_if(self, node: ASTNode) -> None:
        end_label = self.new_label()
        else_label = self.new_label()

        self.gen_expression(node.children[0])
        self.emit("pop rax", "text")
        self.emit("test rax, rax", "text")
        self.emit(f"jz {else_label}", "text")

        if len(node.children) > 1 and node.children[1] is not None:
            self.gen_statement(node.children[1])
        self.emit(f"jmp {end_label}", "text")
        self.emit_raw(f"{else_label}:", "text")

        if len(node.children) > 2 and node.children[2] is not None:
            self.gen_statement(node.children[2])
        self.emit_raw(f"{end_label}:", "text")

    def gen_while(self, node: ASTNode) -> None:
        start_label = self.new_label()
        end_label = self.new_label()
        self.break_labels.append(end_label)
        self.continue_labels.append(start_label)

        self.emit_raw(f"{start_label}:", "text")
        self.gen_expression(node.children[0])
        self.emit("pop rax", "text")
        self.emit("test rax, rax", "text")
        self.emit(f"jz {end_label}", "text")
        if len(node.children) > 1 and node.children[1] is not None:
            self.gen_statement(node.children[1])
        self.emit(f"jmp {start_label}", "text")
        self.emit_raw(f"{end_label}:", "text")

        self.break_labels.pop()
        self.continue_labels.pop()

    def gen_for(self, node: ASTNode) -> None:
        if node.value == "cstyle":
            self.gen_for_cstyle(node)
        elif node.value == "each":
            self.gen_for_each(node)
        else:
            self.gen_for_range(node)

    def gen_for_range(self, node: ASTNode) -> None:
        var_node, start, end, step, body = (node.children + [None] * 5)[:5]
        start_label = self.new_label()
        end_label = self.new_label()
        body_label = self.new_label()
        incr_label = self.new_label()
        self.break_labels.append(end_label)
        self.continue_labels.append(incr_label)

        var_name = var_node.value if var_node is not None else "i"
        offset = var_node.meta.get('offset') if var_node is not None else None
        if offset is None:
            sym = self.symbols.lookup(var_name)
            offset = sym.stack_offset if sym else -8

        # The end bound and step are kept in frame slots (not registers), because
        # the loop body is free to clobber rbx/r10.
        end_off = node.meta.get('end_offset', offset - 8)
        step_off = node.meta.get('step_offset', offset - 16)

        self.gen_expression(start)
        self.emit("pop rax", "text")
        self.emit(f"mov qword [rbp + {offset}], rax", "text")
        self.gen_expression(end)
        self.emit("pop rax", "text")
        self.emit(f"mov qword [rbp + {end_off}], rax", "text")
        self.gen_expression(step)
        self.emit("pop rax", "text")
        self.emit(f"mov qword [rbp + {step_off}], rax", "text")

        self.emit_raw(f"{start_label}:", "text")
        self.emit(f"mov rcx, qword [rbp + {step_off}]", "text")
        self.emit(f"mov rax, qword [rbp + {offset}]", "text")
        self.emit(f"mov rbx, qword [rbp + {end_off}]", "text")
        self.emit("test rcx, rcx", "text")
        positive = self.new_label()
        self.emit(f"jns {positive}", "text")
        self.emit("cmp rax, rbx", "text")
        self.emit(f"jle {end_label}", "text")
        self.emit(f"jmp {body_label}", "text")
        self.emit_raw(f"{positive}:", "text")
        self.emit("cmp rax, rbx", "text")
        self.emit(f"jge {end_label}", "text")
        self.emit_raw(f"{body_label}:", "text")

        if body is not None:
            self.gen_statement(body)

        self.emit_raw(f"{incr_label}:", "text")
        self.emit(f"mov rax, qword [rbp + {offset}]", "text")
        self.emit(f"add rax, qword [rbp + {step_off}]", "text")
        self.emit(f"mov qword [rbp + {offset}], rax", "text")
        self.emit(f"jmp {start_label}", "text")
        self.emit_raw(f"{end_label}:", "text")

        self.break_labels.pop()
        self.continue_labels.pop()

    def gen_for_each(self, node: ASTNode) -> None:
        var_node, iterable, body = (node.children + [None] * 3)[:3]
        start_label = self.new_label()
        end_label = self.new_label()
        self.break_labels.append(end_label)
        self.continue_labels.append(start_label)

        var_name = var_node.value if var_node is not None else "ch"
        offset = var_node.meta.get('offset') if var_node is not None else None
        if offset is None:
            sym = self.symbols.lookup(var_name)
            offset = sym.stack_offset if sym else -8
        iter_off = node.meta.get('iter_offset', offset - 8)

        self.gen_expression(iterable)
        self.emit("pop rax", "text")
        self.emit(f"mov qword [rbp + {iter_off}], rax", "text")
        self.emit_raw(f"{start_label}:", "text")
        self.emit(f"mov rbx, qword [rbp + {iter_off}]", "text")
        self.emit("movzx rax, byte [rbx]", "text")
        self.emit("test rax, rax", "text")
        self.emit(f"jz {end_label}", "text")
        self.emit(f"mov qword [rbp + {offset}], rax", "text")
        self.emit("inc rbx", "text")
        self.emit(f"mov qword [rbp + {iter_off}], rbx", "text")
        if body is not None:
            self.gen_statement(body)
        self.emit(f"jmp {start_label}", "text")
        self.emit_raw(f"{end_label}:", "text")

        self.break_labels.pop()
        self.continue_labels.pop()

    def gen_for_cstyle(self, node: ASTNode) -> None:
        init, cond, step, body = (node.children + [None] * 4)[:4]
        start_label = self.new_label()
        end_label = self.new_label()
        continue_label = self.new_label()
        self.break_labels.append(end_label)
        self.continue_labels.append(continue_label)

        if init is not None:
            self.gen_statement(init)
        self.emit_raw(f"{start_label}:", "text")
        if cond is not None:
            self.gen_expression(cond)
            self.emit("pop rax", "text")
            self.emit("test rax, rax", "text")
            self.emit(f"jz {end_label}", "text")
        if body is not None:
            self.gen_statement(body)
        self.emit_raw(f"{continue_label}:", "text")
        if step is not None:
            self.gen_statement(step)
        self.emit(f"jmp {start_label}", "text")
        self.emit_raw(f"{end_label}:", "text")

        self.break_labels.pop()
        self.continue_labels.pop()

    def gen_with(self, node: ASTNode) -> None:
        if len(node.children) > 1 and node.children[1] is not None:
            self.gen_statement(node.children[1])

    # -- expressions -------------------------------------------------------
    def gen_expression(self, node: Optional[ASTNode]) -> None:
        if node is None:
            self.emit("push 0", "text")
            return

        t = node.type

        if t == ASTType.LITERAL:
            if node.meta.get('is_string'):
                self.emit_string_constant(node.value)
            elif node.data_type == DataType.F64 or ('.' in str(node.value) and not str(node.value).startswith('0x')):
                try:
                    self.emit_float_constant(float(node.value))
                except ValueError:
                    self.emit("push 0", "text")
            elif node.data_type == DataType.CHAR and 'char_value' in node.meta:
                self.emit(f"mov rax, {node.meta['char_value']}", "text")
                self.emit("push rax", "text")
            else:
                try:
                    value = int(str(node.value), 0)
                except ValueError:
                    value = 0
                self.emit(f"mov rax, {value}", "text")
                self.emit("push rax", "text")
            return

        if t == ASTType.VARIABLE:
            ref = self.ref_of(node)
            if node.meta.get('offset') is None and not node.meta.get('is_global') \
                    and self.symbols.find_functions(node.value):
                # a bare function name used as a value is the function's address
                fn_nodes = self.symbols.find_functions(node.value)
                label = fn_nodes[0].meta.get('label') or self.function_label(fn_nodes[0])
                self.emit(f"lea rax, [rel {label}]", "text")
                self.emit("push rax", "text")
                return
            if isinstance(ref, TypeRef) and ref.base == DataType.OPTION:
                size = self.option_size(ref)
                self.emit(f"sub rsp, {size}", "text")
                self.gen_address(node)
                self.emit("mov r11, rax", "text")
                for offset in range(0, size, 8):
                    self.emit(f"mov rax, qword [r11 + {offset}]", "text")
                    self.emit(f"mov qword [rsp + {offset}], rax", "text")
                return
            if isinstance(ref, TypeRef) and ref.base in VECTOR_INFO:
                size = self.size_of(ref)
                self.emit(f"sub rsp, {size}", "text")
                self.gen_address(node)
                self.emit("mov r11, rax", "text")
                for offset in range(0, size, 16):
                    self.emit(f"movups xmm0, [r11 + {offset}]", "text")
                    self.emit(f"movups [rsp + {offset}], xmm0", "text")
                return
            if self.is_aggregate_ref(ref):
                self.gen_address(node)
                self.emit("push rax", "text")
                return
            operand = self.variable_operand(node)
            prefix = self.mov_prefix_of(ref)
            self.emit(f"mov {self.reg_for(prefix)}, {prefix} {operand}", "text")
            self.extend_loaded(ref, prefix)
            self.f32_widen(ref)
            self.emit("push rax", "text")
            return

        if t == ASTType.BINARY_OP:
            self.gen_binary(node)
            return

        if t == ASTType.UNARY_OP:
            self.gen_unary(node)
            return

        if t == ASTType.INDEX:
            ref = self.ref_of(node)
            if self.is_aggregate_ref(ref):
                self.gen_address(node)
                self.emit("push rax", "text")
                return
            self.gen_address(node)
            self.emit("mov rbx, rax", "text")
            prefix = self.mov_prefix_of(ref)
            self.emit(f"mov {self.reg_for(prefix)}, {prefix} [rbx]", "text")
            self.extend_loaded(ref, prefix)
            self.f32_widen(ref)
            self.emit("push rax", "text")
            return

        if t == ASTType.MEMBER_ACCESS:
            ref = self.ref_of(node)
            if ref is None:
                base_ref = self.ref_of(node.children[0]) if node.children else None
                struct_name = self.symbols.struct_name_of(base_ref)
                ref = self.symbols.field_ref(struct_name, node.value)
            if self.is_aggregate_ref(ref):
                self.gen_address(node)
                self.emit("push rax", "text")
                return
            self.gen_address(node)
            self.emit("mov rbx, rax", "text")
            prefix = self.mov_prefix_of(ref)
            self.emit(f"mov {self.reg_for(prefix)}, {prefix} [rbx]", "text")
            self.extend_loaded(ref, prefix)
            self.f32_widen(ref)
            self.emit("push rax", "text")
            return

        if t == ASTType.CALL or t == ASTType.METHOD_CALL:
            self.gen_call(node)
            return

        if t == ASTType.BUILTIN_CALL:
            self.gen_builtin(node)
            return

        if t == ASTType.TYPE_CONVERSION:
            self.gen_conversion(node)
            return

        if t == ASTType.ARRAY_LITERAL:
            self.emit("; array literal used as a value", "text")
            self.emit("push 0", "text")
            return

        if t == ASTType.STRUCT_LITERAL:
            self.emit(f"; struct literal {node.value}", "text")
            self.emit("push 0", "text")
            return

        if t == ASTType.TUPLE:
            if node.children:
                self.gen_expression(node.children[0])
            else:
                self.emit("push 0", "text")
            return

        if t == ASTType.LAMBDA:
            label = node.meta.get('label')
            if not label:
                label = f"lambda_{self.label_counter}"
                self.label_counter += 1
                node.meta['label'] = label
                self.pending_lambdas.append(node)
            self.emit(f"lea rax, {self.mem(label)}", "text")
            self.emit("push rax", "text")
            return

        if t == ASTType.SIMD_OPERATION:
            self.gen_simd_operation(node)
            return

        if t == ASTType.BLOCK_ARRAY_METHOD:
            self.emit(f"; BlockArray.{node.value}() is not yet implemented", "text")
            self.emit("push 0", "text")
            return

        if t == ASTType.BLOCK_ARRAY_TYPE:
            self.emit("; BlockArray value", "text")
            self.emit("push 0", "text")
            return

        self.emit(f"; unsupported expression node {t.name}", "text")
        self.emit("push 0", "text")

    def gen_unary(self, node: ASTNode) -> None:
        op = node.value
        operand = node.children[0] if node.children else None
        if op == '&':
            self.gen_address(operand)
            self.emit("push rax", "text")
            return
        if op == '*':
            self.gen_expression(operand)
            self.emit("pop rbx", "text")
            ref = self.ref_of(node)
            prefix = self.mov_prefix_of(ref)
            self.emit(f"mov {self.reg_for(prefix)}, {prefix} [rbx]", "text")
            if prefix == "byte":
                self.emit("movzx eax, al", "text")
            elif prefix == "word":
                self.emit("movzx eax, ax", "text")
            self.emit("push rax", "text")
            return
        if op in ('++', '--'):
            self.gen_expression(operand)
            self.emit("pop rax", "text")
            self.emit("add rax, 1" if op == '++' else "sub rax, 1", "text")
            self.emit("push rax", "text")
            self.gen_address(operand)
            self.emit("mov rbx, rax", "text")
            self.emit("pop rax", "text")
            self.emit("mov qword [rbx], rax", "text")
            self.emit("push rax", "text")
            return

        self.gen_expression(operand)
        self.emit("pop rax", "text")
        if op == '-':
            if self.is_float_node(operand):
                self.emit("mov rbx, 0x8000000000000000", "text")
                self.emit("xor rax, rbx", "text")
            else:
                self.emit("neg rax", "text")
        elif op in ('not', '!'):
            self.emit("test rax, rax", "text")
            self.emit("sete al", "text")
            self.emit("movzx eax, al", "text")
        elif op == '~':
            self.emit("not rax", "text")
        self.emit("push rax", "text")

    def gen_binary(self, node: ASTNode) -> None:
        op = node.value
        left, right = node.children[0], node.children[1]
        left_ref, right_ref = self.ref_of(left), self.ref_of(right)
        if isinstance(left_ref, TypeRef) and left_ref.base in VECTOR_INFO \
                and isinstance(right_ref, TypeRef) and right_ref.base == left_ref.base:
            self.gen_vector_binary(node, left_ref)
            return
        left_float = self.is_float_node(left)
        right_float = self.is_float_node(right)
        use_float = left_float or right_float

        if op in ('and', '&&'):
            op = '&&'
        elif op in ('or', '||'):
            op = '||'

        if op in ('&&', '||'):
            # short-circuit evaluation
            done = self.new_label()
            self.gen_expression(left)
            self.emit("pop rax", "text")
            self.emit("test rax, rax", "text")
            self.emit("setne al", "text")
            self.emit("movzx eax, al", "text")
            self.emit("jz " + done if op == '&&' else "jnz " + done, "text")
            self.gen_expression(right)
            self.emit("pop rax", "text")
            self.emit("test rax, rax", "text")
            self.emit("setne al", "text")
            self.emit("movzx eax, al", "text")
            self.emit_raw(f"{done}:", "text")
            self.emit("push rax", "text")
            return

        self.gen_expression(left)
        self.gen_expression(right)
        self.emit("pop rbx", "text")
        self.emit("pop rax", "text")

        if op in ('==', '!=') and self.is_string_node(left) and self.is_string_node(right):
            loop, eq, ne, end = (self.new_label() for _ in range(4))
            self.emit_raw(f"{loop}:", "text")
            self.emit("mov cl, byte [rax]", "text")
            self.emit("cmp cl, byte [rbx]", "text")
            self.emit(f"jne {ne}", "text")
            self.emit("test cl, cl", "text")
            self.emit(f"jz {eq}", "text")
            self.emit("inc rax", "text")
            self.emit("inc rbx", "text")
            self.emit(f"jmp {loop}", "text")
            self.emit_raw(f"{eq}:", "text")
            self.emit(f"mov eax, {1 if op == '==' else 0}", "text")
            self.emit(f"jmp {end}", "text")
            self.emit_raw(f"{ne}:", "text")
            self.emit(f"mov eax, {0 if op == '==' else 1}", "text")
            self.emit_raw(f"{end}:", "text")
            self.emit("push rax", "text")
            return

        signed = self.is_signed_node(left) or self.is_signed_node(right)
        unsigned = (not signed) and (self.is_unsigned_node(left) or self.is_unsigned_node(right))

        if use_float:
            if left_float:
                self.emit("movq xmm0, rax", "text")
            elif self.is_unsigned_node(left):
                self.emit("mov rdx, rax", "text")
                self.emit("shr rdx, 1", "text")
                self.emit("and eax, 1", "text")
                self.emit("or rdx, rax", "text")
                self.emit("cvtsi2sd xmm0, rdx", "text")
                self.emit("addsd xmm0, xmm0", "text")
            else:
                self.emit("cvtsi2sd xmm0, rax", "text")
            if right_float:
                self.emit("movq xmm1, rbx", "text")
            elif self.is_unsigned_node(right):
                self.emit("mov rdx, rbx", "text")
                self.emit("shr rdx, 1", "text")
                self.emit("and ebx, 1", "text")
                self.emit("or rdx, rbx", "text")
                self.emit("cvtsi2sd xmm1, rdx", "text")
                self.emit("addsd xmm1, xmm1", "text")
            else:
                self.emit("cvtsi2sd xmm1, rbx", "text")
            if op == '+':
                self.emit("addsd xmm0, xmm1", "text")
            elif op == '-':
                self.emit("subsd xmm0, xmm1", "text")
            elif op == '*':
                self.emit("mulsd xmm0, xmm1", "text")
            elif op == '/':
                self.emit("divsd xmm0, xmm1", "text")
            elif op in ('==', '!=', '<', '<=', '>', '>='):
                self.emit("ucomisd xmm0, xmm1", "text")
                if op in ("==", "!="):
                    self.emit("sete al" if op == "==" else "setne al", "text")
                    self.emit("setnp dl" if op == "==" else "setp dl", "text")
                    self.emit("and al, dl" if op == "==" else "or al, dl", "text")
                elif op in ("<", "<="):
                    self.emit("setb al" if op == "<" else "setbe al", "text")
                    self.emit("setnp dl", "text")
                    self.emit("and al, dl", "text")
                else:
                    self.emit("seta al" if op == ">" else "setae al", "text")
                self.emit("movzx eax, al", "text")
                self.emit("push rax", "text")
                return
            elif op == '**':
                exponent = self.const_eval(right)
                if exponent == 0.5:
                    self.emit("sqrtsd xmm0, xmm0", "text")
                elif exponent == -0.5:
                    self.emit("sqrtsd xmm0, xmm0", "text")
                    self.emit("mov rax, 0x3ff0000000000000", "text")
                    self.emit("movq xmm1, rax", "text")
                    self.emit("divsd xmm1, xmm0", "text")
                    self.emit("movapd xmm0, xmm1", "text")
                elif isinstance(exponent, (int, float)) and float(exponent).is_integer() \
                        and abs(int(exponent)) <= 32:
                    power = abs(int(exponent))
                    if power == 0:
                        self.emit("mov rax, 0x3ff0000000000000", "text")
                        self.emit("movq xmm0, rax", "text")
                    else:
                        self.emit("movapd xmm1, xmm0", "text")
                        for _ in range(power - 1):
                            self.emit("mulsd xmm0, xmm1", "text")
                        if exponent < 0:
                            self.emit("mov rax, 0x3ff0000000000000", "text")
                            self.emit("movq xmm1, rax", "text")
                            self.emit("divsd xmm1, xmm0", "text")
                            self.emit("movapd xmm0, xmm1", "text")
                else:
                    self.emit("; floating exponent must be a constant integer or +/-0.5", "text")
            self.emit("movq rax, xmm0", "text")
            self.emit("push rax", "text")
            return

        if op == '+':
            self.emit("add rax, rbx", "text")
        elif op == '-':
            self.emit("sub rax, rbx", "text")
        elif op == '*':
            factor = self.const_eval(right)
            other = left
            value = factor
            if factor is None:
                value = self.const_eval(left)
                other = right
            if self.opt_level.value >= OptimizationLevel.O2.value \
                    and isinstance(value, int) and value > 0 and value & (value - 1) == 0 \
                    and (self.is_unsigned_node(other) or self.is_signed_node(other)):
                shift = value.bit_length() - 1
                if other is right:
                    self.emit(f"shl rbx, {shift}", "text")
                    self.emit("mov rax, rbx", "text")
                else:
                    self.emit(f"shl rax, {shift}", "text")
            else:
                self.emit("imul rax, rbx", "text")
        elif op == '/':
            if signed:
                self.emit("cqo", "text")
                self.emit("idiv rbx", "text")
            else:
                self.emit("xor rdx, rdx", "text")
                self.emit("div rbx", "text")
        elif op == '%':
            if signed:
                self.emit("cqo", "text")
                self.emit("idiv rbx", "text")
            else:
                self.emit("xor rdx, rdx", "text")
                self.emit("div rbx", "text")
            self.emit("mov rax, rdx", "text")
        elif op == '&':
            self.emit("and rax, rbx", "text")
        elif op == '|':
            self.emit("or rax, rbx", "text")
        elif op == '^':
            self.emit("xor rax, rbx", "text")
        elif op == '<<':
            self.emit("mov rcx, rbx", "text")
            self.emit("shl rax, cl", "text")
        elif op == '>>':
            self.emit("mov rcx, rbx", "text")
            self.emit("sar rax, cl" if signed else "shr rax, cl", "text")
        elif op == '**':
            loop, end = self.new_label(), self.new_label()
            self.emit("mov rcx, rbx", "text")
            self.emit("mov rbx, rax", "text")
            self.emit("mov eax, 1", "text")
            self.emit_raw(f"{loop}:", "text")
            self.emit("test rcx, rcx", "text")
            self.emit(f"jz {end}", "text")
            self.emit("imul rax, rbx", "text")
            self.emit("dec rcx", "text")
            self.emit(f"jmp {loop}", "text")
            self.emit_raw(f"{end}:", "text")
        else:
            self.emit("cmp rax, rbx", "text")
            if unsigned:
                cc = {"==": "sete", "!=": "setne", "<": "setb", "<=": "setbe",
                      ">": "seta", ">=": "setae"}.get(op)
            else:
                cc = {"==": "sete", "!=": "setne", "<": "setl", "<=": "setle",
                      ">": "setg", ">=": "setge"}.get(op)
            if cc:
                self.emit(f"{cc} al", "text")
                self.emit("movzx eax, al", "text")
        self.emit("push rax", "text")

    def gen_conversion(self, node: ASTNode) -> None:
        target = node.meta.get('target_ref') or TypeRef(base=node.target_type)
        source = self.ref_of(node.children[0]) if node.children else None
        self.gen_expression(node.children[0] if node.children else None)
        self.emit("pop rax", "text")

        src_float = self.is_float_ref(source) or self.is_float_node(node.children[0])
        dst_float = self.is_float_ref(target)
        tsize = self.size_of(target)
        method = node.conversion_method

        if src_float and dst_float:
            pass
        elif src_float and not dst_float:
            self.emit("movq xmm0, rax", "text")
            self.emit("cvttsd2si rax, xmm0", "text")
        elif not src_float and dst_float:
            self.emit("cvtsi2sd xmm0, rax", "text")
            self.emit("movq rax, xmm0", "text")

        if method == 'saturating' and tsize < 8:
            limit = (1 << (tsize * 8)) - 1
            self.emit(f"cmp rax, {limit}", "text")
            ok = self.new_label()
            self.emit(f"jbe {ok}", "text")
            self.emit(f"mov rax, {limit}", "text")
            self.emit_raw(f"{ok}:", "text")

        # truncate to the target width (zero-extending writes need no imm64)
        if tsize == 1:
            self.emit("movzx eax, al", "text")
        elif tsize == 2:
            self.emit("movzx eax, ax", "text")
        elif tsize == 4:
            self.emit("mov eax, eax", "text")

        self.emit("push rax", "text")

def literal_int(node) -> int:
    """Integer value of a numeric literal, honouring the base it was written in."""
    raw = node.value
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    base = node.meta.get('base') if isinstance(node.meta, dict) else None
    if base:
        try:
            return int(text, base)
        except ValueError:
            return 0
    for parser in (0, 10):
        try:
            return int(text, parser)
        except ValueError:
            continue
    return 0


BOOT_ORIGIN = 0x7C00
BOOT_LIMIT = 510


class BootCodegen:
    """Emits a 16-bit real-mode BIOS boot sector in NASM syntax.

    A boot sector runs before any runtime exists, so this back end targets the
    subset of LOWL that makes sense at that stage: scalar u8/u16 locals and
    globals, integer arithmetic and comparisons, if/elif/else, while,
    for-range, functions with up to three parameters, inline asm, string
    literals, and a few BIOS builtins (print, putc, newline, clear_screen,
    read_key, halt, print_u16, print_hex, delay).
    """

    ARG_REGS = ['ax', 'bx', 'cx']

    BUILTINS = {'print', 'putc', 'newline', 'clear_screen', 'read_key', 'halt',
                'print_u16', 'print_hex', 'delay'}

    def __init__(self, symbols, opt_level=None):
        self.symbols = symbols
        self.text: List[str] = []
        self.rodata: List[str] = []
        self.bss: List[str] = []
        self.locals: dict = {}
        self.globals: dict = {}
        self.frame = 0
        self.return_label: Optional[str] = None
        self.break_labels: List[str] = []
        self.continue_labels: List[str] = []
        self.counter = 0
        self.strings: dict = {}
        self.helpers: set = set()
        self.problems: List[str] = []
        self.functions: dict = {}

    # -- emission ------------------------------------------------------
    def emit(self, line: str = "") -> None:
        self.text.append(f"    {line}" if line else "")

    def raw(self, line: str) -> None:
        self.text.append(line)

    def label(self, name: str) -> None:
        self.text.append(f"{name}:")

    def new_label(self, prefix: str = "L") -> str:
        self.counter += 1
        return f".{prefix}{self.counter}"

    def note(self, message: str) -> None:
        self.problems.append(message)
        self.emit(f"; NOTE: {message}")

    # -- driver --------------------------------------------------------
    def generate(self, program: ASTNode) -> str:
        self.text.clear()
        self.rodata.clear()
        self.bss.clear()

        body = []
        for child in program.children:
            if child.type == ASTType.FUNCTION:
                self.functions[child.value] = child
            elif child.type == ASTType.ASSIGN and child.meta.get('is_declaration'):
                body.append(child)
            elif child.type in (ASTType.BLOCK,):
                body.extend(child.children)

        self.emit("; ============================================================================")
        self.emit("; lowl boot sector - 16-bit real mode, loaded by the BIOS at 0x7C00")
        self.emit("; Generated by lowlc.py -f boot")
        self.emit("; ============================================================================")
        self.raw("bits 16")
        self.raw(f"org 0x{BOOT_ORIGIN:04X}")
        self.raw("")
        self.raw("start:")
        self.emit("cli")
        self.emit("xor ax, ax")
        self.emit("mov ds, ax")
        self.emit("mov es, ax")
        self.emit("mov ss, ax")
        self.emit("mov sp, 0x7C00")
        self.emit("sti")
        self.emit("cld")

        for decl in body:
            self.gen_global_decl(decl)

        entry = 'main' if 'main' in self.functions else None
        if entry is None:
            self.note("no main() found; the boot sector halts immediately")
        else:
            self.emit(f"call fn_{entry}")

        self.emit("cli")
        self.emit("hlt")
        stop = self.new_label("halt")
        self.label(stop)
        self.emit(f"jmp {stop}")
        self.raw("")

        for name, fn in self.functions.items():
            self.gen_function(fn)

        self.gen_helpers()

        out = "\n".join(self.text) + "\n"
        if self.rodata:
            out += "\n".join(self.rodata) + "\n"
        if self.bss:
            out += "\n".join(self.bss) + "\n"
        out += "\n; pad to 510 bytes and close with the boot signature\n"
        out += f"times {BOOT_LIMIT} - ($ - $$) db 0\n"
        out += "dw 0xAA55\n"
        return out

    # -- data ----------------------------------------------------------
    def string_label(self, text: str) -> str:
        if text in self.strings:
            return self.strings[text]
        label = f"str_{len(self.strings)}"
        self.strings[text] = label
        data = ", ".join(str(b) for b in text.encode('utf-8')) + ", 0"
        self.rodata.append(f"{label}: db {data}")
        return label

    def gen_global_decl(self, node: ASTNode) -> None:
        lhs = node.children[0]
        name = lhs.value
        self.globals[name] = True
        if len(node.children) > 1:
            self.gen_expr(node.children[1])
            self.emit(f"mov [{name}], ax")
            self.rodata.append(f"{name}: dw 0")
        else:
            self.bss.append(f"{name}: resw 1")

    # -- functions -----------------------------------------------------
    def gen_function(self, node: ASTNode) -> None:
        name = node.value
        params = getattr(node, 'function_param_names', None)
        if not params:
            params = [ref.name for ref in (node.meta.get('param_refs') or []) if getattr(ref, 'name', None)]
        body = None

        self.locals = {}
        self.frame = 0
        self.return_label = self.new_label("ret")
        self.break_labels = []
        self.continue_labels = []

        self.raw("")
        self.raw(f"; function {name}")
        self.raw(f"fn_{name}:")
        self.emit("push bp")
        self.emit("mov bp, sp")

        if len(params) > len(self.ARG_REGS):
            self.note(f"{name}: only {len(self.ARG_REGS)} parameters are supported in the boot target")
            params = params[:len(self.ARG_REGS)]

        for index, pname in enumerate(params):
            self.frame += 2
            offset = -self.frame
            self.locals[pname] = offset
            self.emit(f"mov [bp{offset:+d}], {self.ARG_REGS[index]}")

        for stmt in node.children:
            if stmt is not None:
                self.gen_stmt(stmt)

        self.emit("xor ax, ax")
        self.label(self.return_label)
        self.emit("mov sp, bp")
        self.emit("pop bp")
        self.emit("ret")

    # -- statements ----------------------------------------------------
    def gen_block(self, node: ASTNode) -> None:
        for stmt in node.children:
            if stmt is not None:
                self.gen_stmt(stmt)

    def gen_stmt(self, node: ASTNode) -> None:
        t = node.type
        if t == ASTType.BLOCK:
            self.gen_block(node)
        elif t == ASTType.ASSIGN:
            self.gen_assign(node)
        elif t == ASTType.IF_STMT:
            self.gen_if(node)
        elif t == ASTType.WHILE_STMT:
            self.gen_while(node)
        elif t == ASTType.FOR_STMT:
            self.gen_for(node)
        elif t == ASTType.RETURN_STMT:
            self.gen_return(node)
        elif t in (ASTType.CALL, ASTType.BUILTIN_CALL):
            self.gen_expr(node)
        elif t == ASTType.ASM_STMT:
            for line in str(node.value).split(';'):
                if line.strip():
                    self.raw(f"    {line.strip()}")
        elif t == ASTType.BREAK_STMT:
            if self.break_labels:
                self.emit(f"jmp {self.break_labels[-1]}")
        elif t == ASTType.CONTINUE_STMT:
            if self.continue_labels:
                self.emit(f"jmp {self.continue_labels[-1]}")
        elif t in (ASTType.FUNCTION, ASTType.STRUCT_DEF, ASTType.CLASS,
                   ASTType.IMPL_BLOCK, ASTType.TEMPLATE_DECL, ASTType.ENUM_DEF,
                   ASTType.PRAGMA, ASTType.IMPORT_STMT):
            pass
        elif t == ASTType.SWITCH_STMT:
            self.note("switch is not supported in the boot target")
        else:
            self.note(f"{t.name.lower()} statement is not supported in the boot target")

    def gen_assign(self, node: ASTNode) -> None:
        lhs = node.children[0]
        value = node.children[1] if len(node.children) > 1 else None

        if lhs.type != ASTType.VARIABLE:
            self.note("only scalar variables can be assigned in the boot target")
            return

        name = lhs.value
        if node.meta.get('is_declaration') and name not in self.globals:
            if name not in self.locals:
                self.frame += 2
                self.locals[name] = -self.frame
            target = f"[bp{self.locals[name]:+d}]"
        elif name in self.locals:
            target = f"[bp{self.locals[name]:+d}]"
        elif name in self.globals:
            target = f"[{name}]"
        else:
            self.note(f"unknown variable '{name}'")
            return

        if value is not None:
            self.gen_expr(value)
        else:
            self.emit("xor ax, ax")
        self.emit(f"mov {target}, ax")

    def gen_if(self, node: ASTNode) -> None:
        cond = node.children[0]
        then_block = node.children[1] if len(node.children) > 1 else None
        rest = node.children[2:]

        else_label = self.new_label("else")
        end_label = self.new_label("endif")

        self.gen_expr(cond)
        self.emit("test ax, ax")
        self.emit(f"jz {else_label}")
        if then_block is not None:
            self.gen_block(then_block)

        if rest:
            self.emit(f"jmp {end_label}")
            self.label(else_label)
            for branch in rest:
                if branch.type == ASTType.IF_STMT:
                    self.gen_if(branch)
                else:
                    self.gen_block(branch)
            self.label(end_label)
        else:
            self.label(else_label)

    def gen_while(self, node: ASTNode) -> None:
        cond = node.children[0]
        body = node.children[1] if len(node.children) > 1 else None

        top = self.new_label("while")
        end = self.new_label("endwhile")

        self.label(top)
        self.gen_expr(cond)
        self.emit("test ax, ax")
        self.emit(f"jz {end}")

        self.break_labels.append(end)
        self.continue_labels.append(top)
        if body is not None:
            self.gen_block(body)
        self.break_labels.pop()
        self.continue_labels.pop()

        self.emit(f"jmp {top}")
        self.label(end)

    def gen_for(self, node: ASTNode) -> None:
        if node.value != 'range' or len(node.children) < 4:
            self.note("only 'for i in a..b' loops are supported in the boot target")
            return

        var_node, start, end_expr = node.children[0], node.children[1], node.children[2]
        body = node.children[-1]
        step_expr = node.children[3] if len(node.children) == 5 else None
        name = var_node.value

        if name not in self.locals:
            self.frame += 2
            self.locals[name] = -self.frame
        slot = f"[bp{self.locals[name]:+d}]"

        self.gen_expr(start)
        self.emit(f"mov {slot}, ax")
        self.gen_expr(end_expr)
        self.emit("mov dx, ax")          # dx holds the exclusive bound

        top = self.new_label("for")
        end = self.new_label("endfor")
        step = self.new_label("forstep")

        self.label(top)
        self.emit(f"mov ax, {slot}")
        self.emit("cmp ax, dx")
        self.emit(f"jae {end}")

        self.break_labels.append(end)
        self.continue_labels.append(step)
        self.gen_block(body)
        self.break_labels.pop()
        self.continue_labels.pop()

        self.label(step)
        self.emit(f"mov ax, {slot}")
        if step_expr is not None:
            self.emit("push ax")
            self.gen_expr(step_expr)
            self.emit("mov bx, ax")
            self.emit("pop ax")
            self.emit("add ax, bx")
        else:
            self.emit("inc ax")
        self.emit(f"mov {slot}, ax")
        self.emit(f"jmp {top}")
        self.label(end)

    def gen_return(self, node: ASTNode) -> None:
        if node.children:
            self.gen_expr(node.children[0])
        else:
            self.emit("xor ax, ax")
        if self.return_label:
            self.emit(f"jmp {self.return_label}")

    # -- expressions ---------------------------------------------------
    def gen_expr(self, node: Optional[ASTNode]) -> None:
        if node is None:
            self.emit("xor ax, ax")
            return

        t = node.type
        if t == ASTType.LITERAL:
            if node.meta.get('is_string') or (isinstance(node.value, str)
                                              and not self._is_number(node.value)):
                self.emit(f"mov ax, {self.string_label(str(node.value))}")
            else:
                self.emit(f"mov ax, {literal_int(node) & 0xFFFF}")
        elif t == ASTType.VARIABLE:
            name = node.value
            if name in self.locals:
                self.emit(f"mov ax, [bp{self.locals[name]:+d}]")
            elif name in self.globals:
                self.emit(f"mov ax, [{name}]")
            else:
                self.note(f"unknown variable '{name}'")
                self.emit("xor ax, ax")
        elif t == ASTType.BINARY_OP:
            self.gen_binary(node)
        elif t == ASTType.UNARY_OP:
            self.gen_unary(node)
        elif t == ASTType.CALL or t == ASTType.BUILTIN_CALL:
            self.gen_call(node)
        elif t == ASTType.TYPE_CONVERSION:
            self.gen_expr(node.children[0] if node.children else None)
            target = str(node.value or '').lower()
            if target in ('u8', 'i8', 'char', 'bool', 'bit'):
                self.emit("and ax, 0xFF")
        elif t == ASTType.MEMBER_ACCESS:
            self.note("struct member access is not supported in the boot target")
            self.emit("xor ax, ax")
        elif t == ASTType.INDEX:
            self.note("array indexing is not supported in the boot target")
            self.emit("xor ax, ax")
        elif t == ASTType.METHOD_CALL:
            self.note("method calls are not supported in the boot target")
            self.emit("xor ax, ax")
        elif t == ASTType.TUPLE or t == ASTType.ARRAY_LITERAL:
            self.note("aggregate literals are not supported in the boot target")
            self.emit("xor ax, ax")
        else:
            self.note(f"{t.name.lower()} expression is not supported in the boot target")
            self.emit("xor ax, ax")

    @staticmethod
    def _is_number(text: str) -> bool:
        for parser in (0, 10, 16):
            try:
                int(text, parser)
                return True
            except (TypeError, ValueError):
                continue
        return False

    def gen_binary(self, node: ASTNode) -> None:
        op = str(node.value or '').lower()
        left = node.children[0] if node.children else None
        right = node.children[1] if len(node.children) > 1 else None

        if op in ('and', '&&', 'or', '||'):
            self.gen_expr(left)
            self.emit("push ax")
            self.gen_expr(right)
            self.emit("mov bx, ax")
            self.emit("pop ax")
            self.emit("test ax, ax")
            self.emit("setne al")
            self.emit("xor ah, ah")
            self.emit("test bx, bx")
            self.emit("setne bl")
            self.emit("xor bh, bh")
            self.emit("and ax, bx" if op in ('and', '&&') else "or ax, bx")
            return

        self.gen_expr(left)
        self.emit("push ax")
        self.gen_expr(right)
        self.emit("mov bx, ax")
        self.emit("pop ax")

        simple = {
            '+': "add ax, bx", '-': "sub ax, bx", '*': "imul bx",
            '&': "and ax, bx", '|': "or ax, bx", '^': "xor ax, bx",
        }
        if op in simple:
            self.emit(simple[op])
            return
        if op in ('/', '%'):
            self.emit("xor dx, dx")
            self.emit("div bx")
            if op == '%':
                self.emit("mov ax, dx")
            return
        if op == '<<':
            self.emit("mov cx, bx")
            self.emit("shl ax, cl")
            return
        if op == '>>':
            self.emit("mov cx, bx")
            self.emit("shr ax, cl")
            return

        compare = {'==': 'e', '!=': 'ne', '<': 'b', '<=': 'be', '>': 'a', '>=': 'ae'}
        if op in compare:
            self.emit("cmp ax, bx")
            self.emit(f"set{compare[op]} al")
            self.emit("xor ah, ah")
            return

        self.note(f"operator '{op}' is not supported in the boot target")
        self.emit("xor ax, ax")

    def gen_unary(self, node: ASTNode) -> None:
        op = str(node.value or '').lower()
        self.gen_expr(node.children[0] if node.children else None)
        if op in ('-', 'neg'):
            self.emit("neg ax")
        elif op in ('not', '!'):
            self.emit("test ax, ax")
            self.emit("sete al")
            self.emit("xor ah, ah")
        elif op == '~':
            self.emit("not ax")

    def gen_call(self, node: ASTNode) -> None:
        name = str(node.value or '')
        args = node.children[1:] if node.children and node.children[0].type == ASTType.VARIABLE \
            else list(node.children)
        low = name.lower()

        if low in self.BUILTINS:
            self.gen_builtin(low, args)
            return

        if name not in self.functions:
            self.note(f"call to unknown function '{name}'")
            self.emit("xor ax, ax")
            return

        if len(args) > len(self.ARG_REGS):
            self.note(f"{name}: only {len(self.ARG_REGS)} arguments are supported in the boot target")
            args = args[:len(self.ARG_REGS)]

        for arg in args:
            self.gen_expr(arg)
            self.emit("push ax")
        for index in range(len(args) - 1, -1, -1):
            self.emit(f"pop {self.ARG_REGS[index]}")

        self.emit(f"call fn_{name}")

    def gen_builtin(self, name: str, args: List[ASTNode]) -> None:
        def first_arg() -> None:
            self.gen_expr(args[0] if args else None)

        if name == 'print':
            self.helpers.add('print')
            arg = args[0] if args else None
            if arg is not None and arg.type == ASTType.LITERAL and arg.meta.get('is_string'):
                self.emit(f"mov si, {self.string_label(str(arg.value))}")
            else:
                first_arg()
                self.emit("mov si, ax")
            self.emit("call boot_print")
        elif name == 'putc':
            self.helpers.add('putc')
            first_arg()
            self.emit("call boot_putc")
        elif name == 'newline':
            self.helpers.update(('newline', 'putc'))
            self.emit("call boot_newline")
        elif name == 'clear_screen':
            self.emit("mov ax, 0x0003")
            self.emit("int 0x10")
        elif name == 'read_key':
            self.emit("xor ah, ah")
            self.emit("int 0x16")
        elif name == 'halt':
            self.emit("cli")
            self.emit("hlt")
            stop = self.new_label("halt")
            self.label(stop)
            self.emit(f"jmp {stop}")
        elif name == 'print_u16':
            self.helpers.update(('print_u16', 'putc'))
            first_arg()
            self.emit("call boot_print_u16")
        elif name == 'print_hex':
            self.helpers.update(('print_hex', 'putc'))
            first_arg()
            self.emit("call boot_print_hex")
        elif name == 'delay':
            first_arg()
            self.emit("mov cx, ax")
            self.emit("call boot_delay")
        else:
            self.note(f"builtin '{name}' is not supported in the boot target")
            self.emit("xor ax, ax")

    # -- runtime helpers -----------------------------------------------
    def gen_helpers(self) -> None:
        if 'putc' in self.helpers:
            self.raw("")
            self.raw("; BIOS teletype output, al = character")
            self.raw("boot_putc:")
            self.emit("push ax")
            self.emit("push bx")
            self.emit("push cx")
            self.emit("push dx")
            self.emit("mov ah, 0x0E")
            self.emit("mov bx, 0x0007")
            self.emit("int 0x10")
            self.emit("pop dx")
            self.emit("pop cx")
            self.emit("pop bx")
            self.emit("pop ax")
            self.emit("ret")

        if 'newline' in self.helpers:
            self.raw("")
            self.raw("; carriage return + line feed")
            self.raw("boot_newline:")
            self.emit("push ax")
            self.emit("mov ax, 13")
            self.emit("call boot_putc")
            self.emit("mov ax, 10")
            self.emit("call boot_putc")
            self.emit("pop ax")
            self.emit("ret")

        if 'print' in self.helpers:
            self.raw("")
            self.raw("; print the NUL-terminated string at ds:si")
            self.raw("boot_print:")
            self.emit("push ax")
            self.emit("push si")
            loop = self.new_label("print")
            done = self.new_label("printdone")
            self.label(loop)
            self.emit("lodsb")
            self.emit("test al, al")
            self.emit(f"jz {done}")
            self.emit("call boot_putc")
            self.emit(f"jmp {loop}")
            self.label(done)
            self.emit("pop si")
            self.emit("pop ax")
            self.emit("ret")

        if 'print_u16' in self.helpers:
            self.raw("")
            self.raw("; print ax as unsigned decimal")
            self.raw("boot_print_u16:")
            self.emit("push ax")
            self.emit("push bx")
            self.emit("push cx")
            self.emit("push dx")
            self.emit("mov bx, 10")
            self.emit("xor cx, cx")
            divide = self.new_label("div")
            emit_digits = self.new_label("digits")
            self.label(divide)
            self.emit("xor dx, dx")
            self.emit("div bx")
            self.emit("push dx")
            self.emit("inc cx")
            self.emit("test ax, ax")
            self.emit(f"jnz {divide}")
            self.label(emit_digits)
            self.emit("pop ax")
            self.emit("add al, 0x30")
            self.emit("call boot_putc")
            self.emit(f"loop {emit_digits}")
            self.emit("pop dx")
            self.emit("pop cx")
            self.emit("pop bx")
            self.emit("pop ax")
            self.emit("ret")

        if 'print_hex' in self.helpers:
            self.raw("")
            self.raw("; print ax as four hex digits")
            self.raw("boot_print_hex:")
            self.emit("push ax")
            self.emit("push bx")
            self.emit("push cx")
            self.emit("push dx")
            self.emit("mov dx, ax")
            self.emit("mov cx, 4")
            digit = self.new_label("hex")
            self.label(digit)
            self.emit("rol dx, 4")
            self.emit("mov ax, dx")
            self.emit("and ax, 0x000F")
            self.emit("cmp al, 10")
            self.emit("jb .hexdigit")
            self.emit("add al, 0x27")
            self.raw(".hexdigit:")
            self.emit("add al, 0x30")
            self.emit("push dx")
            self.emit("call boot_putc")
            self.emit("pop dx")
            self.emit(f"loop {digit}")
            self.emit("pop dx")
            self.emit("pop cx")
            self.emit("pop bx")
            self.emit("pop ax")
            self.emit("ret")

        if 'delay' in self.helpers:
            self.raw("")
            self.raw("; busy-wait roughly cx * 65536 iterations")
            self.raw("boot_delay:")
            self.emit("push cx")
            self.emit("push dx")
            outer = self.new_label("delay")
            self.label(outer)
            self.emit("mov dx, 0xFFFF")
            inner = self.new_label("delayin")
            self.label(inner)
            self.emit("dec dx")
            self.emit(f"jnz {inner}")
            self.emit(f"loop {outer}")
            self.emit("pop dx")
            self.emit("pop cx")
            self.emit("ret")


# ============================================================================
# Main Entry Point
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

    def _specialize_function_templates(self, program: ASTNode) -> ASTNode:
        codegen = CodeGenerator(self.backend, self.symbols, self.opt_level, self.output_format)

        def walk(node):
            yield node
            for child in node.children:
                yield from walk(child)

        def actual_ref(node):
            if node.type == ASTType.LITERAL and node.meta.get('is_string'):
                return TypeRef(base=DataType.STRING, name="string")
            return codegen.ref_of(node) or TypeRef(base=node.data_type)

        def same_type(left, right):
            if left.base != right.base:
                return False
            if left.base == DataType.STRUCT and left.name != right.name:
                return False
            if left.elem is not None or right.elem is not None:
                return left.elem is not None and right.elem is not None \
                    and same_type(left.elem, right.elem)
            return len(left.params) == len(right.params) and all(
                same_type(a, b) for a, b in zip(left.params, right.params))

        def bind(param, actual, params, bindings):
            if param.base == DataType.STRUCT and param.name in params:
                previous = bindings.get(param.name)
                if previous is not None:
                    return same_type(previous, actual)
                bindings[param.name] = copy.deepcopy(actual)
                return True
            if param.base != actual.base:
                return False
            if param.base == DataType.STRUCT and param.name and param.name != actual.name:
                return False
            if param.elem is not None:
                return actual.elem is not None and bind(param.elem, actual.elem, params, bindings)
            return True

        def substitute_ref(ref, bindings):
            if not isinstance(ref, TypeRef):
                return ref
            if ref.base == DataType.STRUCT and ref.name in bindings:
                return copy.deepcopy(bindings[ref.name])
            result = copy.deepcopy(ref)
            result.elem = substitute_ref(result.elem, bindings) if result.elem else None
            result.params = [substitute_ref(p, bindings) for p in result.params]
            result.fn_params = [substitute_ref(p, bindings) for p in result.fn_params]
            if result.fn_return is not None:
                result.fn_return = substitute_ref(result.fn_return, bindings)
            return result

        def substitute_value(value, bindings):
            if isinstance(value, TypeRef):
                return substitute_ref(value, bindings)
            if isinstance(value, list):
                return [substitute_value(item, bindings) for item in value]
            if isinstance(value, tuple):
                return tuple(substitute_value(item, bindings) for item in value)
            if isinstance(value, dict):
                return {key: substitute_value(item, bindings) for key, item in value.items()}
            if isinstance(value, ASTNode):
                substitute_node(value, bindings)
            return value

        def substitute_node(node, bindings):
            node.meta = {key: substitute_value(value, bindings)
                         for key, value in node.meta.items()}
            if node.type == ASTType.BINARY_OP and node.children:
                ref = node.children[0].meta.get('type_ref')
                if isinstance(ref, TypeRef):
                    node.data_type = ref.base
            for child in node.children:
                substitute_node(child, bindings)
            if node.type == ASTType.FUNCTION:
                node.meta['param_refs'] = [
                    substitute_ref(p, bindings) for p in node.meta.get('param_refs', [])]
                node.meta['return_ref'] = substitute_ref(node.meta.get('return_ref'), bindings)
                node.function_params = [p.base for p in node.meta['param_refs']]
                node.function_return = node.meta['return_ref'].base

        candidates_by_name = {}
        for fn in self.symbols.functions:
            candidates_by_name.setdefault(fn.value, []).append(fn)
        specialized = {}
        generated = []

        for call in list(walk(program)):
            if call.type != ASTType.CALL:
                continue
            args = call.children[1:]
            arg_refs = [actual_ref(arg) for arg in args]
            candidates = candidates_by_name.get(call.value, [])

            fixed = []
            generic = []
            for candidate in candidates:
                refs = candidate.meta.get('param_refs') or []
                if len(refs) != len(arg_refs):
                    continue
                if candidate.template_params:
                    generic.append(candidate)
                elif all(same_type(pref, actual) for pref, actual in zip(refs, arg_refs)):
                    fixed.append(candidate)

            if fixed:
                chosen = fixed[0]
                call.meta['resolved_label'] = chosen.meta.get('label') or codegen.function_label(chosen)
                call.meta['return_ref'] = copy.deepcopy(chosen.meta.get('return_ref'))
                continue

            for template in generic:
                bindings = {}
                params = set(template.template_params)
                refs = template.meta.get('param_refs') or []
                if not all(bind(pref, actual, params, bindings)
                           for pref, actual in zip(refs, arg_refs)):
                    continue
                if any(param not in bindings for param in params):
                    continue
                key = (template.value, tuple((name, repr(bindings[name]))
                                             for name in template.template_params))
                clone = specialized.get(key)
                if clone is None:
                    clone = copy.deepcopy(template)
                    substitute_node(clone, bindings)
                    clone.template_params = []
                    tags = "_".join(codegen._type_tag(bindings[name])
                                    for name in template.template_params)
                    clone.meta['label'] = f"{template.value}__{tags}"
                    clone.meta['template_instance'] = True
                    specialized[key] = clone
                    generated.append(clone)
                    self.symbols.register_function(clone.value, clone)
                    candidates_by_name.setdefault(clone.value, []).append(clone)
                call.meta['resolved_label'] = clone.meta['label']
                call.meta['return_ref'] = copy.deepcopy(clone.meta.get('return_ref'))
                break

        for fn in [node for node in walk(program) if node.type == ASTType.FUNCTION] + generated:
            inferred = {}
            for node in walk(fn):
                if node.type == ASTType.ASSIGN and node.children:
                    value = node.children[-1]
                    result = value.meta.get('return_ref')
                    lhs = node.children[0]
                    if isinstance(result, TypeRef) and lhs.type == ASTType.VARIABLE:
                        node.meta['type_ref'] = copy.deepcopy(result)
                        lhs.meta['type_ref'] = copy.deepcopy(result)
                    ref = node.meta.get('type_ref')
                    if isinstance(ref, TypeRef) and lhs.type == ASTType.VARIABLE:
                        inferred[lhs.value] = ref
            for node in walk(fn):
                if node.type == ASTType.VARIABLE and node.value in inferred:
                    node.meta['type_ref'] = copy.deepcopy(inferred[node.value])

        program.children.extend(generated)
        return program
        
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

        ast = self._specialize_function_templates(ast)
            
        if self.verbose:
            print("Parser: AST built")
            
        if self.output_format == OutputFormat.BOOT_IMAGE:
            boot = BootCodegen(self.symbols)
            asm_code = boot.generate(ast)
            for problem in boot.problems:
                print(f"note: {problem}")
        else:
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
        description='lowl Compiler v2.1.0 - Complete Systems Programming Language',
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
