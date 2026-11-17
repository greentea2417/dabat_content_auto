#!/usr/bin/env python3
"""다받맘 정보성 콘텐츠 초안 자동 생성기.

매일 임신·출산 준비 엄마를 위한 정부·지자체 혜택 정보성 쓰레드 초안을 만들어
drafts/YYYY-MM-DD.md 로 저장하고 텔레그램으로 보낸다.

- 글 생성: VPS 에 로그인된 Claude Code CLI 헤드리스 모드(claude -p) 사용. API 키 사용 안 함.
- SNS 자동 게시는 하지 않는다. 사람이 확인 후 직접 올린다.
- 외부 패키지 없이 Python 표준 라이브러리만 사용한다.

사용법:
    python3 generate.py              # 생성 + 저장 + 텔레그램 전송
    python3 generate.py --dry-run    # 생성 + 저장만 (텔레그램 전송 안 함)
    python3 generate.py --force      # 오늘 초안이 이미 있어도 다시 생성
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
DRAFTS_DIR = BASE_DIR / "drafts"
HISTORY_FILE = BASE_DIR / "data" / "history.json"
ENV_FILE = BASE_DIR / ".env"
KST = ZoneInfo("Asia/Seoul")

HISTORY_LOOKBACK = 90        # 프롬프트에 넣을 지난 주제 개수
SIMILARITY_THRESHOLD = 0.8   # 이 이상 비슷하면 중복으로 간주
CLAUDE_TIMEOUT_SEC = 600
TELEGRAM_LIMIT = 4000        # 텔레그램 메시지 최대 4096자, 여유 있게

# 주제가 한쪽으로 쏠리지 않도록 프롬프트에 제시하는 카테고리
CATEGORIES = [
    "임신 준비(난임·임신 전 검사·엽산 등)",
    "임신 중 의료비·검진 지원",
    "출산 직후 지원금·바우처",
    "산후조리·산모 건강 지원",
    "육아휴직·출산휴가 등 직장맘 제도",
    "아빠(배우자) 관련 제도",
    "지자체(시·군·구) 출산 장려 혜택",
    "교통·주거·세금 혜택",
    "신청 방법·서류·기한 꿀팁",
    "놓치기 쉬운 숨은 혜택",
]


# ---------------------------------------------------------------------------
# 설정 / 기록
# ---------------------------------------------------------------------------

def load_env(path: Path = ENV_FILE) -> None:
    """간단한 .env 파서. 이미 설정된 환경변수는 덮어쓰지 않는다."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        log(f"경고: {HISTORY_FILE} 를 읽을 수 없어 빈 기록으로 시작합니다.")
        return []


