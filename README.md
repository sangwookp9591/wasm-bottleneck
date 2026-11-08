# wasm-bottleneck

서비스를 컴퓨터 조립처럼 다루는 Claude Code 스킬입니다. 점검으로 느린 부품을 찾고, 측정으로 필요성이 확인된 부품만 같은 규격의 Rust/WASM 부품으로 갈아 끼운 뒤 수치로 검증합니다.

## 하는 일

1. 문제를 지표와 목표값으로 정의합니다.
2. 네트워크, 서버, DB, 스크립트, 렌더링으로 시간을 나눕니다.
3. 프로덕션 조건에서 재현하고 병목을 분류합니다.
4. 최대 이득을 계산하고 싼 해결책부터 적용합니다.
5. 조건을 만족하는 구간만 Rust/WASM 부품으로 교체합니다.
6. 기존 구현과 같은 조건으로 비교하고 회귀를 막습니다.

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
| `SKILL.md` | 진단 절차, 분류표, 교체 판단 기준, 보고 형식 |
| `references/profiling.md` | 계층별 측정 방법 |
| `references/part-swap.md` | 슬롯 설계와 교체 절차 |
| `references/wasm-build-serve.md` | WASM 빌드와 서빙 |
| `references/react-integration.md` | React, Next.js, Worker 통합 |
| `scripts/check_wasm_serving.sh` | 배포된 `.wasm`의 응답 헤더 점검 |

```bash
scripts/check_wasm_serving.sh https://cdn.example.com/app.3f9a1c7b.wasm https://app.example.com
```
