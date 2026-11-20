import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import lowlc


ROOT = Path(__file__).resolve().parents[1]


class CodegenRegressionTests(unittest.TestCase):
    def compile_source(self, source, level=lowlc.OptimizationLevel.O0):
        compiler = lowlc.Compiler(opt_level=level)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "generated.asm"
            with contextlib.redirect_stdout(io.StringIO()):
                succeeded = compiler.compile(source, str(output), "regression.lowl")
            assembly = output.read_text() if succeeded else ""
        return succeeded, assembly

    def test_packed_vectors_use_width_and_lane_specific_instructions(self):
        source = (ROOT / "test_simd_core.lowl").read_text()
        succeeded, assembly = self.compile_source(source)
        self.assertTrue(succeeded)
        for instruction in ("addps", "mulps", "divpd", "subpd",
                            "vaddps", "vaddpd", "vdivpd"):
            self.assertIn(instruction, assembly)
        self.assertNotIn("not yet implemented", assembly)
        self.assertIn("mov dword [rsp + 12]", assembly)
        self.assertIn("mov qword [rsp + 8]", assembly)

    def test_vector_constructor_rejects_wrong_lane_count(self):
        source = """fn main() -> u32:
    let v: vec4_f32 = vec4_f32(1.0, 2.0, 3.0)
    return 0
"""
        succeeded, _ = self.compile_source(source)
        self.assertFalse(succeeded)

    def test_templates_specialize_and_option_values_have_no_placeholder_codegen(self):
        source = (ROOT / "test7.lowl").read_text()
        succeeded, assembly = self.compile_source(source)
        self.assertTrue(succeeded)
        for label in ("max__u64:", "max__f64:", "max__string_string:"):
            self.assertIn(label, assembly)
        self.assertNotIn("max__t_t", assembly)
        self.assertNotIn("no known owner type", assembly)
        self.assertNotIn("unsupported Option method", assembly)
        pair_value_call = assembly.index("call Pair_get_value")
        self.assertIn("cmp cl, byte [rbx]", assembly[pair_value_call:pair_value_call + 600])

    def test_class_dispatch_and_floating_square_root_emit_real_instructions(self):
        source = (ROOT / "test4.lowl").read_text()
        succeeded, assembly = self.compile_source(source)
        self.assertTrue(succeeded)
        self.assertIn("call qword [rax + 0]", assembly)
        self.assertIn("sqrtsd xmm0, xmm0", assembly)
        self.assertNotIn("floating exponent must", assembly)

    def test_optimized_integer_power_of_two_uses_shift(self):
        source = """fn main() -> u32:
    let x: u64 = 7
    let y: u64 = x * 8
    return y:u32
"""
        succeeded, assembly = self.compile_source(source, lowlc.OptimizationLevel.O2)
        self.assertTrue(succeeded)
        self.assertIn("shl rax, 3", assembly)
        self.assertNotIn("imul rax, rbx", assembly)

    def test_integer_constant_folding_matches_signed_division(self):
        tree = lowlc.ASTNode(lowlc.ASTType.BINARY_OP, "/")
        tree.add_child(lowlc.ASTNode(lowlc.ASTType.LITERAL, "-7"))
        tree.add_child(lowlc.ASTNode(lowlc.ASTType.LITERAL, "3"))
        folded = lowlc.Optimizer(lowlc.OptimizationLevel.O1).constant_folding(tree)
        self.assertEqual(folded.value, "-2")


if __name__ == "__main__":
    unittest.main()
