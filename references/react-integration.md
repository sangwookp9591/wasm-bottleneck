# React와 Next.js 통합

## 데이터 흐름

- 렌더 루프와 스크롤은 WASM 안에 둔다. React state를 프레임마다 거치면 WASM의 이득이 사라진다.
- React는 데이터가 바뀔 때만 호출하고, 선택 변경 같은 의미 있는 이벤트만 받는다.
- 데이터는 TypedArray나 Arrow로 넘긴다.

## 컴포넌트

`wasm-bindgen --target web` 결과물을 쓴다. StrictMode는 개발 중 effect를 두 번 실행하므로, 비동기 초기화 중에 언마운트된 경우까지 정리해야 한다. `free()`를 빠뜨리면 WASM 메모리가 샌다.

```tsx
"use client";
import { useEffect, useRef, useState } from "react";
import init, { Grid } from "@acme/grid-wasm";

export function FastGrid({ data }: { data: Uint32Array }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [grid, setGrid] = useState<Grid | null>(null);

  useEffect(() => {
    let alive = true;
    let g: Grid | undefined;
    (async () => {
      await init();
      const created = await Grid.create(ref.current!);
      if (!alive) { created.free(); return; }
      g = created;
      setGrid(created);
    })();
    return () => { alive = false; g?.free(); setGrid(null); };
  }, []);

  useEffect(() => { grid?.set_data(data); }, [grid, data]);

  return <canvas ref={ref} style={{ width: "100%", height: "100%" }} />;
}
```

## Next.js

- App Router에서 `next/dynamic`의 `ssr: false`는 Client Component 안에서만 쓸 수 있다. 얇은 Client Component로 감싼다.
- 번들러 설정에 의존하지 않으려면 `.wasm`을 정적 파일로 배포하고 `init({ module_or_path: url })`로 경로를 넘긴다.
- `next.config`의 헤더 설정으로 캐시와 CSP를 지정하거나 CDN에서 처리한다.

## Worker

계산 모듈은 Worker에서 실행한다.

```ts
// sort.worker.ts
import init, { sort_rows } from "@acme/sort-wasm";

const ready = init();

self.onmessage = async ({ data: { id, input } }) => {
  await ready;
  const output: Float64Array = sort_rows(input);
  self.postMessage({ id, output }, { transfer: [output.buffer] });
};
```

- Worker는 `new Worker(new URL("./sort.worker.ts", import.meta.url), { type: "module" })`로 만들고, 처음 쓸 때 한 번만 생성해 재사용한다.
- 요청마다 `id`를 붙여 응답을 짝지어야 동시 호출이 섞이지 않는다.
- `postMessage`에 transfer를 지정하면 복사 비용이 없지만, 보낸 쪽의 버퍼는 사용할 수 없게 된다.
- 렌더링까지 Worker로 옮길 때는 `canvas.transferControlToOffscreen()`을 쓴다. 메인 스레드가 React 작업으로 바빠도 스크롤이 끊기지 않는다.

## canvas 부품의 필수 처리

- `ResizeObserver`와 `devicePixelRatio`로 내부 해상도를 맞춘다.
- 텍스트 입력은 해당 위치에 실제 HTML `<input>`을 띄운다. canvas만으로는 한글 IME 조합을 처리하기가 매우 어렵다.
- 스크린 리더용 숨김 DOM이나 ARIA grid를 제공한다.
- WebGPU를 쓸 수 없으면 WebGL2나 Canvas2D로 대체하고, 컨텍스트 소실 시 복구 경로를 둔다.
