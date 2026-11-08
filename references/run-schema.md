# run.json 구조

`init`이 뼈대를 만든다. 아래 필드는 단계마다 `pipeline.py set <run_dir> <섹션> '<JSON>'`으로 채운다. 값은 기존 섹션에 병합되며, 긴 내용은 `--file`로 넘긴다. `measurements`, `checks`, `meta`, `history`는 스크립트가 쓰는 영역이므로 수정하지 않는다. 같은 라벨을 다시 측정하면 이전 기록은 `history`에 남는다.

```json
{
  "spec": {
    "target": "필터 클릭",
    "metric": "duration",
    "percentile": "p75",
    "unit": "ms",
    "direction": "lower",
    "goal": 200,
    "build": "production",
    "device": "M2, CPU 4x throttle",
    "behavior": ["필터 결과와 순서가 유지된다"],
    "test_command": "npm test"
  },
  "diagnosis": {
    "segments": [
      { "name": "filter 연산", "ms": 780, "source": "measured" },
      { "name": "렌더링", "ms": 20, "source": "estimated" }
    ],
    "target_segment": "filter 연산",
    "target_reason": "",
    "classification": "cpu",
    "evidence": "Performance 패널 Bottom-Up에서 dedupe의 self time 97%"
  },
  "decision": {
    "rung": 4,
    "action": "중첩 루프를 Set 조회로 교체",
    "max_gain": 780,
    "gap_note": "",
    "swap": "unnecessary",
    "swap_reason": "4단계로 목표 달성",
    "gate": {}
  },
  "change": { "summary": "dedupe를 O(n)으로 변경", "files": ["src/dedupe.js"] },
  "swap": { "skipped_reason": "교체 불필요" },
  "rollout": { "strategy": "direct", "reason": "동작이 동일한 내부 알고리즘 변경", "rollback": "커밋 되돌리기" },
  "guard": { "kind": "CI 벤치마크 임계값", "artifacts": ["bench/budget.json"] }
}
```

## 필드 규칙

- `spec.build`는 `production`이어야 한다. `spec.direction`은 `lower` 또는 `higher`다.
- `segments[].source`는 `measured`, `estimated`, `unknown` 중 하나다. 단위가 `ms`면 구간 합은 기준선 중앙값의 75~125%여야 한다. 구간을 다시 쪼개거나 다시 측정해서 맞춘다.
- `target_segment`가 가장 큰 구간이 아니면 `target_reason`을 적는다.
- `decision.rung`은 1~6이고, 6은 `swap: "adopt"`와 짝이다.
- `change.files`, `guard.artifacts`, `swap.interface_file`은 `--project` 기준 경로이고 실제로 존재해야 한다.
- `rollout.strategy`는 `flag`, `canary`, `direct` 중 하나다. `direct`는 `reason`이 필요하고, 부품 교체에는 쓸 수 없다.

## 교체할 때 추가되는 필드

```json
{
  "decision": {
    "rung": 6,
    "swap": "adopt",
    "gate": {
      "cheaper_attempts": "TypedArray 정렬 + Worker로 2.1초, 목표 1초 미달",
      "narrow_boundary": "Float64Array 입력과 출력",
      "net_gain": "실행 1.4초 절약, 다운로드와 컴파일 180ms"
    }
  },
  "swap": {
    "slot": "SortEngine",
    "location": "browser",
    "interface_file": "src/engine.ts",
    "fallback": "로드 실패와 panic 시 tsEngine 사용",
    "cost_included": ["download", "compile", "transfer", "execute"]
  }
}
```

`location`이 `server`면 `cost_included`에 `transfer`, `execute`만 있어도 된다.
