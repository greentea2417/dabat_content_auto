#!/usr/bin/env bash
# 매일 오전 8시(KST)에 run.sh 를 실행하는 cron 을 등록한다.
# 여러 번 실행해도 중복 등록되지 않는다.  제거: ./install.sh --uninstall
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
MARK="# dabat_content_auto"

# 기존 crontab 에서 이 프로젝트 줄만 뺀 내용 (crontab 이 비어 있어도 실패하지 않게)
current_cron() { { crontab -l 2>/dev/null || true; } | grep -v "$MARK" || true; }

if [[ "${1:-}" == "--uninstall" ]]; then
  current_cron | crontab -
  echo "cron 제거 완료"
  exit 0
fi

command -v python3 >/dev/null || { echo "python3 가 필요합니다: sudo apt install -y python3"; exit 1; }
command -v crontab >/dev/null || { echo "cron 이 필요합니다: sudo apt install -y cron"; exit 1; }

CLAUDE_PATH="$(command -v claude || true)"
if [[ -z "$CLAUDE_PATH" ]]; then
  echo "claude CLI 를 찾을 수 없습니다. Claude Code 설치·로그인 후 다시 실행하세요."
  exit 1
fi

if [[ ! -f "$DIR/.env" ]]; then
  cp "$DIR/.env.example" "$DIR/.env"
  chmod 600 "$DIR/.env"
  echo ".env 를 만들었습니다. 텔레그램 토큰/채팅 ID 를 채워 주세요: $DIR/.env"
fi

chmod +x "$DIR/run.sh" "$DIR/generate.py"
mkdir -p "$DIR/drafts" "$DIR/data" "$DIR/logs"

# 서버 시간대와 무관하게 '08:00 KST' 에 해당하는 서버 로컬 시각을 계산한다.
read -r MIN HOUR < <(python3 - <<'PY'
import datetime as dt
from zoneinfo import ZoneInfo
kst = dt.datetime.now(ZoneInfo("Asia/Seoul")).replace(hour=8, minute=0, second=0, microsecond=0)
local = kst.astimezone()  # 서버 로컬 시간대
print(local.minute, local.hour)
PY
)

# cron 은 PATH 가 매우 짧으므로 claude/node 가 있는 경로를 넣어 준다.
NODE_PATH_DIR="$(dirname "$(command -v node || echo /usr/bin/node)")"
CRON_PATH="$(dirname "$CLAUDE_PATH"):$NODE_PATH_DIR:/usr/local/bin:/usr/bin:/bin"
LINE="$MIN $HOUR * * * PATH=$CRON_PATH HOME=$HOME $DIR/run.sh $MARK"

{ current_cron; echo "$LINE"; } | crontab -

echo "cron 등록 완료 (서버 시간대: $(date +%Z), 매일 ${HOUR}:$(printf %02d "$MIN") = 08:00 KST)"
echo "  $LINE"
echo
echo "테스트:  python3 $DIR/generate.py --dry-run"
echo "로그:    tail -f $DIR/logs/\$(date +%Y-%m).log"
