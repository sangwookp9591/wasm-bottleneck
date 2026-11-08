# wasm-bottleneck

서비스를 컴퓨터 조립처럼 다루는 Claude Code 스킬입니다. 점검으로 느린 부품을 찾고, 측정으로 필요성이 확인된 부품만 같은 규격의 Rust/WASM 부품으로 갈아 끼운 뒤, 동작과 성능을 수치로 검증합니다.

언어를 바꿔도 줄지 않는 병목(네트워크, DOM, 쿼리 대기 등)에는 교체를 권하지 않습니다. 알고리즘 수정으로 끝나는 문제라면 "WASM 불필요"라고 판단합니다.

## 목차

- [요구 사항](#요구-사항)
- [설치](#설치)
- [설치 확인](#설치-확인)
- [업데이트와 삭제](#업데이트와-삭제)
- [사용법](#사용법)
- [파이프라인](#파이프라인)
- [직접 실행하기](#직접-실행하기)
- [WASM 서빙 점검](#wasm-서빙-점검)
- [문제 해결](#문제-해결)
- [파일 구성](#파일-구성)
- [검증 범위](#검증-범위)
- [라이선스](#라이선스)

## 요구 사항

기본 파이프라인에 필요한 도구입니다.

| 도구 | 용도 |
|---|---|
| [Claude Code](https://claude.com/claude-code) | 스킬 실행 |
| Python 3 | `scripts/pipeline.py` 실행 (추가 패키지 없음) |
| git | 코드 변경 감지. 없으면 경고만 표시하고 해당 검사를 건너뜀 |
| curl | `scripts/check_wasm_serving.sh` 실행 |

Rust/WASM 부품으로 교체할 때만 아래가 추가로 필요합니다.

```bash
# Rust 설치 후 WASM 타깃 추가
rustup target add wasm32-unknown-unknown

# wasm-bindgen CLI. 버전은 Cargo.lock의 wasm-bindgen과 정확히 같아야 합니다.
cargo install wasm-bindgen-cli --version <프로젝트의-wasm-bindgen-버전>

# 선택: 용량 최적화와 압축 (macOS)
brew install binaryen brotli
```

## 설치

### 모든 프로젝트에서 사용

```bash
git clone https://github.com/sangwookp9591/wasm-bottleneck.git ~/.claude/skills/wasm-bottleneck
```

### 특정 프로젝트에서만 사용

프로젝트 루트에서 실행합니다.

```bash
git clone https://github.com/sangwookp9591/wasm-bottleneck.git .claude/skills/wasm-bottleneck
rm -rf .claude/skills/wasm-bottleneck/.git
git add .claude/skills/wasm-bottleneck
```

`.git`을 지우면 스킬 파일이 프로젝트에 일반 파일로 포함되어 팀원도 같은 버전을 쓰게 됩니다.

### 실행 기록 관리

파이프라인은 프로젝트의 `.perf/<작업명>/`에 측정 기록과 보고서를 남깁니다. 저장소에 남기지 않으려면 `.gitignore`에 추가하세요.

```bash
echo '.perf/' >> .gitignore
```

## 설치 확인

Claude Code를 새로 시작한 뒤 `/wasm-bottleneck`을 입력해 스킬이 목록에 나오는지 확인합니다. 스크립트와 게이트는 아래 테스트로 확인할 수 있습니다.

```bash
cd ~/.claude/skills/wasm-bottleneck
python3 -m unittest discover -s tests
```

## 업데이트와 삭제

```bash
# 업데이트 (전역 설치 기준)
git -C ~/.claude/skills/wasm-bottleneck pull

# 삭제
rm -rf ~/.claude/skills/wasm-bottleneck
```

## 사용법

성능 문제를 평소처럼 말하면 스킬이 자동으로 쓰입니다. `/wasm-bottleneck`으로 직접 호출해도 됩니다.

```
필터 클릭이 1.2초 걸려. 병목 찾아서 200ms 이하로 만들어줘. 필터 결과는 그대로 유지돼야 해.
```

```
/wasm-bottleneck 200만 행 정렬이 느린데 이 함수만 Rust WASM으로 갈아 끼울 가치가 있어?
```

목표값, 측정 방법(벤치마크 명령이나 RUM 데이터), 지켜야 할 동작을 함께 알려 주면 바로 진행할 수 있습니다. 측정할 수단이 없으면 스킬은 수치를 지어내지 않고 무엇이 필요한지 알린 뒤 멈춥니다.

## 파이프라인

| # | 단계 | 통과 조건 |
|---|---|---|
| 1 | spec | 지표, 목표, 프로덕션 조건, 지켜야 할 동작 정의 |
| 2 | baseline | 목표를 먼저 정한 뒤 5회 이상 측정 |
| 3 | diagnose | 구간 합이 기준선의 75~125%이고, 대상 구간이 측정값임 |
| 4 | decide | 최대 이득 계산, 싼 해결책부터 선택, 교체 조건 확인 |
| 5 | change | 결정한 조치 적용 |
| 6 | guard | 회귀 방지 설정 파일 추가 |
| 7 | spec-check | 최종 코드에서 동작 검사 통과 |
| 8 | perf-check | 같은 조건, 노이즈를 넘는 개선, 목표 달성 |
| 9 | swap | 교체 시 호환성, TypeScript 최선 구현 대비 우위, 총비용, 복구 경로 |
| 10 | rollout | 적용 방식과 되돌리는 방법 |
| 11 | report | 필수 항목을 갖춘 보고서 |

해결책은 싼 것부터 고릅니다.

1. 작업을 없앤다.
2. 캐시하거나 미룬다.
3. 묶어서 처리한다.
4. 알고리즘과 자료구조를 바꾼다.
5. Worker나 별도 프로세스로 옮긴다.
6. Rust/WASM 부품으로 교체한다.

## 직접 실행하기

보통은 Claude가 이 명령들을 실행하지만, 직접 돌릴 수도 있습니다. 프로젝트 루트에서 실행합니다.

벤치마크 명령은 마지막 출력 줄에 숫자 하나를 내야 합니다. 명령은 셸 없이 실행되므로 환경 변수나 파이프가 필요하면 `env`나 `sh -c`를 쓰세요.

```bash
P=~/.claude/skills/wasm-bottleneck/scripts/pipeline.py
RUN=.perf/filter

python3 "$P" init "$RUN" --project . --name "필터 클릭"

# 1. 스펙: 기준선을 재기 전에 목표를 정합니다.
python3 "$P" set "$RUN" spec '{
  "target": "필터 클릭", "metric": "duration", "percentile": "로컬 측정 중앙값",
  "unit": "ms", "direction": "lower", "goal": 200, "build": "production",
  "device": "M2, CPU 스로틀 없음", "behavior": ["필터 결과와 순서 유지"],
  "test_command": "npm test"
}'

# 2. 기준선
python3 "$P" measure "$RUN" baseline --condition "production,local" --runs 5 -- node bench.js

# 3. 진단
python3 "$P" set "$RUN" diagnosis '{
  "segments": [
    {"name": "필터 연산", "ms": 950, "source": "measured"},
    {"name": "렌더링", "ms": 50, "source": "estimated"}
  ],
  "target_segment": "필터 연산", "classification": "cpu",
  "evidence": "CPU 프로파일에서 filter 함수의 self time이 대부분"
}'

# 4. 결정
python3 "$P" set "$RUN" decision '{
  "rung": 4, "action": "중첩 루프를 Set 조회로 교체", "max_gain": 950,
  "swap": "unnecessary", "swap_reason": "알고리즘 수정으로 목표 달성 가능"
}'

# 5~6. 코드를 고치고 회귀 방지 파일을 추가합니다.
python3 "$P" set "$RUN" change '{"summary": "필터를 O(n)으로 변경", "files": ["src/filter.js"]}'
python3 "$P" set "$RUN" guard '{"kind": "CI 벤치마크 임계값", "artifacts": ["bench/budget.json"]}'

# 7~8. 최종 코드 검사
python3 "$P" spec-check "$RUN" -- npm test
python3 "$P" measure "$RUN" after --condition "production,local" --runs 5 -- node bench.js

# 9~10. 교체 여부와 적용 방식
python3 "$P" set "$RUN" swap '{"skipped_reason": "교체 불필요"}'
python3 "$P" set "$RUN" rollout '{
  "strategy": "direct", "reason": "동작이 같은 내부 변경", "rollback": "커밋 되돌리기"
}'

# 11. "$RUN/REPORT.md"를 작성한 뒤 전체 게이트를 검사합니다.
python3 "$P" check "$RUN"
```

`check`는 단계별 `PASS`, `FAIL`과 함께 마지막에 `PIPELINE COMPLETE` 또는 `PIPELINE INCOMPLETE`를 출력합니다. 종료 코드는 성공이 `0`, 게이트나 명령 실패가 `1`, 잘못된 사용이 `2`입니다.

RUM이나 브라우저 트레이스처럼 명령으로 재현할 수 없는 값은 숫자 배열 파일로 가져옵니다.

```bash
python3 "$P" measure "$RUN" baseline --condition "production,rum" \
  --samples-file samples.json --source-note "RUM 7일치 p75"
```

Rust/WASM으로 교체한다면 추가로 세 가지를 실행합니다. 부하 차이를 줄이기 위해 `ts_best`와 `after`는 연달아 측정합니다.

```bash
python3 "$P" spec-check "$RUN" --kind compat -- node --test compat.test.js
python3 "$P" measure "$RUN" ts_best --condition "production,local" --runs 21 -- env ENGINE=ts node bench.js
python3 "$P" measure "$RUN" after --condition "production,local" --runs 21 -- node bench.js
```

필드 전체 설명은 [`references/run-schema.md`](references/run-schema.md)에 있습니다. 전역 설치 외의 경로라면 `P`만 바꾸면 됩니다.

## WASM 서빙 점검

배포된 `.wasm`의 상태 코드, `Content-Type`, 압축, 캐시 헤더, 해시 파일명, CORS를 점검합니다.

```bash
~/.claude/skills/wasm-bottleneck/scripts/check_wasm_serving.sh \
  https://cdn.example.com/app.3f9a1c7b.wasm https://app.example.com
```

두 번째 인자인 페이지 origin은 선택이며, 지정하면 CORS도 확인합니다. 종료 코드는 문제 없음이 `0`, `FAIL` 있음이 `1`, 요청 불가나 잘못된 인자가 `2`입니다.

## 문제 해결

| 메시지 | 원인과 조치 |
|---|---|
| `기준선을 재기 전에 spec.goal을 정하세요` | `set`으로 목표를 먼저 기록합니다. 측정을 본 뒤 목표를 맞추는 일을 막기 위한 규칙입니다. |
| `검사 후 코드가 바뀜`, `측정 후 코드가 바뀜` | 최종 코드에서 `spec-check`와 `measure after`를 다시 실행합니다. 빌드 산출물이 원인이면 `.gitignore`에 추가합니다. |
| `구간 합 ...이 기준선 ...의 75~125%를 벗어남` | 구간을 다시 측정해 `diagnosis`를 갱신합니다. 기준선을 다시 쟀다면 구간도 다시 재야 합니다. |
| `개선폭 ...이 노이즈 범위 ... 이내` | 다른 작업을 멈추고 `--runs`를 늘려 다시 측정합니다. 그래도 같으면 실질적인 개선이 없는 것입니다. |
| `수정 후 ...이 목표 ...에 미달` | 다음 병목을 찾습니다. 더 줄일 곳이 없으면 미달 사실을 보고하고 목표 조정 여부를 결정합니다. |
| `기준선 측정 후 목표가 ...로 바뀜` | 목표 변경을 승인했다면 `spec.goal_change_reason`에 이유를 적습니다. |
| `교체 이득 ...이 노이즈 범위 ... 이내` | 교체본의 우위가 확인되지 않은 상태입니다. 다시 측정하거나 TypeScript 구현을 유지합니다. |
| `시스템 부하 ... > CPU ...개` | 경고입니다. 부하가 낮을 때 다시 측정하면 수치를 더 믿을 수 있습니다. |
| `마지막 출력 줄이 숫자가 아님` | 벤치마크가 마지막 줄에 숫자만 출력하게 고칩니다. |
| `run.json 없음` | `init`을 먼저 실행하고, 같은 실행 폴더 경로를 쓰는지 확인합니다. |

## 파일 구성

| 파일 | 내용 |
|---|---|
| `SKILL.md` | 파이프라인, 분류표, 교체 판단 기준, 보고 형식 |
| `scripts/pipeline.py` | 실행 기록과 단계별 게이트 검사 |
| `scripts/check_wasm_serving.sh` | 배포된 `.wasm`의 응답 헤더 점검 |
| `tests/test_pipeline.py` | 게이트 테스트 |
| `references/run-schema.md` | 실행 기록 파일 구조 |
| `references/profiling.md` | 계층별 측정 방법 |
| `references/part-swap.md` | 슬롯 설계와 교체 절차 |
| `references/wasm-build-serve.md` | WASM 빌드와 서빙 |
| `references/react-integration.md` | React, Next.js, Worker 통합 |

## 검증 범위

게이트 테스트와 Node 샘플 프로젝트(알고리즘 수정 경로, 실제 Rust WASM 교체 경로)에서 파이프라인을 확인했습니다. 실제 브라우저 측정, RUM 수집, React/Next.js 통합, 운영 CDN 대상 서빙 점검은 아직 실환경에서 검증하지 않았습니다.

## 라이선스

[MIT](LICENSE)