def save_history(history: list[dict]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(HISTORY_FILE)


def log(msg: str) -> None:
    now = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# 프롬프트 / Claude 호출
# ---------------------------------------------------------------------------

def build_prompt(count: int, history: list[dict], today: dt.date, avoid: list[str]) -> str:
    recent = history[-HISTORY_LOOKBACK:]
    past_lines = "\n".join(f"- {h['date']} | {h['topic']}" for h in recent) or "- (아직 없음)"
    avoid_lines = "\n".join(f"- {a}" for a in avoid)
    categories = "\n".join(f"- {c}" for c in CATEGORIES)

    return f"""너는 '다받맘'(정부·지자체 혜택 다 받는 엄마) 쓰레드 계정의 콘텐츠 작가야.
오늘은 {today.isoformat()} 이야. 임신·출산을 준비하는 엄마들에게 도움이 되는
정부·지자체 혜택 정보성 쓰레드 글 초안을 정확히 {count}개 써줘.

[글 형식]
- 쓰레드용, 본문 300자 내외 (250~350자)
- 30대 엄마 친구가 카톡하듯 말하는 말투 (반말 섞인 친근한 말투, 예: "~거 알아?", "~더라", "나도 몰랐는데")
- 과한 이모지·해시태그 금지 (이모지는 0~2개)
- 첫 줄은 스크롤을 멈추게 하는 한 문장
- 마지막 줄은 댓글을 부르는 질문 한 줄로 끝낼 것

[정확성 규칙 — 매우 중요]
- 금액, 기간, 소득 기준, 나이, 신청 기한, 대상 조건 같은 구체 수치·조건 바로 뒤에는 반드시 "[확인 필요]" 를 붙여.
  예: "첫만남이용권 200만원[확인 필요]"
- 확실하지 않은 제도명은 만들어내지 말고, 실제로 있는 제도만 다뤄.
- 지역마다 다른 혜택이면 "지역마다 달라" 라고 분명히 적어.
- 각 글마다 사람이 출처를 검색해서 확인할 수 있는 키워드 2~4개를 따로 적어.
  (예: "복지로 첫만남이용권", "정부24 행복출산 원스톱", "보건소 임산부 등록")

[주제 다양성]
아래 카테고리 중에서 {count}개 글이 서로 다른 카테고리가 되도록 골라:
{categories}

아래는 지난 초안 주제야. 같은 제도·같은 각도는 절대 반복하지 마:
{past_lines}
{("이번에 특히 피해야 할 주제:" + chr(10) + avoid_lines) if avoid else ""}

[출력 형식]
설명이나 코드블록 없이 아래 JSON 배열만 출력해:
[
  {{
    "topic": "다룬 제도/주제를 한 줄로 (중복 체크용, 예: '첫만남이용권 신청 방법')",
    "category": "위 카테고리 중 하나",
    "body": "쓰레드 본문 전체 (줄바꿈은 \\n, 마지막 줄은 질문)",
    "check_keywords": ["출처 확인용 검색 키워드", "..."]
  }}
]
"""


def find_claude() -> str:
    configured = os.environ.get("CLAUDE_BIN", "").strip()
    if configured:
        return configured
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (Path.home() / ".local/bin/claude", Path.home() / ".claude/local/claude"):
        if candidate.exists():
            return str(candidate)
    raise SystemExit("claude CLI 를 찾을 수 없습니다. .env 의 CLAUDE_BIN 에 경로를 지정하세요.")


def call_claude(prompt: str) -> str:
    cmd = [
        find_claude(), "-p",
        "--output-format", "json",
        "--no-session-persistence",
        # 글쓰기만 하면 되므로 도구 사용은 막는다
        "--disallowedTools", "Bash", "Edit", "Write", "NotebookEdit",
        "WebFetch", "WebSearch", "Task", "Agent",
    ]
    model = os.environ.get("CLAUDE_MODEL", "").strip()
    if model:
        cmd += ["--model", model]

    # 프롬프트는 stdin 으로 전달 (인자 길이·이스케이프 문제 방지)
    proc = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT_SEC,
        cwd=str(BASE_DIR),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude 실행 실패 (exit {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()[:500]}"
        )
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.stdout  # 혹시 text 로 나왔을 때
    if envelope.get("is_error"):
        raise RuntimeError(f"claude 오류 응답: {envelope.get('result')}")
    return envelope.get("result", "")


def parse_drafts(text: str) -> list[dict]:
    """응답에서 JSON 배열을 뽑아 검증한다."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("응답에서 JSON 배열을 찾지 못했습니다.")
    items = json.loads(cleaned[start:end + 1])

    drafts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic", "")).strip()
        body = str(item.get("body", "")).strip()
        if not topic or not body:
            continue
        keywords = item.get("check_keywords") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        drafts.append({
            "topic": topic,
            "category": str(item.get("category", "")).strip(),
            "body": body,
            "check_keywords": [str(k).strip() for k in keywords if str(k).strip()],
        })
    return drafts


# ---------------------------------------------------------------------------
# 중복 체크
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", s).lower()


def is_duplicate(topic: str, seen: list[str]) -> bool:
    t = _norm(topic)
    for s in seen:
        n = _norm(s)
        if not n:
            continue
        if t == n or difflib.SequenceMatcher(None, t, n).ratio() >= SIMILARITY_THRESHOLD:
            return True
    return False


def generate_drafts(count: int, history: list[dict], today: dt.date, max_attempts: int = 3) -> list[dict]:
    seen = [h["topic"] for h in history]
    accepted: list[dict] = []
    rejected: list[str] = []

    for attempt in range(1, max_attempts + 1):
        need = count - len(accepted)
        if need <= 0:
            break
        log(f"Claude 호출 (시도 {attempt}/{max_attempts}, 필요한 초안 {need}개)")
        prompt = build_prompt(
            need,
            history + [{"date": today.isoformat(), "topic": d["topic"]} for d in accepted],
            today,
            rejected,
        )
        try:
            candidates = parse_drafts(call_claude(prompt))
        except (RuntimeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            log(f"생성 실패: {e}")
            time.sleep(5)
            continue

        for d in candidates:
            if len(accepted) >= count:
                break
            if is_duplicate(d["topic"], seen):
                log(f"중복 주제 제외: {d['topic']}")
                rejected.append(d["topic"])
                continue
            if "[확인 필요]" not in d["body"]:
                log(f"경고: '[확인 필요]' 표시가 없는 초안 — {d['topic']}")
            accepted.append(d)
            seen.append(d["topic"])

    if len(accepted) < count:
        log(f"경고: 초안을 {count}개 중 {len(accepted)}개만 만들었습니다.")
    return accepted


# ---------------------------------------------------------------------------
# 저장 / 전송
# ---------------------------------------------------------------------------

def format_draft(idx: int, d: dict) -> str:
    kw = ", ".join(d["check_keywords"]) or "(없음)"
    return (
        f"## 초안 {idx}. {d['topic']}\n"
        f"- 카테고리: {d['category']}\n"
        f"- 글자 수: {len(d['body'])}자\n"
        f"- 출처 확인 키워드: {kw}\n\n"
        f"{d['body']}\n"
    )


def save_markdown(drafts: list[dict], today: dt.date) -> Path:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DRAFTS_DIR / f"{today.isoformat()}.md"
    parts = [
        f"# 다받맘 초안 — {today.isoformat()}\n",
        "> ⚠️ 자동 생성 초안입니다. `[확인 필요]` 표시된 수치·조건은 출처 확인 키워드로 "
        "복지로·정부24·지자체 공식 사이트에서 꼭 확인한 뒤 직접 게시하세요.\n",
    ]
    parts += [format_draft(i, d) for i, d in enumerate(drafts, 1)]
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def send_telegram(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 .env 에 없습니다.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in [text[i:i + TELEGRAM_LIMIT] for i in range(0, len(text), TELEGRAM_LIMIT)]:
        # parse_mode 없이 평문 전송 (특수문자 이스케이프 문제 방지)
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": "true",
        }).encode()
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, data=data, timeout=30) as resp:
                    body = json.loads(resp.read().decode())
                    if not body.get("ok"):
                        raise RuntimeError(f"텔레그램 오류: {body}")
                break
            except (urllib.error.URLError, RuntimeError) as e:
                if attempt == 2:
                    raise RuntimeError(f"텔레그램 전송 실패: {e}") from e
                time.sleep(3 * (attempt + 1))


def notify(drafts: list[dict], today: dt.date) -> None:
    send_telegram(
        f"📝 다받맘 오늘의 초안 {len(drafts)}개 ({today.isoformat()})\n"
        "※ [확인 필요] 항목은 출처 확인 후 직접 게시해 주세요. 자동 게시되지 않습니다."
    )
    for i, d in enumerate(drafts, 1):
        kw = ", ".join(d["check_keywords"]) or "(없음)"
        send_telegram(
            f"[초안 {i}] {d['topic']}\n"
            f"카테고리: {d['category']} · {len(d['body'])}자\n"
            f"────────\n{d['body']}\n────────\n"
            f"🔎 출처 확인 키워드: {kw}"
        )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="다받맘 정보성 콘텐츠 초안 생성기")
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 전송 없이 생성·저장만 한다")
    parser.add_argument("--force", action="store_true", help="오늘 초안이 이미 있어도 다시 만든다")
    parser.add_argument("--count", type=int, default=None, help="만들 초안 개수 (기본 .env DRAFT_COUNT 또는 3)")
    args = parser.parse_args()

    load_env()
    count = args.count or int(os.environ.get("DRAFT_COUNT", "3") or 3)
    today = dt.datetime.now(KST).date()
    out_path = DRAFTS_DIR / f"{today.isoformat()}.md"

    if out_path.exists() and not args.force:
        log(f"오늘 초안이 이미 있습니다: {out_path} (다시 만들려면 --force)")
        return 0

    history = load_history()
    if args.force:
        # 오늘 기록은 지우고 다시 만든다
        history = [h for h in history if h.get("date") != today.isoformat()]

    drafts = generate_drafts(count, history, today)
    if not drafts:
        log("초안을 하나도 만들지 못했습니다.")
        if not args.dry_run:
            try:
                send_telegram(f"⚠️ 다받맘 초안 생성 실패 ({today.isoformat()}). VPS 로그를 확인해 주세요.")
            except RuntimeError as e:
                log(str(e))
        return 1

    path = save_markdown(drafts, today)
    log(f"저장 완료: {path}")

    history += [
        {"date": today.isoformat(), "topic": d["topic"], "category": d["category"]}
        for d in drafts
    ]
    save_history(history)

    if args.dry_run:
        log("dry-run: 텔레그램 전송을 건너뜁니다.")
        print(path.read_text(encoding="utf-8"))
    else:
        notify(drafts, today)
        log("텔레그램 전송 완료")
    return 0 if len(drafts) >= count else 2


if __name__ == "__main__":
    sys.exit(main())
