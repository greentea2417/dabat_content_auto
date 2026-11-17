# 다받맘 정보성 콘텐츠 초안 자동 생성기

임신·출산을 준비하는 엄마들을 위한 **정부·지자체 혜택 정보성 쓰레드 글 초안**을 매일 3개 만들어
`drafts/YYYY-MM-DD.md` 로 저장하고 텔레그램으로 보내 줍니다.

> ⚠️ **SNS 자동 게시는 하지 않습니다.** 초안을 사람이 확인하고, `[확인 필요]` 표시된 수치는
> 출처를 확인한 뒤 직접 올리세요.

## 동작 방식

1. 매일 오전 8시(KST) cron 이 `run.sh` → `generate.py` 를 실행
2. `generate.py` 가 VPS 에 로그인된 **Claude Code CLI 헤드리스 모드(`claude -p`)** 로 초안 생성 (API 키 사용 안 함)
   - 쓰레드용 300자 내외, 30대 엄마 친구 말투, 마지막 줄은 질문
   - 금액·기간·소득 기준 같은 수치 뒤에 `[확인 필요]`, 글마다 출처 확인용 검색 키워드
3. 지난 주제(`data/history.json`)를 프롬프트에 넣고, 비슷한 주제는 걸러내 반복을 막음
4. `drafts/YYYY-MM-DD.md` 저장 후 텔레그램 봇으로 전송

외부 Python 패키지는 필요 없습니다(표준 라이브러리만 사용, Python 3.9+).

## 파일 구성

| 파일 | 설명 |
|---|---|
| `generate.py` | 초안 생성·저장·전송 본체 |
| `run.sh` | cron 용 실행 래퍼 (`logs/YYYY-MM.log` 에 로그 기록) |
| `install.sh` | 매일 08:00 KST cron 등록 (`--uninstall` 로 제거) |
| `.env.example` | 설정 예시 (`.env` 는 git 에 올라가지 않음) |
| `drafts/` | 날짜별 초안 (git 제외) |
| `data/history.json` | 지난 주제 기록 (git 제외) |

---

## VPS 설치 방법 (Oracle Cloud · Ubuntu ARM)

### 1. 기본 패키지 설치

```bash
sudo apt update && sudo apt install -y git python3 cron
```

```bash
sudo systemctl enable --now cron
```

### 2. Claude Code 설치 및 로그인

이미 설치·로그인돼 있다면 건너뛰세요.

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

```bash
claude
```

처음 실행하면 브라우저 로그인 링크가 나옵니다. 로그인을 마치고 `/exit` 로 나옵니다.
헤드리스 모드가 되는지 확인합니다.

```bash
claude -p "안녕이라고만 대답해"
```

### 3. 레포 받기

```bash
cd ~ && git clone https://github.com/greentea2417/dabat_content_auto.git
```

```bash
cd ~/dabat_content_auto
```

### 4. 텔레그램 봇 준비

1. 텔레그램에서 **@BotFather** → `/newbot` → 봇 이름 지정 → **토큰** 복사
2. 만든 봇에게 아무 메시지나 한 번 보내기
3. 아래 주소를 브라우저에서 열어 `"chat":{"id": ...}` 값(**채팅 ID**)을 확인

```
https://api.telegram.org/bot<토큰>/getUpdates
```

### 5. `.env` 설정

```bash
cp .env.example .env && chmod 600 .env
```

```bash
nano .env
```

`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 를 채웁니다. (`CLAUDE_BIN`, `CLAUDE_MODEL`, `DRAFT_COUNT` 는 선택)

### 6. 테스트 실행

텔레그램 없이 생성·저장만 해 봅니다.

```bash
python3 generate.py --dry-run
```

`drafts/오늘날짜.md` 에 초안 3개가 생기면 성공입니다. 텔레그램 전송까지 확인하려면:

```bash
python3 generate.py --force
```

> 같은 날 두 번 실행하면 기본적으로 건너뜁니다. 다시 만들려면 `--force` 를 붙이세요.

### 7. cron 등록 (매일 오전 8시 KST)

```bash
./install.sh
```

서버 시간대가 UTC 여도 자동으로 08:00 KST 에 맞춰 등록합니다(UTC 서버 → 매일 23:00).
여러 번 실행해도 중복 등록되지 않으며, 기존 crontab 항목은 그대로 둡니다.

```bash
crontab -l
```

제거하려면:

```bash
./install.sh --uninstall
```

### 8. 로그 확인

```bash
tail -n 50 logs/$(date +%Y-%m).log
```

---

## 업데이트

```bash
cd ~/dabat_content_auto && git pull
```

`drafts/`, `data/history.json`, `.env` 는 git 에서 제외되어 있어 업데이트해도 지워지지 않습니다.

## 문제 해결

- **cron 에서 `claude` 를 못 찾음**: `which claude` 결과를 `.env` 의 `CLAUDE_BIN` 에 적고 `./install.sh` 를 다시 실행하세요.
- **로그인 만료 오류**: VPS 에서 `claude` 를 실행해 다시 로그인하세요.
- **텔레그램 전송 실패**: 봇에게 먼저 메시지를 보냈는지, 토큰/채팅 ID 가 맞는지 확인하세요.
- **같은 주제가 반복됨**: `data/history.json` 에 기록이 쌓이는지 확인하세요. 기록을 지우면 처음부터 다시 시작합니다.
- **생성 실패 시**: 최대 3번 재시도하고, 그래도 실패하면 텔레그램으로 실패 알림을 보냅니다.
