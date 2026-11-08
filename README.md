# wasm-bottleneck

서비스를 컴퓨터 조립처럼 다루는 Claude Code 스킬입니다. 점검으로 느린 부품을 찾고, 측정으로 필요성이 확인된 부품만 같은 규격의 Rust/WASM 부품으로 갈아 끼운 뒤 수치로 검증합니다.

## 파이프라인

| # | 단계 | 통과 조건 |
|---|---|---|
| 1 | spec | 지표, 목표, 프로덕션 조건, 지켜야 할 동작 정의 |
| 2 | baseline | 목표를 먼저 정한 뒤 5회 이상 측정 |
| 3 | diagnose | 구간 합이 기준선을 설명하고, 대상 구간이 측정됨 |
| 4 | decide | 최대 이득 계산, 싼 해결책부터 선택, 교체 조건 확인 |
| 5 | change | 결정한 조치 적용 |
| 6 | guard | 회귀 방지 설정 파일 추가 |
| 7 | spec-check | 최종 코드에서 동작 검사 통과 |
| 8 | perf-check | 같은 조건, 노이즈를 넘는 개선, 목표 달성 |
| 9 | swap | 교체 시 호환성, TypeScript 최선 구현 대비 우위, 총비용, 복구 경로 |
| 10 | rollout | 적용 방식과 되돌리는 방법 |
| 11 | report | 필수 항목을 갖춘 보고서 |

`scripts/pipeline.py`가 측정과 동작 검사를 직접 실행해 기록하고, 코드 지문을 남깁니다. 단계가 빠지거나, 검사 뒤에 코드가 바뀌거나, 측정 후 목표를 임의로 바꾸거나, 개선이 노이즈 범위면 `check`가 실패합니다.

언어를 바꿔도 줄지 않는 병목(네트워크, DOM, 쿼리 대기 등)에는 교체를 권하지 않습니다.

## 설치

모든 프로젝트에서 쓰려면 다음을 실행합니다.

```bash
git clone https://github.com/sangwookp9591/wasm-bottleneck.git ~/.claude/skills/wasm-bottleneck
```

특정 프로젝트에서만 쓰려면 프로젝트의 `.claude/skills/wasm-bottleneck`에 클론합니다.

## 사용 예

```
필터 클릭이 1.2초 걸려. 병목 찾아서 고쳐줘.
200만 행 정렬이 느린데 이 함수만 Rust WASM으로 갈아 끼울 가치가 있어?
```

## 구성

| 파일 | 내용 |
|---|---|
| `SKILL.md` | 파이프라인, 분류표, 교체 판단 기준, 보고 형식 |
| `scripts/pipeline.py` | 실행 기록과 단계별 게이트 검사 |
| `tests/test_pipeline.py` | 게이트 테스트 (`python3 -m unittest discover -s tests`) |
| `references/run-schema.md` | 실행 기록 파일 구조 |
| `references/profiling.md` | 계층별 측정 방법 |
| `references/part-swap.md` | 슬롯 설계와 교체 절차 |
| `references/wasm-build-serve.md` | WASM 빌드와 서빙 |
| `references/react-integration.md` | React, Next.js, Worker 통합 |
| `scripts/check_wasm_serving.sh` | 배포된 `.wasm`의 응답 헤더 점검 |

```bash
scripts/check_wasm_serving.sh https://cdn.example.com/app.3f9a1c7b.wasm https://app.example.com
```

## 라이선스

[MIT](LICENSE)
