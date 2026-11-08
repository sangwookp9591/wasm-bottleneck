#!/usr/bin/env python3
"""wasm-bottleneck 파이프라인의 실행 기록과 게이트 검사.

사용법:
  pipeline.py init <run_dir> --project <path> --name <이름>
  pipeline.py set <run_dir> <섹션> ('<JSON>' | --file <파일>)
  pipeline.py measure <run_dir> <baseline|after|ts_best> --condition <조건>
      [--runs N] (-- <명령> | --samples-file <파일> --source-note <출처>)
  pipeline.py spec-check <run_dir> [--kind behavior|compat] -- <명령>
  pipeline.py check <run_dir>

종료 코드: 0 = 성공, 1 = 게이트 실패 또는 명령 실패, 2 = 잘못된 사용
"""
import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time

CLASSIFICATIONS = {
    "cpu", "gc-memory", "draw", "server-cpu", "leak", "main-thread",
    "react-dom", "network", "bundle", "io", "concurrency",
}
SWAP_CLASSIFICATIONS = {"cpu", "gc-memory", "draw", "server-cpu"}
SWAP_COSTS = {
    "browser": {"download", "compile", "transfer", "execute"},
    "server": {"transfer", "execute"},
}
REPORT_SECTIONS = [
    "## 결론", "## 측정 환경", "## 시간 분해", "## 조치", "## Rust/WASM 판단",
    "## 전후 비교", "## 스펙 검사", "## 회귀 방지", "## 미확인 사항",
]
MIN_RUNS = 5
EDITABLE_SECTIONS = ("spec", "diagnosis", "decision", "change", "swap", "rollout", "guard")


def die(message):
    print(f"오류: {message}", file=sys.stderr)
    sys.exit(2)


def run_path(run_dir):
    return os.path.join(run_dir, "run.json")


