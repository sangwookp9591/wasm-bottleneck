# WASM 빌드와 서빙

## 모듈 경계

- 기능별로 crate를 나눠 `.wasm`을 따로 만든다.
- 모듈마다 메모리와 표준 라이브러리 코드를 따로 가지므로, 항상 함께 쓰는 기능은 하나로 묶는다.
- API는 숫자와 TypedArray 위주로 설계한다. 호출 횟수를 줄이고 한 번에 많이 처리한다.
- Apache Arrow처럼 컬럼 형식 데이터는 경계 비용을 크게 줄인다.
- 앱 전체가 canvas를 차지한다면 GPUI를 고려할 수 있지만, React 안의 부품으로 쓸 거라면 Rust + wgpu가 맞다. GPUI 웹은 문서 소유 canvas와 단일 창을 전제로 하는 버전이 있으니 쓰는 버전의 코드를 확인한다.

## 빌드

```toml
[profile.release]
opt-level = "s"
lto = "fat"
codegen-units = 1
panic = "abort"
strip = true
```

```bash
cargo build --release --target wasm32-unknown-unknown
wasm-bindgen target/wasm32-unknown-unknown/release/app.wasm --target web --out-dir dist
wasm-opt dist/app_bg.wasm -Oz --all-features -o dist/app_bg.wasm
brotli -q 11 dist/app_bg.wasm
```

- `opt-level`은 `"s"`, `"z"`, `3`을 빌드해서 Brotli 압축 후 크기와 실행 시간을 비교해 정한다. 계산이 핵심인 모듈은 `3`과 `wasm-opt -O3`가 유리할 수 있다.
- SIMD가 효과 있는 연산은 `RUSTFLAGS="-C target-feature=+simd128"`로 비교한다. 구형 브라우저까지 지원한다면 비SIMD 빌드를 따로 둔다.
- `format!`, `serde`, 큰 제네릭 인스턴스, 정규식 라이브러리가 흔한 용량 원인이다.
- `wasm32`의 메모리 상한은 4GB이고, 실제 가능량은 기기마다 더 낮다. 대용량은 청크로 처리한다.

## 로딩

- `WebAssembly.instantiateStreaming`을 쓴다. wasm-bindgen이 만든 `init()`은 응답이 `application/wasm`이면 이를 사용한다.
- 첫 화면에 필요 없는 모듈은 `import()`로 라우트 진입이나 사용자 동작 시점에 불러온다.
- 쓸 가능성이 높으면 유휴 시간에 미리 받거나 `<link rel="preload" as="fetch" crossorigin>`을 건다.
- 입력이 작으면 TypeScript 경로로 처리해 다운로드를 건너뛴다. 기준 크기는 실측으로 정하고, 로드 실패 시 대체 경로로도 쓴다.
- 재방문은 Service Worker로 네트워크 없이 시작할 수 있다.

## 서빙 체크리스트

배포 후 `scripts/check_wasm_serving.sh <url> [origin]`으로 확인한다.

| 항목 | 값 |
|---|---|
| Content-Type | `application/wasm` |
| 압축 | 빌드 시 만든 Brotli |
| 파일명 | 콘텐츠 해시 포함 |
| 캐시 | `public, max-age=31536000, immutable` (HTML은 `no-cache`) |
| 교차 출처 CDN | `Access-Control-Allow-Origin` 필요 |
| CSP | `script-src`에 `'wasm-unsafe-eval'` |

- wasm-bindgen이 만든 JS와 `.wasm`은 버전이 정확히 맞아야 한다. 함께 해시해서 배포하고, 이미 열린 탭이 깨지지 않도록 이전 버전 파일을 한동안 남겨 둔다.
- HTML의 정적 스켈레톤을 먼저 보여 줘서 WASM 로딩 동안 빈 화면을 없앤다.

## 스레드

`SharedArrayBuffer` 기반 스레드는 nightly `build-std`, `+atomics`, COOP/COEP 헤더(`same-origin`, `require-corp`)가 필요하다. COEP는 제3자 리소스 로딩에 영향을 주므로 서비스 전체 영향부터 확인한다. 단일 Worker로 충분한지 측정한 뒤에 도입한다.

## 폰트

앱이 폰트를 직접 번들하는 프레임워크에서는 한글 폰트가 WASM보다 커질 수 있다. KS X 1001의 2,350자 subset을 먼저 넣고 전체 폰트는 나중에 받는다. wgpu로 직접 렌더링한다면 Canvas2D로 글리프를 만들어 GPU 아틀라스에 올리면 시스템 폰트를 쓸 수 있다.
