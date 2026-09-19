"""Keep the runnable instructions consistent with the skin-source policy."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RunbookContracts(unittest.TestCase):
    def read(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_legacy_ini_only_routes_to_current_step(self):
        text = self.read("references/ini-template.md")
        self.assertNotIn("以本文件为准", text)
        self.assertNotIn("```ini", text)
        self.assertIn("step-09-ini.md", text)

    def test_current_ini_preserves_observed_gate_and_draw(self):
        text = self.read("references/step-09-ini.md")
        operation = text.split("## 操作", 1)[1].split("## 期望输出", 1)[0]
        self.assertNotIn("if vs == 202 && ps == 1718.1", operation)
        self.assertNotIn("drawindexedinstanced =", operation)

    def test_vision_does_not_reject_b_for_unrelated_atlas_changes(self):
        text = self.read("references/vision-subagent.md")
        self.assertNotIn("legs_only && !stray_pixels", text)
        self.assertIn("框外其它部件", text)

    def test_install_describes_required_style_switch(self):
        text = self.read("INSTALL.md")
        self.assertNotIn("可加默认关闭", text)
        self.assertIn("默认必须", text)

    def test_build_commands_include_b_tint_choices(self):
        text = self.read("references/step-07-build-ps.md")
        commands = [line for line in text.splitlines()
                    if line.strip().startswith("python scripts/build_sheer_ps.py")
                    and "--skin-slot-kind bareleg" in line]
        self.assertEqual(len(commands), 2)
        self.assertTrue(any("--skin-tint-source shared" in line for line in commands))
        self.assertTrue(any("--skin-tint-source constant --skin-tint-linear" in line
                            for line in commands))
        self.assertTrue(all("--style-index" in line for line in commands))

    def test_delivery_instructions_cover_all_states_and_no_bypass(self):
        text = self.read("references/step-08-static-gate.md")
        self.assertIn("--shader \"<正式状态一>\" --shader \"<正式状态二>\"", text)
        self.assertIn("每个目标 draw", text)
        self.assertIn("资源绑定签名", text)
        self.assertIn("不得改用 `--no-style-switch`", text)

    def test_bake_quality_uses_all_covered_pixels(self):
        text = self.read("references/step-06-skin-source.md")
        self.assertNotIn("C 表面距离中位数不超过 10", text)
        self.assertIn("所有覆盖像素", text)
        self.assertIn("不能猜 1,1,1", text)

    def test_colour_report_keeps_distinct_body_and_stocking_draws(self):
        text = self.read("references/step-06-skin-source.md")
        commands = [line for line in text.splitlines()
                    if line.strip().startswith("python scripts/stocking_preview.py")
                    and '--piece "body-source"' in line]
        self.assertEqual(len(commands), 1)
        self.assertIn('--piece "<目标标签>" "<丝袜资源一>" "<丝袜draw一>"', commands[0])
        self.assertIn('--piece "body-source" "<身体资源>" "<身体draw>"', commands[0])
        self.assertIn("身体和丝袜的 draw 数量、起点、基顶点可以不同", text)

    def p0_notice(self, text):
        """Return the two verbatim lines of the P0 notice as they appear in a document."""
        return [line.strip() for line in text.splitlines()
                if line.strip().startswith(("【先确认能不能做】", "请先花半分钟看一眼"))]

    def test_p0_gate_comes_first_in_skill(self):
        # Low-capability agents answer after reading SKILL.md and step 00 only,
        # so the notice text itself must live there, ahead of every other rule.
        text = self.read("SKILL.md")
        gate = text.index("## 前提闸门 P0")
        self.assertLess(gate, text.index("## 默认值"))
        self.assertLess(gate, text.index("## 硬规矩"))
        self.assertEqual(len(self.p0_notice(text)), 2)
        self.assertIn("【无法完成】", text)
        self.assertIn("P0、U1、U2、三问没齐", text)

    def test_p0_notice_opens_the_first_reply_example(self):
        skill = self.read("SKILL.md")
        step = self.read("references/step-00-intake.md")
        example = step.split("## 期望输出", 1)[1].split("## 判定", 1)[0]
        # The example must carry the same words as SKILL.md, before the file list.
        self.assertEqual(self.p0_notice(example), self.p0_notice(skill))
        self.assertLess(example.index("【先确认能不能做】"), example.index("还需要："))
        operation = step.split("## 操作", 1)[1].split("## 期望输出", 1)[0]
        self.assertLess(operation.index("【先确认能不能做】"), operation.index("点名尚缺的 U1"))

    def test_missing_leg_evidence_stops_instead_of_falling_back(self):
        for name in ("references/step-00-intake.md", "references/step-01-decide.md",
                     "references/step-06-skin-source.md"):
            verdict = self.read(name).split("## 判定", 1)[1].split("## ", 1)[0]
            self.assertIn("【无法完成】", verdict, name)
        self.assertIn("先确认能不能做", self.read("INSTALL.md"))


if __name__ == "__main__":
    unittest.main()