def load(run_dir):
    try:
        with open(run_path(run_dir), encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        die(f"{run_path(run_dir)} 없음. init을 먼저 실행하세요.")
    except json.JSONDecodeError as error:
        die(f"run.json 형식 오류: {error}")


def save(run_dir, run):
    with open(run_path(run_dir), "w", encoding="utf-8") as handle:
        json.dump(run, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def git(project, *args):
    return subprocess.run(
        ["git", "-C", project, *args], capture_output=True, check=False
    )


def code_state(project, run_dir):
    """커밋, 수정 내용, 추적되지 않은 파일을 합친 지문. git 저장소가 아니면 None."""
    head = git(project, "rev-parse", "HEAD")
    if head.returncode != 0:
        return None
    scope = ["--", "."]
    relative = os.path.relpath(os.path.abspath(run_dir), project)
    if not relative.startswith(".."):
        scope.append(f":(exclude){relative}")
    digest = hashlib.sha256(head.stdout)
    digest.update(git(project, "diff", "HEAD", "--binary", *scope).stdout)
    untracked = git(project, "ls-files", "-o", "--exclude-standard", "-z", *scope)
    for name in sorted(filter(None, untracked.stdout.split(b"\0"))):
        digest.update(name)
        path = os.path.join(project.encode(), name)
        if os.path.isfile(path):
            with open(path, "rb") as handle:
                digest.update(handle.read())
    return digest.hexdigest()


def cmd_init(args):
    project = os.path.abspath(args.project)
    if not os.path.isdir(project):
        die(f"프로젝트 폴더 없음: {project}")
    if os.path.exists(run_path(args.run_dir)):
        die(f"이미 존재: {run_path(args.run_dir)}")
    os.makedirs(args.run_dir, exist_ok=True)
    save(args.run_dir, {
        "meta": {"name": args.name, "project": project, "created_at": time.time()},
        "spec": {}, "diagnosis": {}, "decision": {}, "change": {}, "swap": {},
        "rollout": {}, "guard": {}, "measurements": {}, "checks": {},
    })
    print(f"생성: {run_path(args.run_dir)}")
    return 0


def cmd_set(args):
    if bool(args.value) == bool(args.file):
        die("JSON 문자열과 --file 중 하나만 지정하세요.")
    raw = args.value
    if args.file:
        with open(args.file, encoding="utf-8") as handle:
            raw = handle.read()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        die(f"JSON 형식 오류: {error}")
    if not isinstance(value, dict):
        die("JSON 객체를 지정하세요.")
    run = load(args.run_dir)
    run[args.section] = {**run[args.section], **value}
    save(args.run_dir, run)
    print(f"{args.section} 갱신: {', '.join(sorted(value))}")
    return 0


def cmd_measure(args):
    run = load(args.run_dir)
    project = run["meta"]["project"]
    command = args.command
    if bool(command) == bool(args.samples_file):
        die("-- <명령>과 --samples-file 중 하나만 지정하세요.")
    if args.label == "baseline" and not number(run["spec"].get("goal")):
        die("기준선을 재기 전에 spec.goal을 정하세요. 측정을 본 뒤 목표를 맞추지 않기 위해서입니다.")
    state = code_state(project, args.run_dir)
    if args.samples_file:
        if not args.source_note:
            die("--samples-file에는 --source-note가 필요합니다.")
        with open(args.samples_file, encoding="utf-8") as handle:
            samples = json.load(handle)
        if not samples or not all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in samples
        ):
            die("--samples-file은 숫자 배열이어야 합니다.")
        samples = [float(x) for x in samples]
        source = args.source_note
    else:
        samples = []
        for index in range(args.runs):
            result = subprocess.run(command, cwd=project, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                print(result.stdout + result.stderr, file=sys.stderr)
                print(f"측정 {index + 1}회차 실패, 기록하지 않음 (exit {result.returncode})", file=sys.stderr)
                return 1
            lines = [line for line in result.stdout.splitlines() if line.strip()]
            try:
                samples.append(float(lines[-1]))
            except (IndexError, ValueError):
                print(f"마지막 출력 줄이 숫자가 아님: {lines[-1:]}", file=sys.stderr)
                return 1
        source = "command"
    median = statistics.median(samples)
    previous = run["measurements"].get(args.label)
    if previous:
        run.setdefault("history", []).append({"label": args.label, **previous})
    load_average = os.getloadavg()[0]
    cpus = os.cpu_count() or 1
    if load_average > cpus:
        print(f"경고: 시스템 부하 {load_average:.1f} > CPU {cpus}개. 수치가 흔들릴 수 있습니다.", file=sys.stderr)
    run["measurements"][args.label] = {
        "samples": samples,
        "goal": run["spec"].get("goal"),
        "load1": load_average,
        "cpus": cpus,
        "median": median,
        "mad": statistics.median(abs(x - median) for x in samples),
        "condition": args.condition,
        "command": command,
        "source": source,
        "recorded_at": time.time(),
        "code_state": state,
    }
    save(args.run_dir, run)
    print(f"{args.label}: 중앙값 {median:g} ({len(samples)}회, 조건 {args.condition})")
    return 0


def cmd_spec_check(args):
    run = load(args.run_dir)
    project = run["meta"]["project"]
    command = args.command
    if not command:
        die("검사 명령이 필요합니다.")
    result = subprocess.run(
        command, cwd=project, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False
    )
    log = f"spec-check-{args.kind}.log"
    with open(os.path.join(args.run_dir, log), "wb") as handle:
        handle.write(result.stdout)
    run["checks"][args.kind] = {
        "command": command,
        "exit_code": result.returncode,
        "log": log,
        "recorded_at": time.time(),
        "code_state": code_state(project, args.run_dir),
    }
    save(args.run_dir, run)
    print(f"{args.kind} 검사: exit {result.returncode} (로그 {log})")
    return 0 if result.returncode == 0 else 1


class Gate:
    def __init__(self):
        self.failures = []
        self.warnings = []

    def need(self, condition, message):
        if not condition:
            self.failures.append(message)
        return bool(condition)

    def warn(self, condition, message):
        if not condition:
            self.warnings.append(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def better(direction, value, other):
    return value < other if direction == "lower" else value > other


def meets(direction, value, goal):
    return value <= goal if direction == "lower" else value >= goal


def measurement(gate, run, label):
    item = run["measurements"].get(label)
    if not gate.need(item, f"{label} 측정 기록 없음"):
        return None
    gate.need(
        len(item["samples"]) >= MIN_RUNS,
        f"{label} 측정 횟수 부족 ({len(item['samples'])} < {MIN_RUNS})",
    )
    return item


def warn_load(gate, item, label):
    gate.warn(
        item.get("load1", 0) <= item.get("cpus", 1),
        f"{label} 측정 시 시스템 부하 {item.get('load1', 0):.1f} > CPU {item.get('cpus', 1)}개",
    )


def gate_spec(run):
    gate = Gate()
    spec = run["spec"]
    for field in ("target", "metric", "percentile", "unit", "device", "test_command"):
        gate.need(text(spec.get(field)), f"spec.{field} 없음")
    gate.need(spec.get("direction") in ("lower", "higher"), "spec.direction은 lower 또는 higher")
    gate.need(number(spec.get("goal")), "spec.goal 숫자 없음")
    gate.need(spec.get("build") == "production", "spec.build가 production이 아님")
    behavior = spec.get("behavior")
    gate.need(
        isinstance(behavior, list) and any(text(x) for x in behavior),
        "spec.behavior(지켜야 할 동작) 없음",
    )
    return gate


def gate_baseline(run):
    gate = Gate()
    item = measurement(gate, run, "baseline")
    spec = run["spec"]
    if item and number(spec.get("goal")) and spec.get("direction") in ("lower", "higher"):
        gate.need(
            not meets(spec["direction"], item["median"], spec["goal"]),
            f"기준선 {item['median']:g}이 이미 목표 {spec['goal']:g}를 만족함",
        )
    if item and item.get("goal") != spec.get("goal"):
        gate.need(
            text(spec.get("goal_change_reason")),
            f"기준선 측정 후 목표가 {item.get('goal')}에서 {spec.get('goal')}로 바뀜. "
            "사용자가 승인했다면 spec.goal_change_reason에 적으세요.",
        )
    return gate


def gate_diagnose(run):
    gate = Gate()
    diagnosis = run["diagnosis"]
    segments = diagnosis.get("segments")
    gate.need(diagnosis.get("classification") in CLASSIFICATIONS, "diagnosis.classification이 분류표에 없음")
    gate.need(text(diagnosis.get("evidence")), "diagnosis.evidence 없음")
    if not gate.need(isinstance(segments, list) and segments, "diagnosis.segments 없음"):
        return gate
    valid = all(
        isinstance(x, dict) and text(x.get("name")) and number(x.get("ms"))
        and x.get("source") in ("measured", "estimated", "unknown")
        for x in segments
    )
    if not gate.need(valid, "segments 항목에 name, ms, source 필요"):
        return gate
    target = next((x for x in segments if x["name"] == diagnosis.get("target_segment")), None)
    if gate.need(target, "target_segment가 segments에 없음"):
        gate.need(target["source"] == "measured", "대상 구간이 측정값이 아님")
        if target["ms"] < max(x["ms"] for x in segments):
            gate.need(text(diagnosis.get("target_reason")), "가장 큰 구간이 아닌데 target_reason 없음")
    baseline = run["measurements"].get("baseline")
    if baseline and run["spec"].get("unit") == "ms":
        total = sum(x["ms"] for x in segments)
        gate.need(
            0.75 * baseline["median"] <= total <= 1.25 * baseline["median"],
            f"구간 합 {total:g}이 기준선 {baseline['median']:g}의 75~125%를 벗어남",
        )
    return gate


def gate_decide(run):
    gate = Gate()
    decision = run["decision"]
    diagnosis = run["diagnosis"]
    rung = decision.get("rung")
    swap = decision.get("swap")
    gate.need(rung in (1, 2, 3, 4, 5, 6), "decision.rung은 1~6")
    gate.need(text(decision.get("action")), "decision.action 없음")
    gate.need(swap in ("adopt", "hold", "unnecessary"), "decision.swap은 adopt, hold, unnecessary")
    gate.need((rung == 6) == (swap == "adopt"), "rung 6과 swap adopt는 함께 쓰여야 함")
    max_gain = decision.get("max_gain")
    target = next(
        (x for x in diagnosis.get("segments") or [] if isinstance(x, dict)
         and x.get("name") == diagnosis.get("target_segment")),
        None,
    )
    baseline = run["measurements"].get("baseline")
    goal = run["spec"].get("goal")
    if gate.need(number(max_gain), "decision.max_gain 숫자 없음") and target and number(target.get("ms")):
        gate.need(max_gain <= target["ms"], f"최대 이득 {max_gain:g}이 대상 구간 {target['ms']:g}보다 큼")
        if baseline and number(goal) and max_gain < abs(baseline["median"] - goal):
            gate.need(text(decision.get("gap_note")), "최대 이득이 목표 차이보다 작은데 gap_note 없음")
    if swap == "adopt":
        gate.need(
            diagnosis.get("classification") in SWAP_CLASSIFICATIONS,
            f"분류 {diagnosis.get('classification')}는 교체 대상이 아님",
        )
        for field in ("cheaper_attempts", "narrow_boundary", "net_gain"):
            gate.need(text((decision.get("gate") or {}).get(field)), f"decision.gate.{field} 없음")
    elif swap in ("hold", "unnecessary"):
        gate.need(text(decision.get("swap_reason")), "decision.swap_reason 없음")
    return gate


def gate_change(run):
    gate = Gate()
    change = run["change"]
    gate.need(text(change.get("summary")), "change.summary 없음")
    files = change.get("files")
    if gate.need(isinstance(files, list) and files, "change.files 없음"):
        for name in files:
            gate.need(
                os.path.exists(os.path.join(run["meta"]["project"], name)),
                f"변경 파일 없음: {name}",
            )
    return gate


def gate_spec_check(run, run_dir):
    gate = Gate()
    check = run["checks"].get("behavior")
    if not gate.need(check, "behavior 검사 기록 없음"):
        return gate
    gate.need(check["exit_code"] == 0, f"behavior 검사 실패 (exit {check['exit_code']})")
    gate.need(os.path.exists(os.path.join(run_dir, check["log"])), "검사 로그 파일 없음")
    baseline = run["measurements"].get("baseline")
    if baseline:
        gate.need(check["recorded_at"] > baseline["recorded_at"], "검사가 기준선보다 먼저 실행됨")
    current = code_state(run["meta"]["project"], run_dir)
    gate.warn(current is not None, "git 저장소가 아니어서 코드 변경 여부를 확인하지 못함")
    if current is not None:
        gate.need(check["code_state"] == current, "검사 후 코드가 바뀜. spec-check를 다시 실행하세요.")
    return gate


def gate_perf_check(run, run_dir):
    gate = Gate()
    after = measurement(gate, run, "after")
    baseline = run["measurements"].get("baseline")
    spec = run["spec"]
    direction = spec.get("direction")
    if not after or not baseline or direction not in ("lower", "higher"):
        gate.need(baseline, "baseline 측정 기록 없음")
        return gate
    warn_load(gate, baseline, "baseline")
    warn_load(gate, after, "after")
    gate.need(after["condition"] == baseline["condition"], "기준선과 측정 조건이 다름")
    gate.need(after["recorded_at"] > baseline["recorded_at"], "after가 기준선보다 먼저 측정됨")
    delta = abs(baseline["median"] - after["median"])
    noise = 2 * max(baseline["mad"], after["mad"])
    gate.need(better(direction, after["median"], baseline["median"]), "기준선보다 개선되지 않음")
    gate.need(delta > noise, f"개선폭 {delta:g}이 노이즈 범위 {noise:g} 이내")
    if number(spec.get("goal")):
        gate.need(
            meets(direction, after["median"], spec["goal"]),
            f"수정 후 {after['median']:g}이 목표 {spec['goal']:g}에 미달",
        )
    current = code_state(run["meta"]["project"], run_dir)
    if current is not None:
        gate.need(after["code_state"] == current, "측정 후 코드가 바뀜. measure after를 다시 실행하세요.")
        if baseline["code_state"] is not None:
            gate.need(after["code_state"] != baseline["code_state"], "기준선과 코드가 같음. 변경이 반영되지 않음")
    return gate


def gate_swap(run, run_dir):
    gate = Gate()
    swap = run["swap"]
    if run["decision"].get("swap") != "adopt":
        gate.need(text(swap.get("skipped_reason")), "교체하지 않은 이유(swap.skipped_reason) 없음")
        return gate
    for field in ("slot", "fallback"):
        gate.need(text(swap.get(field)), f"swap.{field} 없음")
    interface = swap.get("interface_file")
    if gate.need(text(interface), "swap.interface_file 없음"):
        gate.need(
            os.path.exists(os.path.join(run["meta"]["project"], interface)),
            f"인터페이스 파일 없음: {interface}",
        )
    required = SWAP_COSTS.get(swap.get("location"))
    if gate.need(required, "swap.location은 browser 또는 server"):
        missing = required - set(swap.get("cost_included") or [])
        gate.need(not missing, f"총비용 누락: {sorted(missing)}")
    compat = run["checks"].get("compat")
    if gate.need(compat, "compat 검사 기록 없음"):
        gate.need(compat["exit_code"] == 0, f"compat 검사 실패 (exit {compat['exit_code']})")
        current = code_state(run["meta"]["project"], run_dir)
        if current is not None:
            gate.need(compat["code_state"] == current, "compat 검사 후 코드가 바뀜")
    ts_best = measurement(gate, run, "ts_best")
    after = run["measurements"].get("after")
    direction = run["spec"].get("direction")
    if ts_best and after and direction in ("lower", "higher"):
        gate.need(ts_best["condition"] == after["condition"], "TypeScript 비교 조건이 다름")
        gate.need(
            better(direction, after["median"], ts_best["median"]),
            f"교체본 {after['median']:g}이 TypeScript 최선 {ts_best['median']:g}보다 낫지 않음",
        )
        delta = abs(ts_best["median"] - after["median"])
        noise = 2 * max(ts_best["mad"], after["mad"])
        gate.need(delta > noise, f"교체 이득 {delta:g}이 노이즈 범위 {noise:g} 이내")
        warn_load(gate, ts_best, "ts_best")
    return gate


def gate_rollout(run):
    gate = Gate()
    rollout = run["rollout"]
    strategy = rollout.get("strategy")
    gate.need(strategy in ("flag", "canary", "direct"), "rollout.strategy는 flag, canary, direct")
    gate.need(text(rollout.get("rollback")), "rollout.rollback 없음")
    if strategy == "direct":
        gate.need(text(rollout.get("reason")), "direct에는 rollout.reason 필요")
        gate.need(run["decision"].get("swap") != "adopt", "부품 교체는 direct로 적용할 수 없음")
    return gate


def gate_guard(run):
    gate = Gate()
    guard = run["guard"]
    gate.need(text(guard.get("kind")), "guard.kind 없음")
    artifacts = guard.get("artifacts")
    if gate.need(isinstance(artifacts, list) and artifacts, "guard.artifacts 없음"):
        for name in artifacts:
            gate.need(
                os.path.exists(os.path.join(run["meta"]["project"], name)),
                f"회귀 방지 파일 없음: {name}",
            )
    return gate


def gate_report(run_dir):
    gate = Gate()
    path = os.path.join(run_dir, "REPORT.md")
    if gate.need(os.path.exists(path), "REPORT.md 없음"):
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        for section in REPORT_SECTIONS:
            gate.need(section in content, f"보고서 항목 없음: {section}")
    return gate


def cmd_check(args):
    run = load(args.run_dir)
    stages = [
        ("spec", gate_spec(run)),
        ("baseline", gate_baseline(run)),
        ("diagnose", gate_diagnose(run)),
        ("decide", gate_decide(run)),
        ("change", gate_change(run)),
        ("guard", gate_guard(run)),
        ("spec-check", gate_spec_check(run, args.run_dir)),
        ("perf-check", gate_perf_check(run, args.run_dir)),
        ("swap", gate_swap(run, args.run_dir)),
        ("rollout", gate_rollout(run)),
        ("report", gate_report(args.run_dir)),
    ]
    failed = 0
    for name, gate in stages:
        print(f"{'FAIL' if gate.failures else 'PASS'}  {name}")
        failed += 1 if gate.failures else 0
        for message in gate.failures:
            print(f"      - {message}")
        for message in gate.warnings:
            print(f"      ! {message}")
    print("PIPELINE COMPLETE" if not failed else f"PIPELINE INCOMPLETE ({failed}개 단계 실패)")
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="action", required=True)

    init = commands.add_parser("init")
    init.add_argument("run_dir")
    init.add_argument("--project", required=True)
    init.add_argument("--name", required=True)
    init.set_defaults(handler=cmd_init)

    set_section = commands.add_parser("set")
    set_section.add_argument("run_dir")
    set_section.add_argument("section", choices=EDITABLE_SECTIONS)
    set_section.add_argument("value", nargs="?")
    set_section.add_argument("--file")
    set_section.set_defaults(handler=cmd_set)

    measure = commands.add_parser("measure")
    measure.add_argument("run_dir")
    measure.add_argument("label", choices=["baseline", "after", "ts_best"])
    measure.add_argument("--condition", required=True)
    measure.add_argument("--runs", type=int, default=MIN_RUNS)
    measure.add_argument("--samples-file")
    measure.add_argument("--source-note")
    measure.set_defaults(handler=cmd_measure)

    spec_check = commands.add_parser("spec-check")
    spec_check.add_argument("run_dir")
    spec_check.add_argument("--kind", choices=["behavior", "compat"], default="behavior")
    spec_check.set_defaults(handler=cmd_spec_check)

    check = commands.add_parser("check")
    check.add_argument("run_dir")
    check.set_defaults(handler=cmd_check)

    # 실행할 명령의 옵션이 파서에 섞이지 않도록 첫 "--"에서 미리 나눈다.
    argv = sys.argv[1:]
    split = argv.index("--") if "--" in argv else len(argv)
    args = parser.parse_args(argv[:split])
    args.command = argv[split + 1:]
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
