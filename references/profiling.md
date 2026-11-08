# 계층별 측정 방법

병목으로 의심되는 계층의 절만 읽는다.

## 실사용자 (RUM)

`web-vitals`의 attribution 빌드로 INP를 세 구간으로 나눠 수집한다.

```ts
import { onINP } from "web-vitals/attribution";

onINP(({ value, attribution: a }) => {
  navigator.sendBeacon("/rum", JSON.stringify({
    value,
    target: a.interactionTarget,
    inputDelay: a.inputDelay,
    processing: a.processingDuration,
    presentation: a.presentationDelay,
  }));
});
```

| 큰 구간 | 의미 | 다음 확인 |
|---|---|---|
| inputDelay | 다른 작업이 메인 스레드를 점유 | Long Animation Frames의 스크립트 출처 |
| processing | 핸들러, 상태 업데이트가 느림 | Performance 패널, React Profiler |
| presentation | 레이아웃, 페인트가 느림 | DOM 크기, 강제 리플로우, 큰 페인트 영역 |

기기 등급, 라우트, 지역, 배포 버전으로 나눠서 본다. 전체 평균에서는 특정 기기의 문제가 사라진다.

## 메인 스레드

Chrome Performance 패널에서 CPU 스로틀을 걸고 녹화한다.

- 50ms를 넘는 작업을 찾고 Bottom-Up 탭에서 self time 순으로 정렬한다. total time은 호출한 함수까지 포함해서 원인을 흐린다.
- 보라색 Layout이 스크립트 안에 반복되면 강제 리플로우다.
- 사용자 코드에 `performance.mark`와 `performance.measure`를 넣으면 트레이스에서 구간을 바로 찾을 수 있다.

## React

React Profiler로 커밋 시간과 렌더 원인을 본다. props가 그대로인데 렌더되는 컴포넌트, 한 번의 입력으로 생기는 연쇄 커밋, 긴 목록의 전체 렌더를 찾는다. 프로덕션 수치가 필요하면 프로파일링 빌드를 쓴다.

## 네트워크와 번들

- Network 패널에서 직렬로 이어지는 요청, 압축되지 않은 응답, 캐시 미스를 찾는다.
- bundle analyzer로 첫 로딩 번들의 큰 의존성을 찾는다.
- 응답에 `Server-Timing` 헤더를 넣으면 서버 내부 시간이 브라우저 측정과 연결된다.

## 메모리

- 누수: 같은 동작을 반복하고 힙 스냅샷을 비교한다. 강제 GC 후에도 증가하는 객체의 retainer를 추적한다. 해제되지 않은 이벤트 리스너, 타이머, 전역 캐시, 분리된 DOM이 흔한 원인이다.
- GC 압력: Allocation 타임라인에서 할당이 많은 함수를 찾는다.
- WASM: 선형 메모리는 늘어나기만 하고 줄지 않는다. `free()` 누락과 최고 사용량을 구분해서 본다.

## 서버와 DB

- 분산 트레이싱(OpenTelemetry)으로 요청 안의 구간을 나눈다.
- DB는 슬로우 쿼리 로그와 `EXPLAIN ANALYZE`로 확인하고, 요청당 쿼리 수로 N+1을 찾는다.
- p50은 정상인데 p95만 나쁘면 대기열, 커넥션 풀, GC, 락 경합을 의심한다. 사용률이 포화에 가까워질수록 대기 시간은 급격히 늘어난다.
- Node는 event loop delay를 측정하고, CPU 프로파일은 `node --cpu-prof`로 뜬다.

## Rust

프로덕션과 같은 최적화에 심볼만 남긴 프로파일을 쓴다.

```toml
[profile.profiling]
inherits = "release"
debug = true
strip = false
```

| 목적 | 도구 |
|---|---|
| CPU 프로파일 | `samply`, `cargo flamegraph` |
| 힙 할당 | `dhat`, `heaptrack` |
| 비동기 작업과 지연 | `tokio-console`, `tracing` |
| 함수 단위 비교 | `criterion` |

## WASM

- 함수 이름이 보이도록 프로파일링 빌드는 `wasm-bindgen --keep-debug`로 만들고 `wasm-opt`에 `-g`를 준다. 이렇게 하면 Chrome Performance 패널에 Rust 함수 이름이 나온다.
- 용량 원인은 `twiggy top`, `twiggy dominators`로 찾는다. 이름이 있는 빌드를 대상으로 한다.
- JS와 WASM 경계를 `performance.measure`로 감싸서 실행 시간과 데이터 전달 시간을 분리한다.
