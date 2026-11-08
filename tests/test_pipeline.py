"""파이프라인 게이트 테스트. 실행: python3 -m unittest discover -s tests"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE = os.path.join(SKILL_ROOT, "scripts", "pipeline.py")
STAGES = [
    "spec", "baseline", "diagnose", "decide", "change", "guard", "spec-check",
    "perf-check", "swap", "rollout", "report",
]
REPORT = "\n".join(
    f"## {name}\n내용\n" for name in [
        "결론", "측정 환경", "시간 분해", "조치", "Rust/WASM 판단",
        "전후 비교", "스펙 검사", "회귀 방지", "미확인 사항",
    ]
)
BENCH = "print(open('ms.txt').read())"


class PipelineTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = os.path.realpath(temp.name)
        self.run_dir = os.path.join(self.project, ".perf", "job")
        self.git("init", "-q")
        self.write("bench.py", BENCH)
        self.write("ms.txt", "1000")
        self.write("budget.json", "{}")
        self.write("engine.ts", "export {}")
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init")
        self.cli("init", self.run_dir, "--project", self.project, "--name", "job")

    def git(self, *args):
        subprocess.run(["git", "-C", self.project, *args], check=True, capture_output=True)

    def write(self, name, content):
        with open(os.path.join(self.project, name), "w", encoding="utf-8") as handle:
            handle.write(content)

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, PIPELINE, *args], capture_output=True, text=True, check=False
        )

    def measure(self, label, condition="production,cpu4x", runs="5"):
        return self.cli(
            "measure", self.run_dir, label, "--condition", condition, "--runs", runs,
            "--", sys.executable, "bench.py",
        )

    def spec_check(self, *code, kind="behavior"):
        return self.cli(
            "spec-check", self.run_dir, "--kind", kind, "--",
            sys.executable, "-c", code[0] if code else "pass",
        )

    def edit(self, **sections):
        path = os.path.join(self.run_dir, "run.json")
        with open(path, encoding="utf-8") as handle:
            run = json.load(handle)
        for key, value in sections.items():
            run[key] = {**run[key], **value}
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(run, handle)

    def build(self, adopt=False, after_ms="100"):
        self.edit(spec={
            "target": "필터", "metric": "duration", "percentile": "p75", "unit": "ms",
            "direction": "lower", "goal": 200, "build": "production", "device": "M2",
            "behavior": ["결과 유지"], "test_command": "test",
        })
        self.assertEqual(self.measure("baseline").returncode, 0)
        self.edit(diagnosis={
            "segments": [{"name": "연산", "ms": 950, "source": "measured"},
                         {"name": "렌더", "ms": 50, "source": "estimated"}],
            "target_segment": "연산", "classification": "cpu", "evidence": "프로파일",
        })
        if adopt:
            self.write("ms.txt", "400")
            self.assertEqual(self.measure("ts_best").returncode, 0)
            self.edit(
                decision={"rung": 6, "action": "교체", "max_gain": 950, "swap": "adopt",
                          "gate": {"cheaper_attempts": "a", "narrow_boundary": "b", "net_gain": "c"}},
                swap={"slot": "s", "location": "browser", "interface_file": "engine.ts",
                      "fallback": "f", "cost_included": ["download", "compile", "transfer", "execute"]},
                rollout={"strategy": "flag", "rollback": "끄기"},
            )
        else:
            self.edit(
                decision={"rung": 4, "action": "개선", "max_gain": 950,
                          "swap": "unnecessary", "swap_reason": "충분"},
                swap={"skipped_reason": "불필요"},
                rollout={"strategy": "direct", "reason": "내부 변경", "rollback": "되돌리기"},
            )
        self.write("ms.txt", after_ms)
        self.edit(
            change={"summary": "수정", "files": ["ms.txt"]},
            guard={"kind": "budget", "artifacts": ["budget.json"]},
        )
        self.assertEqual(self.spec_check().returncode, 0)
        if adopt:
            self.assertEqual(self.spec_check(kind="compat").returncode, 0)
        self.assertEqual(self.measure("after").returncode, 0)
        with open(os.path.join(self.run_dir, "REPORT.md"), "w", encoding="utf-8") as handle:
            handle.write(REPORT)

    def assert_gate(self, stage, fragment):
        result = self.cli("check", self.run_dir)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(f"FAIL  {stage}", result.stdout)
        self.assertIn(fragment, result.stdout)

    def test_complete_without_swap(self):
        self.build()
        result = self.cli("check", self.run_dir)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("PIPELINE COMPLETE", result.stdout)
        for stage in STAGES:
            self.assertIn(f"PASS  {stage}", result.stdout)

    def test_complete_with_swap(self):
        self.build(adopt=True)
        result = self.cli("check", self.run_dir)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_empty_run_fails_every_stage(self):
        result = self.cli("check", self.run_dir)
        self.assertEqual(result.returncode, 1)
        for stage in STAGES:
            self.assertIn(f"FAIL  {stage}", result.stdout)

    def test_dev_build_rejected(self):
        self.build()
        self.edit(spec={"build": "development"})
        self.assert_gate("spec", "production")

    def test_too_few_runs_rejected(self):
        self.build()
        self.assertEqual(self.measure("baseline", runs="2").returncode, 0)
        self.assert_gate("baseline", "측정 횟수 부족")

    def test_goal_miss_rejected(self):
        self.build(after_ms="500")
        self.assert_gate("perf-check", "목표")

    def test_different_condition_rejected(self):
        self.build()
        self.assertEqual(self.measure("after", condition="production").returncode, 0)
        self.assert_gate("perf-check", "조건이 다름")

    def test_noise_rejected(self):
        self.build()
        path = os.path.join(self.run_dir, "samples.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([100, 1000, 100, 1200, 150, 1300, 900], handle)
        self.assertEqual(self.cli(
            "measure", self.run_dir, "after", "--condition", "production,cpu4x",
            "--samples-file", path, "--source-note", "RUM",
        ).returncode, 0)
        self.assert_gate("perf-check", "노이즈")

    def test_failed_spec_check_rejected(self):
        self.build()
        self.assertEqual(self.spec_check("raise SystemExit(3)").returncode, 1)
        self.assert_gate("spec-check", "실패")

    def test_code_change_after_checks_rejected(self):
        self.build()
        self.write("ms.txt", "99")
        result = self.cli("check", self.run_dir)
        self.assertEqual(result.returncode, 1)
        self.assertIn("검사 후 코드가 바뀜", result.stdout)
        self.assertIn("측정 후 코드가 바뀜", result.stdout)

    def test_segments_must_explain_baseline(self):
        self.build()
        self.edit(diagnosis={"segments": [{"name": "연산", "ms": 100, "source": "measured"}]})
        self.assert_gate("diagnose", "구간 합")

    def test_estimated_target_rejected(self):
        self.build()
        self.edit(diagnosis={"segments": [{"name": "연산", "ms": 1000, "source": "estimated"}]})
        self.assert_gate("diagnose", "측정값이 아님")

    def test_swap_for_react_rejected(self):
        self.build(adopt=True)
        self.edit(diagnosis={"classification": "react-dom"})
        self.assert_gate("decide", "교체 대상이 아님")

    def test_swap_requires_ts_best(self):
        self.build(adopt=True)
        path = os.path.join(self.run_dir, "run.json")
        with open(path, encoding="utf-8") as handle:
            run = json.load(handle)
        del run["measurements"]["ts_best"]
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(run, handle)
        self.assert_gate("swap", "ts_best")

    def test_swap_must_beat_ts_best(self):
        self.build(adopt=True, after_ms="150")
        self.write("ms.txt", "120")
        self.assertEqual(self.measure("ts_best").returncode, 0)
        self.write("ms.txt", "150")
        self.assert_gate("swap", "낫지 않음")

    def test_swap_requires_total_cost(self):
        self.build(adopt=True)
        self.edit(swap={"cost_included": ["execute"]})
        self.assert_gate("swap", "총비용 누락")

    def test_swap_requires_compat(self):
        self.build()
        self.edit(
            decision={"rung": 6, "swap": "adopt",
                      "gate": {"cheaper_attempts": "a", "narrow_boundary": "b", "net_gain": "c"}},
            swap={"slot": "s", "location": "server", "interface_file": "engine.ts",
                  "fallback": "f", "cost_included": ["transfer", "execute"]},
        )
        self.assert_gate("swap", "compat")

    def test_swap_cannot_go_direct(self):
        self.build(adopt=True)
        self.edit(rollout={"strategy": "direct", "reason": "x"})
        self.assert_gate("rollout", "direct")

    def test_guard_file_must_exist(self):
        self.build()
        self.edit(guard={"artifacts": ["missing.json"]})
        self.assert_gate("guard", "missing.json")

    def test_report_sections_required(self):
        self.build()
        with open(os.path.join(self.run_dir, "REPORT.md"), "w", encoding="utf-8") as handle:
            handle.write("## 결론\n")
        self.assert_gate("report", "스펙 검사")

    def test_set_merges_and_refuses_recorded_sections(self):
        self.assertEqual(self.cli("set", self.run_dir, "spec", '{"goal": 200}').returncode, 0)
        self.assertEqual(self.cli("set", self.run_dir, "spec", '{"unit": "ms"}').returncode, 0)
        with open(os.path.join(self.run_dir, "run.json"), encoding="utf-8") as handle:
            spec = json.load(handle)["spec"]
        self.assertEqual(spec, {"goal": 200, "unit": "ms"})
        self.assertEqual(self.cli("set", self.run_dir, "measurements", "{}").returncode, 2)
        self.assertEqual(self.cli("set", self.run_dir, "checks", "{}").returncode, 2)

    def test_baseline_requires_goal_first(self):
        self.assertEqual(self.measure("baseline").returncode, 2)

    def test_goal_change_rejected_without_reason(self):
        self.build()
        self.edit(spec={"goal": 999})
        self.assert_gate("baseline", "목표가")
        self.edit(spec={"goal_change_reason": "사용자 승인"})
        result = self.cli("check", self.run_dir)
        self.assertIn("PASS  baseline", result.stdout)

    def test_remeasure_keeps_history(self):
        self.build()
        self.assertEqual(self.measure("after").returncode, 0)
        with open(os.path.join(self.run_dir, "run.json"), encoding="utf-8") as handle:
            run = json.load(handle)
        self.assertEqual([x["label"] for x in run["history"]], ["after"])

    def test_swap_gain_within_noise_rejected(self):
        self.build(adopt=True)
        path = os.path.join(self.run_dir, "samples.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([105, 300, 110, 320, 104, 400, 115], handle)
        self.assertEqual(self.cli(
            "measure", self.run_dir, "ts_best", "--condition", "production,cpu4x",
            "--samples-file", path, "--source-note", "local",
        ).returncode, 0)
        self.assert_gate("swap", "교체 이득")

    def test_failed_measurement_not_recorded(self):
        self.edit(spec={"goal": 200})
        result = self.cli(
            "measure", self.run_dir, "baseline", "--condition", "x", "--",
            sys.executable, "-c", "raise SystemExit(1)",
        )
        self.assertEqual(result.returncode, 1)
        self.assert_gate("baseline", "측정 기록 없음")


class SkillDocumentTest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(SKILL_ROOT, "SKILL.md"), encoding="utf-8") as handle:
            self.skill = handle.read()

    def test_every_stage_has_table_row_and_section(self):
        for number, stage in enumerate(STAGES, 1):
            self.assertRegex(self.skill, rf"\| {number} \| {re.escape(stage)} \|")
            self.assertIn(f"### {number}. {stage}", self.skill)

    def test_stage_order_matches_checker(self):
        with open(PIPELINE, encoding="utf-8") as handle:
            source = handle.read()
        body = source[source.index("stages = ["):]
        found = re.findall(r'\("([a-z-]+)", gate_', body)
        self.assertEqual(found, STAGES)

    def test_referenced_files_exist(self):
        paths = set(re.findall(r"`((?:references|scripts)/[\w.-]+)", self.skill))
        self.assertGreaterEqual(len(paths), 6)
        for path in paths:
            self.assertTrue(os.path.exists(os.path.join(SKILL_ROOT, path)), path)

    def test_report_template_matches_checker(self):
        with open(PIPELINE, encoding="utf-8") as handle:
            source = handle.read()
        block = source[source.index("REPORT_SECTIONS"):source.index("MIN_RUNS")]
        for section in re.findall(r'"(## [^"]+)"', block):
            self.assertIn(section, self.skill)


if __name__ == "__main__":
    unittest.main()
