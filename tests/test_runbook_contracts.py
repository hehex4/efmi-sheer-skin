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
        """Return the verbatim lines of the opening hint as they appear in a document."""
        lines = [line.strip() for line in text.splitlines()]
        start = next(i for i, line in enumerate(lines) if line.startswith("【开工提示】"))
        end = next(i for i, line in enumerate(lines) if i > start and line.startswith("查法："))
        return lines[start:end + 1]

    def test_opening_hint_comes_first_in_skill(self):
        # Low-capability agents answer after reading SKILL.md and step 00 only,
        # so the hint text itself must live there, ahead of every other rule.
        text = self.read("SKILL.md")
        hint = text.index("## 开工提示 P0")
        self.assertLess(hint, text.index("## 默认值"))
        self.assertLess(hint, text.index("## 硬规矩"))
        notice = self.p0_notice(text)
        # One opening line, the two points in order, one closing line.
        self.assertEqual(len(notice), 4)
        self.assertEqual([line[0] for line in notice[1:3]], ["①", "②"])
        for reply in ("【提示·底下没有腿】", "【提示·腿是单色】", "【提示·颜色太接近】"):
            self.assertIn("\n" + reply, text)

    def test_hints_inform_and_the_user_decides(self):
        # The hint is not a gate: nothing waits on it, and no reply refuses the job.
        text = self.read("SKILL.md")
        self.assertIn("要不要做由用户自己决定", text)
        self.assertIn("P0 是提示，不是闸门", text)
        self.assertIn("\n3. U1、U2、三问没齐", text)
        self.assertNotIn("无法完成", text)
        self.assertIn("要不要做由你决定", "\n".join(self.p0_notice(text)))
        # Each evidence-based hint hands the decision back to the user.
        blocks = [line for line in text.splitlines() if line.startswith("【提示·")]
        self.assertEqual(len(blocks), 3)
        for line in blocks:
            self.assertIn("要不要继续，由你决定。", line)

    def test_close_colours_are_measured_not_asked_up_front(self):
        # The stocking-vs-skin difference is never put to the user in the first reply:
        # asking made weak models talk users out of doable mods on a guess.
        # Step 01 measures it after the files arrive and speaks up only when it is too small.
        notice = "\n".join(self.p0_notice(self.read("SKILL.md")))
        self.assertNotIn("肉色", notice)
        self.assertNotIn("肤色", notice)
        verdict = self.read("references/step-01-decide.md").split("## 判定", 1)[1].split("## ", 1)[0]
        self.assertIn("【提示·颜色太接近】", verdict)
        self.assertIn("不向用户提这件事", verdict)
        # The hint must quote the script's own number, never an estimate.
        self.assertIn("只能抄本步 `stocking_preview.py` 的 stdout", verdict)

    def test_opening_hint_opens_the_first_reply_example(self):
        skill = self.read("SKILL.md")
        step = self.read("references/step-00-intake.md")
        example = step.split("## 期望输出", 1)[1].split("## 判定", 1)[0]
        # The example must carry the same words as SKILL.md, before the file list.
        self.assertEqual(self.p0_notice(example), self.p0_notice(skill))
        self.assertLess(example.index("【开工提示】"), example.index("【需要你提供】"))
        operation = step.split("## 操作", 1)[1].split("## 期望输出", 1)[0]
        self.assertLess(operation.index("【开工提示】"), operation.index("【需要你提供】"))

    def intake_ask(self, text):
        """Return the verbatim lines of the four-item ask as they appear in a document."""
        lines = [line.strip() for line in text.splitlines()]
        start = next(i for i, line in enumerate(lines) if line == "【需要你提供】")
        return lines[start:start + 5]

    def test_intake_ask_is_verbatim_in_skill_and_step00(self):
        # Weak models reply after reading SKILL.md only and then misquote the hunting steps
        # (wrong hash length, wrong place to look), so the ask itself must live in SKILL.md.
        skill = self.read("SKILL.md")
        step = self.read("references/step-00-intake.md")
        example = step.split("## 期望输出", 1)[1].split("## 判定", 1)[0]
        ask = self.intake_ask(skill)
        self.assertEqual([line[0] for line in ask[1:]], ["①", "②", "③", "④"])
        self.assertEqual(self.intake_ask(example), ask)
        self.assertLess(skill.index("【需要你提供】"), skill.index("## 默认值"))
        # A mismatch is reported without taking sides or offering to switch.
        self.assertIn("\n【hash 对不上】", skill)
        self.assertIn("不说哪一个“正确”", skill)
        for name in ("references/step-00-intake.md", "references/step-02-locate.md"):
            verdict = self.read(name).split("## 判定", 1)[1].split("## ", 1)[0]
            self.assertIn("【hash 对不上】", verdict, name)

    def test_user_supplies_the_ps_hash_and_the_named_file(self):
        # The hash comes from the user's hunting; the agent only cross-checks it against the frame.
        # The file is asked for by name, never as "give me the ShaderCache folder".
        self.assertIn("PS hash 由用户在 hunting 里找出来给，AI 不从帧里自己定", self.read("SKILL.md"))
        step = self.read("references/step-00-intake.md")
        example = step.split("## 期望输出", 1)[1].split("## 判定", 1)[0]
        for needed in ("hash（16 位十六进制）", "hash-ps_regex.bin", "hash-ps.bin", "-ps.txt", "一帧转储"):
            self.assertIn(needed, example)
        self.assertNotIn("ShaderCache 目录", example)
        self.assertNotIn("从帧定位", example)
        verdict = step.split("## 判定", 1)[1].split("## ", 1)[0]
        self.assertIn("不从帧里或目录里替他挑", verdict)
        self.assertIn("不自己换", verdict)
        locate = self.read("references/step-02-locate.md").split("## 操作", 1)[1].split("## 期望输出", 1)[0]
        self.assertIn("必须等于用户给的 `<目标 PS hash>`", locate)

    def test_q1_is_a_yes_no_signal_and_the_agent_lists_the_draws(self):
        # Users never list every part that went black. Q1 only asks whether the shader is
        # stockings-only; what it really draws comes from the frame's own draw list.
        for name in ("SKILL.md", "references/step-00-intake.md", "references/step-02-locate.md"):
            self.assertIn("只当“是 / 否”信号", self.read(name), name)
        step = self.read("references/step-00-intake.md")
        self.assertIn("不用列全", step)
        self.assertIn("不把这份清单当成完整范围", step)
        locate = self.read("references/step-02-locate.md").split("## 操作", 1)[1].split("## 期望输出", 1)[0]
        commands = [line for line in locate.splitlines()
                    if line.strip().startswith("python scripts/find_draw_shaders.py") and "--ps " in line]
        self.assertEqual(len(commands), 1)
        self.assertIn('--ps "<目标 PS hash>"', commands[0])

    def test_q3_is_asked_only_for_attached_parts(self):
        # The range is the stocking itself and is decided by the agent; the open question is gone.
        step = self.read("references/step-00-intake.md")
        self.assertNotIn("选定档里哪些区域要透", step)
        self.assertIn("Q3（条件题，查到连带部件才发）", step)
        self.assertIn("要不要一起透？默认不透。", step)
        self.assertIn("范围告知（是告知，不是提问）", step)
        self.assertIn("没触发视为已答", self.read("SKILL.md"))

    def test_missing_leg_evidence_is_reported_not_hidden(self):
        # Finding no leg under the stocking is told to the user once; it never silently
        # falls back to a constant colour and never silently carries on.
        for name in ("references/step-01-decide.md", "references/step-06-skin-source.md"):
            verdict = self.read(name).split("## 判定", 1)[1].split("## ", 1)[0]
            self.assertIn("【提示·底下没有腿】", verdict, name)
            self.assertIn("等用户决定", verdict, name)
        self.assertIn("先确认值不值得做", self.read("INSTALL.md"))


if __name__ == "__main__":
    unittest.main()
