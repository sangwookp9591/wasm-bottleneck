#!/usr/bin/env bash
# 배포된 .wasm의 응답 헤더를 점검한다.
# 사용법: check_wasm_serving.sh <wasm-url> [페이지-origin]
# 종료 코드: 0 = FAIL 없음, 1 = FAIL 있음, 2 = 요청 불가 또는 잘못된 인자
set -u

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
  echo "사용법: $0 <wasm-url> [페이지-origin]" >&2
  exit 2
fi

url=$1
origin=${2:-}
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

curl_args=(-sS -L -o /dev/null -D "$tmp" -w '%{size_download} %{url_effective}' -H 'Accept-Encoding: br, gzip')
if [ -n "$origin" ]; then
  curl_args+=(-H "Origin: $origin")
fi

if ! result=$(curl "${curl_args[@]}" "$url"); then
  echo "요청 실패: $url" >&2
  exit 2
fi
size=${result%% *}
effective_url=${result#* }

# 리다이렉트가 있으면 마지막 응답의 헤더만 본다.
headers=$(tr -d '\r' < "$tmp" | awk '/^HTTP\//{b=""} {b=b $0 "\n"} END{printf "%s", b}')

header() {
  printf '%s\n' "$headers" | awk -v n="$1" 'tolower($0) ~ "^" n ":" { sub(/^[^:]*:[ \t]*/, ""); print; exit }'
}

fails=0
pass() { printf 'PASS  %s\n' "$1"; }
warn() { printf 'WARN  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; fails=$((fails + 1)); }

status=$(printf '%s\n' "$headers" | awk 'NR==1 {print $2}')
if [ "$status" = "200" ]; then
  pass "HTTP 상태: 200"
else
  fail "HTTP 상태: ${status:-없음}"
fi

content_type=$(header content-type)
case "$content_type" in
  application/wasm*) pass "Content-Type: $content_type" ;;
  *) fail "Content-Type이 application/wasm이 아님 (${content_type:-없음}). 스트리밍 컴파일이 실패한다." ;;
esac

encoding=$(header content-encoding)
case "$encoding" in
  br) pass "압축: br" ;;
  zstd|gzip) warn "압축: $encoding (Brotli 최고 단계 사전 압축이 보통 더 작다)" ;;
  *) fail "압축 없음 (${encoding:-없음})" ;;
esac

path=${effective_url%%[?#]*}
file=${path##*/}
has_hash=0
if [[ $file =~ [.-][0-9A-Za-z_-]{8,}\.wasm$ ]] && [[ $file =~ [0-9] ]]; then
  has_hash=1
fi

cache=$(header cache-control)
if [[ $cache == *immutable* ]]; then
  if [ "$has_hash" -eq 1 ]; then
    pass "캐시: $cache"
  else
    fail "파일명에 해시가 없는데 immutable 사용 ($file). 배포해도 사용자가 옛 파일을 계속 받는다."
  fi
elif [ "$has_hash" -eq 1 ]; then
  warn "해시 파일이지만 immutable 장기 캐시가 아님 (${cache:-없음})"
else
  warn "파일명에 콘텐츠 해시가 없어 장기 캐시를 쓸 수 없음 ($file, ${cache:-캐시 헤더 없음})"
fi

if [ -n "$origin" ]; then
  acao=$(header access-control-allow-origin)
  if [ "$acao" = "*" ] || [ "$acao" = "$origin" ]; then
    pass "CORS: $acao"
  else
    fail "CORS 허용 안 됨 (${acao:-없음}, 요청 origin: $origin)"
  fi
fi

printf 'INFO  전송 크기: %s bytes\n' "$size"

if [ "$fails" -gt 0 ]; then
  exit 1
fi
exit 0
