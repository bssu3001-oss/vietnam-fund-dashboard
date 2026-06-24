#!/bin/bash
# 이 파일을 더블클릭하면 로컬 서버(http)를 켜고 대시보드를 엽니다.
# (file://로 그냥 열면 Chrome이 데이터 파일을 막아서 안 나오므로, 이렇게 서버로 엽니다)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
URL="http://localhost:8800/베트남펀드_대시보드/index.html"
if curl -s -o /dev/null "http://localhost:8800/" 2>/dev/null; then
  # 서버가 이미 켜져 있으면 그냥 열기
  open "$URL"
else
  # 서버 켜고 열기 (이 창을 닫으면 서버가 꺼집니다)
  ( sleep 1 && open "$URL" ) &
  echo "📊 대시보드 서버 실행 중..."
  echo "   브라우저가 자동으로 열립니다. 다 보고 나면 이 검은 창을 닫으세요."
  python3 -m http.server 8800
fi
