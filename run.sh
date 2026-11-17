#!/usr/bin/env bash
# cron 에서 호출하는 실행 래퍼. 로그는 logs/YYYY-MM.log 에 쌓인다.
set -uo pipefail
cd "$(dirname "$0")"
mkdir -p logs
LOG="logs/$(TZ=Asia/Seoul date +%Y-%m).log"
{
  echo "===== $(TZ=Asia/Seoul date '+%F %T') 실행 시작 ====="
  python3 generate.py "$@"
  echo "===== 종료 코드: $? ====="
} >> "$LOG" 2>&1
