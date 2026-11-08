# 부품 교체 설계

느린 구현을 호출 코드에서 분리해 슬롯으로 만들고, 같은 규격의 Rust/WASM 부품을 꽂는다. 호출 코드가 구현을 모르게 해야 교체와 복구가 설정 변경만으로 끝난다.

## 슬롯 목록

| 슬롯 | 점검 신호 | 교체 부품 | 교체해도 소용없는 경우 |
|---|---|---|---|
| 연산 (정렬, 필터, 집계) | 순수 함수의 self time이 큼 | WASM + Worker | 대부분이 리렌더 시간 |
| 파서, 직렬화 (CSV, JSON, 프로토콜) | 파싱 시간과 할당이 큼 | WASM + Worker, 서버는 napi-rs | 입력 대기가 대부분 |
| 데이터 저장 구조 | GC 멈춤, 메모리 과다 | 선형 메모리의 컬럼 저장소 | 누수가 원인 |
| 미디어, 압축, 암호화 | 바이트 처리가 CPU를 점유 | WASM (SIMD) | 브라우저 내장 API가 이미 있음 |
| 렌더러 | 대량 요소로 프레임 저하 | Rust + wgpu canvas | 화면에 보이는 요소가 적음 |
| 서버 핫패스 | CPU 포화와 함께 p95 상승 | napi-rs, 분리된 Rust 서비스 | DB, 외부 API 대기 |

브라우저에 내장된 `CompressionStream`, Web Crypto 같은 네이티브 API가 있으면 그것이 가장 싼 부품이다. 추가 다운로드가 없고 대체로 충분히 빠르다.

## 규격 정의

인터페이스는 부품 사이의 소켓이다. 입력과 출력을 TypedArray처럼 단순하게 두고, 처음부터 비동기로 만든다. 그래야 Worker나 WASM으로 바꿔도 호출 코드가 그대로 유지된다.

```ts
export interface SortEngine {
  readonly name: "ts" | "wasm";
  sort(input: Float64Array): Promise<Float64Array>;
}

export async function getSortEngine(size: number): Promise<SortEngine> {
  if (size < WASM_MIN_ROWS || !flags.wasmSort) return tsEngine;
  try {
    return await loadWasmEngine();
  } catch (error) {
    reportEngineLoadFailure(error);
    return tsEngine;
  }
}
```

`WASM_MIN_ROWS`는 실측으로 정한다. 작은 입력은 기존 부품이 처리해서 다운로드 자체를 없앤다.

## 교체 절차

1. **슬롯 분리:** 동작을 바꾸지 않고 기존 구현을 인터페이스 뒤로 옮긴다. 여기서 성능이 변하면 안 된다.
2. **호환성 검증:** 같은 입력에 두 부품의 결과가 같은지 골든 데이터와 property test로 확인한다. 언어가 바뀌면 NaN, 정렬 안정성, 문자열 비교(`Intl.Collator`), 부동소수점 포맷, 정수 범위(JS의 2^53), UTF-16과 UTF-8의 길이 차이에서 결과가 달라지기 쉽다.
3. **벤치마크:** SKILL.md 8단계 조건으로 비교한다.
4. **단계적 적용:** 기능 플래그로 일부 사용자부터 켠다. RUM에 `engine` 값을 태그로 남겨 같은 기간에 두 부품을 비교한다.
5. **복구 경로 유지:** 로드 실패, WASM panic, 메모리 부족 시 기존 부품으로 돌아가게 한다. panic이 난 WASM 인스턴스는 상태를 믿을 수 없으므로 재사용하지 않고 새로 만든다.
6. **기존 부품 정리:** 충분히 안정된 뒤에도 대체 경로가 필요한지 판단하고, 필요 없으면 제거한다. 두 구현을 유지하는 것도 비용이다.

## 주의

- 교체 후에는 다음 병목이 드러난다. 다시 점검부터 시작하고, 목표에 도달하면 멈춘다.
- 부품 사이의 연결도 비용이다. 데이터 전달이 교체로 얻은 시간을 잠식하면 슬롯 경계를 더 크게 잡아 호출 횟수를 줄인다.
- 부품을 너무 많이 만들지 않는다. 슬롯마다 빌드, 배포, 호환성 검증 비용이 붙는다.
