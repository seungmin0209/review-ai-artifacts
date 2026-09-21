---
name: review-ai-artifacts
description: Edit & Tell <Agent> what to do — 사용자에게 보여 줄 아티팩트(.html 보고서·요약·대시보드·목업·문서·랜딩, 그리고 .md 문서)를 만들어 달라는 요청을 받았을 때, 그리고 그런 .html/.md 를 어떤 도구(Write·Edit·Bash 스크립트)로든 쓰거나 고친 직후에 쓴다. 산출물을 브라우저에 "이중클릭 = 수정, 우클릭 = 댓글" 화면으로 띄우고, 사용자가 [진행중인 <Agent> Session에 제출] 을 누르면 수정 내역과 댓글을 받아 반영한다. 훅이 자동 발동하지만, 훅이 없거나 실패해도 이 설명에 맞으면 스킬을 따른다. 트리거 — "HTML/md 로 만들어줘", "보고서/대시보드/목업/정리 문서 만들어줘", .html·.md 저장 직후, "편집기 열어줘", "이 문서 고치고 싶어", "댓글 달게 해줘", "리뷰 모드".
---

# review-ai-artifacts — Edit & Tell <Agent> what to do

사용자는 완성된 화면을 보면서 고치고 싶어 한다. 코드나 md 를 열어 달라고 하지 않는다.
HTML 산출물을 넘길 때는 파일 경로만 알려 주지 말고 **이 화면으로 띄워서** 넘긴다.
편집 화면은 공통이지만 제출 전달 경로는 환경별로 다르다. `--agent`는 표시명이다. 파일 저장 성공을 세션 전달 성공으로 표현하지 않는다.

## 설치 (폴더 하나 · Mac/Windows/Linux)

- **권장(Claude Code)**: 에이전트가 터미널에서 `claude plugin marketplace add seungmin0209/review-ai-artifacts && claude plugin install review-ai-artifacts@review-ai-artifacts`. 사용자가 직접이면 입력창에 `/plugin …` 같은 두 줄. 파일 복사·권한 문제 없이 훅까지 설치된다. 아래는 그 밖의 방법이다.

```bash
# Mac / Linux
sh install.sh
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File install.ps1
```

- 설치 스크립트가 **파이썬 3가 없으면 먼저 설치한다** (Mac: Homebrew 또는 Apple 개발자 도구 · Windows: `winget install Python.Python.3.12` · Linux: apt/dnf).
  그 다음 Claude Code 스킬 위치(`~/.claude/skills/review-ai-artifacts`, Windows 는 `%USERPROFILE%\.claude\skills\review-ai-artifacts`)에 넣는다.
- **에이전트가 직접 해도 된다.** 사용자가 스킬 폴더만 받아 두었으면, 에이전트가 이 스크립트를 실행해 파이썬까지 깔고 진행한다.
  단 Claude Code 는 `~/.claude` 아래 쓰기를 막는 경우가 있다. 그때는 마지막 복사 한 줄만 사용자에게 넘긴다 —
  Mac: `unzip ~/Downloads/review-ai-artifacts.zip -d ~/.claude/skills/` · Windows: `Expand-Archive "$HOME\Downloads\review-ai-artifacts.zip" -DestinationPath "$HOME\.claude\skills\" -Force`
  `review.py` 실행이 "python3 를 찾을 수 없다" 로 실패하면 사용자에게 설치를 시키지 말고 install 스크립트를 먼저 돌린다.
- Codex 는 프로젝트 `AGENTS.md` 에, Gemini CLI 는 `GEMINI.md` 에 "HTML 산출물은 <경로>/SKILL.md 규약(review-ai-artifacts)으로 띄운다" 한 줄.
- 실행 명령은 Mac/Linux `python3`, Windows `python`. 설정은 `~/.config/review-ai-artifacts/config.json` 하나.

## Claude Code 자동 발동 훅

플러그인(`hooks/hooks.json`) 또는 `install.sh`/`install.ps1`(`~/.claude/settings.json`) 이 `hook.py` 를 두 이벤트에 건다.

- **PostToolUse** `Write|Edit|MultiEdit|NotebookEdit|Bash` — 파일 도구는 `file_path`, **Bash 는 명령문에서 `.html`/`.md` 경로를 뽑아** 실제로 존재하고 60초 안에 바뀐 것만 대상으로 한다
  (`cat > x.html <<EOF`, `tee`, `sed -i`, `cp`, 파이썬 스크립트 등 어떤 경로든 잡힌다).
- **Stop** (턴 종료) — 안전망. 작업 디렉터리 아래에서 이 세션 중 바뀐 `.html` 이 아직 처리되지 않았으면 그때 발동한다. 어떤 도구로 만들었는지와 무관하다. `stop_hook_active` 면 재발동하지 않는다.

처리한 문서는 `~/.config/review-ai-artifacts/state.json` 에 세션별로 기록해 같은 문서를 두 번 띄우지 않는다. 설정 파일이 없으면 훅이 `mode: ask` 기본 파일을 만들고 첫 사용 안내를 한 번 넣는다.
이 훅은 Claude Code용이다. Codex에서 등록됐다고 가정하지 않는다. 훅 없는 환경에서는 스킬을 읽고 직접 실행한다.

| 상태 | 훅이 하는 일 |
|---|---|
| 설정 없음(처음) | "발동 방식을 먼저 물어라" 를 넣는다 → 에이전트가 채팅으로 네 가지를 설명하고 저장한 뒤 띄운다 |
| `always` | 훅이 **직접** `review.py` 를 띄우고 주소·이벤트 파일 경로를 넣는다. 에이전트는 사용자에게 한 줄 알리고 감시만 건다 |
| `ask` | "띄울까요? 한 줄 물어라" 를 넣는다 |
| `cases` | "이 경우에 해당하면 띄워라" 를 넣는다 |
| `off` | 아무것도 넣지 않는다 |

훅 등록만 따로 하려면 `python3 register_hook.py`, 해제는 `--remove`. 사용자 터미널에서 실행한다(Claude Code 는 `~/.claude` 쓰기를 막는다).

## 사용자는 자연어로만 말한다 — 명령은 에이전트가 친다

사용자(비개발자 포함)는 터미널 명령을 알 필요가 없다. 아래처럼 말하면 에이전트가 대응 명령을 실행하고 결과를 한 줄로 알린다.

| 사용자가 하는 말 | 에이전트가 실행 |
|---|---|
| "review-ai-artifacts 깔아줘" / "<GitHub 링크> 보고 깔아줘" | `claude plugin marketplace add seungmin0209/review-ai-artifacts && claude plugin install review-ai-artifacts@review-ai-artifacts` |
| "review-ai-artifacts 업데이트해줘" / "최신으로" | `claude plugin marketplace update review-ai-artifacts && claude plugin update review-ai-artifacts@review-ai-artifacts` |
| "review-ai-artifacts 지워줘" / "꺼줘(완전히)" | `claude plugin uninstall review-ai-artifacts@review-ai-artifacts` (로컬 설치면 `register_hook.py --remove` 후 폴더 삭제) |
| "리뷰 모드 항상 / 물어봐 / 아티팩트 올릴 때만 / 끄기" | `python3 <폴더>/review.py --set-mode always|ask|cases --cases artifact|off` |
| "편집기 열어줘", "이 문서 고치고 싶어" | `python3 <폴더>/review.py <문서.html 또는 .md>` (mode 와 무관하게 띄운다) |
| "내 이니셜 승으로", "마커 글자 바꿔" | `python3 <폴더>/review.py --set-initial 승` |

플러그인으로 설치된 경우 `<폴더>` 는 `~/.claude/plugins/cache/review-ai-artifacts/review-ai-artifacts/<버전>/` 이다. 사용자에게 경로나 명령을 되묻지 않는다.
설치·갱신 뒤에는 "새 Claude Code 세션부터 적용된다" 고 한 줄 덧붙인다.

## 발동 방식 — 처음 한 번 묻고, 언제든 바꿀 수 있다

`python3 review.py --show-config` 로 본다. **설정 파일이 없으면(처음 사용) 산출물을 띄우기 전에 먼저 묻는다.**
채팅으로 네 가지를 한 문장씩 설명하고 고르게 한 뒤 `--set-mode` 로 저장하고,
**"언제든 '리뷰 모드 항상/물어봐/특정 경우만/끄기' 라고 말하면 바꿀 수 있다"** 고 한 줄 덧붙인다.

| mode | 동작 |
|---|---|
| `always` | HTML 산출물이 나올 때마다 자동으로 띄운다 |
| `ask` | 산출물이 나오면 "편집·댓글 화면으로 띄울까요?" 한 줄만 묻는다 |
| `cases` | `cases` 에 적힌 경우에만 자동. 예: `artifact`(외부 배포), `report`, `dashboard`, `mockup` |
| `off` | 자동 발동 없음. "편집기 열어줘" 같은 명시 요청에만 |

```bash
python3 review.py --set-mode always            # 또는 ask / cases --cases artifact,report / off
python3 review.py --set-initial 승             # 댓글 마커에 보일 한 글자
python3 review.py --set-agent Codex            # 환경변수로 감지되지 않을 때 기본 이름
```

사용자가 나중에 "리뷰 모드 꺼", "이제 매번 띄워" 처럼 말하면 같은 명령으로 갱신하고 결과를 한 줄 알린다. 명시 요청은 mode 와 무관하게 항상 띄운다.

## 에이전트가 할 일 (발동이 결정된 산출물마다)

1. HTML 을 다 쓰고 나서 편집기를 백그라운드로 띄운다. **포트는 문서 경로로 정해진다**(같은 문서 = 같은 포트, 이미 떠 있으면 재사용). 다른 문서의 서버를 내리지 않는다 — 여러 세션이 각자 문서를 띄워도 서로 덮어쓰지 않는다. `--agent` 에는 **자기 이름**을 넣는다 (Claude / Codex / Gemini …). 환경변수로 감지되면 생략해도 된다.
   ```bash
   # Mac/Linux
   nohup python3 <이 폴더>/review.py "<산출물.html>" --agent Claude >/tmp/review-ai-artifacts.log 2>&1 &   # 포트는 문서별로 자동(8901~8990). 로그 첫 줄의 URL 을 읽어 알린다. 다른 문서 서버를 pkill 하지 않는다
   # Windows (PowerShell)
   Start-Process python -ArgumentList '<이 폴더>\review.py','<산출물.html>','--agent','Claude' -WindowStyle Hidden   # 포트 자동
   ```
2. **전달 연결을 확인한다.** Codex에서는 `CODEX_THREAD_ID`를 상속한 서버가 설치된 `codex queue --thread <UUID> --message <알림>`으로 현재 세션에 제출 위치·ID를 알린다. 환경에 ID가 없으면 확인한 현재 세션 UUID를 `--thread`로 지정한다. 이름·`--last`로 추측하거나 별도 `codex exec resume`를 띄우지 않는다.
   - 실행 전 `codex queue --help`, 실행 후 `/health`의 `thread_id`와 현재 UUID를 대조한다. `/health`만으로 실제 수신을 증명하지 않는다. 최초 연결은 격리된 테스트 문서 제출 → 큐 접수 → 대상 세션 수신 → `--ack` 반영 완료로 검증한다.
   - 기존 서버가 같은 문서를 서비스해도 옛 버전·다른 thread면 그대로 재사용하지 않는다. `/doc`와 PID를 확인하고 **그 문서의 서버만** 재시작한다. 미제출 사용자 입력이 있으면 보존 후 재시작한다.
   - 큐 접수는 반영 완료가 아니다. 화면 상태는 `저장됨 → Codex 큐 접수·반영 대기 → 반영 완료`다. 큐 실패·시간 초과에서도 이벤트를 보존하며, 시간 초과를 자동 재전송하지 않는다.
   - Codex CLI/현재 UUID가 없거나 queue가 실패하면 수동 전달로 표시한다. 버튼의 `전달 요청 복사`로 현재 대화에 알릴 수 있다. **백그라운드 tail이나 단순 폴링은 종료된 Codex 턴을 깨우는 연결이 아니다.** 이를 자동 반응 설정이라고 보고하지 않는다.
   - **Claude Code 는 서버가 세션을 깨우지 못한다.** 서버는 파일에 쓰기만 하고, 깨우는 것은 세션이 걸어 둔 **Monitor** 다. 문서를 띄운 직후 훅 안내문의 Monitor 명령을 그대로 건다(owner 필터 · 60초 heartbeat 포함). **Monitor 는 도구 상한이 30분**이라 늘릴 수 없다 — 만료 알림이 오면 **다른 일보다 먼저 같은 명령으로 다시 건다.** 명령은 시작할 때 아직 `new` 인 내 제출을 먼저 훑으므로, 재무장 사이의 공백이나 늦게 건 경우에도 밀린 제출을 바로 알린다(이미 처리한 ID 는 건너뛴다). heartbeat 가 90초 넘게 끊기면 화면이 "지켜보는 세션이 없습니다" 로 바뀌고 [전달 요청 복사] 가 켜진다 — 사용자가 대화창에 붙여 넣어 수동으로 깨운다. 2026-09-16 Monitor 를 걸지 않아 제출을 놓친 사례가 있다.
   - Codex 는 서버가 `codex queue --thread <UUID>` 로 직접 깨운다. 존재하지 않는 UUID 면 `delivery: failed` 로 남고 화면은 "자동 전달 실패" 를 보인다 — 성공처럼 보이지 않는다.
   - 다른 에이전트에서 감시가 지원된다고 추정하지 않는다.
2-1. **여러 세션이 동시에 쓴다 — 남의 문서를 건드리지 않는다.** 서버는 자기를 띄운 세션 ID 를 `owner` 로 들고 있고(`/health`), 제출 이벤트에도 `owner` 가 실린다.
   - `/health` 의 `owner` 가 내 세션이 아니면 그 문서는 **다른 세션 것**이다. 서버를 재시작·`--close` 하지 않고, 그 문서의 `status: new` 이벤트도 처리하지 않는다. 훅도 이 경우 띄우지 않고 알리기만 한다.
   - 이어받아야 하면 **사용자에게 먼저 확인**한다. 확인 없이 포트를 빼앗으면 사용자의 제출이 엉뚱한 세션으로 간다.
   - **fork 로 갈라진 세션이 같은 문서를 함께 지켜볼 때**는 빼앗을 필요가 없다. heartbeat(`/watch?session=&label=`)를 보낸 세션이 명단에 오르고(최근 3분), 둘 이상이면 화면 상단에 **제출 대상 선택칸**이 뜬다. 사용자가 고른 세션이 그 제출의 `owner` 가 되므로, 각 세션의 Monitor 필터가 알아서 갈라 받는다. Monitor 명령의 `label` 은 이 세션을 알아볼 이름으로 바꿔도 된다 — 그 이름이 선택칸에 그대로 보인다. fork 된 세션은 자기가 twin 인지 알 수 없으므로(세션 메타데이터에 부모 링크가 없다) 혈통을 따지지 말고 이 명단만 본다.
   - 턴 종료 안전망은 **이 세션이 실제로 건드린 디렉터리**만 보고, 이미 누가 서비스 중인 문서는 건너뛴다. 워크스페이스 전체를 훑지 않는다.
   - 예외: 세션이 끝나 서버가 내려간 문서는 다음 세션이 `status: new` 부터 이어 처리한다(5항).

3. 사용자에게는 "http://localhost:<포트> 에 띄웠다. 이중클릭으로 고치고 우클릭으로 댓글, 끝나면 [진행중인 <Agent> Session에 제출]"이라고 알리고, 자동 전달 미연결이면 그 제한도 함께 알린다.
4. 이벤트 한 줄 JSON 을 읽는다.
   - `edits[]` `{path, before, after}` — 사용자가 직접 고친 글자. **파일에는 이미 저장돼 있다.** 다시 쓰지 말고 요약해 "수정 N건 반영 확인" 이라고 알린다. 생성 스크립트가 있는 문서면 원본(md·json·py)에도 같은 수정을 반영한다.
   - `owner` — 그 제출을 받을 세션 ID. **내 세션이 아니면 처리하지 않는다**(2-1). 서버가 이미 내려갔고 사용자가 이어받기를 원할 때만 예외다.
   - `comments[]` `{n, path, anchor, quote, text}` — 요청. `quote` 가 있으면 그 문구만, 없으면 `anchor` 요소 전체가 대상. **`path` 가 빈 문자열이고 `anchor` 가 `[문서 전체]` 면 특정 부분이 아니라 문서 전체에 대한 총평**이므로, 한 곳만 고치지 말고 문서 전체를 훑어 반영한다. 파일을 고쳐 저장하고 번호별로 무엇을 어떻게 바꿨는지 답한다. 판단이 갈리면 그 번호만 물어본다.
   - **`conflict: true`** — 사용자가 화면을 새로 고치기 전(옛 판)에 고친 뒤 제출했다. 서버는 파일을 **덮어쓰지 않았다**(내가 올린 새 판을 지키기 위해). `edits[]` 의 `before` 를 **현재 파일**에서 찾아 `after` 로 바꿔 쓴다 — md 와 같은 방식. 못 찾는 항목(내가 그 문장을 이미 바꿨을 때)은 그 항목만 사용자에게 알린다. 생성 스크립트가 있으면 원본에 옮기고 재생성한다.
   - **파일을 쓰기 직전에 다시 읽는다.** 내가 반영하는 동안 사용자가 저장했을 수 있다(그 경우 `conflict` 없이 파일에 이미 들어와 있다). 옛 버퍼로 덮어쓰면 그 저장이 사라진다.
   - **`source: "md"`** — .md 산출물. 편집 화면은 md 를 렌더한 것이고 **파일에 저장되지 않았다.** `edits[]` 의 `before` 문장을 md 원문에서 찾아 `after` 로 바꿔 쓴다(한두 글자 수정이 대부분이라 문자열 치환으로 충분하다. 못 찾으면 그 항목만 사용자에게 알린다). 댓글은 HTML 과 같다.
   - **`final: true`** — 사용자가 초록 [마무리] 를 눌렀다. "이걸로 끝, 더 고칠 것 없음" 이다. `edits` 가 있으면 반영 확인만 하고(파일엔 이미 저장돼 있다. 생성 스크립트가 있으면 원본에도 옮긴다), 댓글은 없다. 처리 뒤 `--ack` 하고 **`--close` 로 그 문서의 서버를 내린다** — 마무리는 편집기를 닫으라는 뜻이다. `final` 이면 `approved` 도 true 다.
   - `approved: true`는 **해당 문서 검토의 이상 없음**이다. 다른 문서의 댓글을 무효화하지 않고 외부 배포·공유를 새로 승인하지 않는다. 기존에 승인된 후속 작업만 계속한다.
   - **반영하는 동안에도 사용자는 계속 고친다.** 저장하기 직전에 그 문서의 `status: new` 줄을 **다시 읽어**, 작업을 시작한 뒤 들어온 제출까지 함께 반영한다. 제출마다 따로 답하지 말고 **한 번 저장하고 한 번 보고한다** — 화면에도 "제출 N건 대기 중 — 모아서 한 번에 반영합니다" 로 뜬다. 여러 건을 처리했으면 ID 마다 `--ack` 를 실행한다.
   - 파일을 고쳐 저장했는데 사용자가 그때 화면에서 수정 중이면 편집기는 **새로 고치지 않고** `[새 판 불러오기]` 버튼과 함께 알린다. 사용자가 그 상태로 저장하면 서버가 409 로 막고 덮어쓸지 물어본다 — 사용자의 수정과 내 새 판 중 무엇이 남는지는 사용자가 정한다.
   - 처리를 끝낸 뒤 `python3 <스킬>/review.py "<문서>" --ack "<이벤트 UUID>" --result "반영 요약" --changes '<JSON>'` 을 실행한다. **`--changes` 로 고친 곳을 함께 넘긴다** — 상단 바에 [변경사항 확인 (N)] 이 생기고, 거기에 커서를 올리면 그 요소들에 노란 테두리가 보인다(누르면 고정). 고정한 뒤 요소에 커서를 올리면 무엇을 왜 바꿨는지 뜬다. 사용자가 문서를 다시 훑지 않고도 반영 결과를 확인한다.
     ```
     --changes '[{"n":1,"what":"집계 기준(2026년 5월 19,161곳)을 문장에 넣었다","why":"근거 없는 서술이라 인용될 때 기준을 되묻는다"}]'
     ```
     `n` 은 댓글 번호 — 그 댓글의 요소에 표시된다. 댓글과 **다른 곳**을 고쳤으면 `path` 를 직접 준다(CSS 선택자). `what` 은 필수, `why` 는 한 문장이면 된다. **`--result` 는 상태줄 한 줄에 잘려 보인다** — 요약은 한 문장으로, 상세는 `--changes` 의 what/why 에 넣는다(전문은 커서를 올리면 보인다). 사용자가 직접 고친 `edits` 는 표시 대상이 아니다 — 자기가 한 일이다. 문서·ID를 검증하고 잠금 아래 `status: done`을 기록한다. 화면에도 완료 상태가 표시된다. 큐 전달 성공만으로 done 처리하지 않는다.
   - **끝났으면 내린다.** `approved: true` 를 받았거나 사용자가 "됐어·끝·더 없어" 라고 하면 `python3 <스킬>/review.py "<문서>" --ack … ` 뒤에 `python3 <스킬>/review.py "<문서>" --close` 를 실행해 **그 문서의 서버만** 내린다. `--ack` 만으로는 내리지 않는다 — 사용자가 반영 결과를 보고 더 고칠 수 있다. 다른 문서 서버는 여전히 건드리지 않는다(`pkill -f review.py` 금지). 안전망으로 서버는 브라우저 탭이 닫혀 요청이 끊긴 뒤 `--idle`(기본 120분) 이 지나면 스스로 종료하고, 미처리 제출이 남았으면 로그에 그 사실을 남긴다.
   - 구형 ID 없는 이벤트는 원문을 보존해 처리하고 고유 UUID를 부여한 후 ack한다. 같은 파일의 다른 문서·새 이벤트를 덮어쓰지 않는다. 부분 처리 중인 댓글은 done으로 표시하지 않는다.
   - 편집기는 파일 변경을 2초마다 감지해 **자동으로 새로 고친다**. 사용자가 편집 중이면 저장 뒤에 불러온다. 파일을 고쳐 저장하는 것으로 끝이다.
5. 세션이 바뀌면 다음 세션이 `_review_events.jsonl` 의 `status: new` 줄을 먼저 처리한다.

## 사용자 조작

| 조작 | 결과 |
|---|---|
| 이중클릭 | 그 자리에서 글자 수정 (서식·링크 유지). 바깥 클릭으로 끝 |
| 우클릭 | 그 요소에 댓글. 문구를 드래그해 고른 뒤 우클릭하면 **그 문구에만** 댓글. 적기 전이면 바깥 클릭·Esc 로 닫힘 |
| 우클릭 — 그림·아이콘 | 댓글창 인용 자리에 **실물을 52px 로 축소해 보여준다**(img·svg·canvas·video). 버튼 속 아이콘을 고르면 아이콘이 아니라 그 버튼이 대상이 된다. 라벨(`[버튼] 메뉴 열기`)은 화면에 띄우지 않고 제출 데이터의 `anchor` 로만 넘어간다 — 라벨은 에이전트가 읽는 것이지 사용자가 읽을 것이 아니다 |
| 상단 바 [세션 선택칸] | **이 문서를 지켜보는 세션이 둘 이상일 때만** 나타난다(fork 로 갈라진 경우). 고른 세션이 그 제출의 `owner` 가 된다 |
| 상단 바 [종합댓글달기] | 특정 부분이 아닌 **문서 전체에 대한 종합 댓글**. 핀이 붙지 않고 `path` 가 빈 문자열로 전달된다 |
| 상단 바 [변경사항 확인 (N)] (검정) | 에이전트가 `--changes` 로 넘긴 고친 곳. **커서를 올린 동안만** 노란 테두리가 보이고, 누르면 고정된다(다시 누르면 해제). 고정 상태에서 요소에 커서를 올리면 무엇을 왜 바꿨는지 뜬다. 평소 화면은 깨끗하다 |
| 상단 바 [마무리] (초록) | 댓글이 없을 때만 보인다. **수정이 없든 있든** "좋다, 이걸로 끝" — 수정은 반영 확인만 받고 편집기가 닫힌다. 댓글을 하나라도 달면 사라지고 [제출] 만 남는다 |
| [제출] 버튼에 커서 | **어느 세션으로 가는지** 뜬다 — 훅이 띄운 서버는 `작업 폴더 · 세션 ID 앞 8자`. 손으로 띄울 때는 `--session-label` 로 이름을 준다 |
| Enter | 댓글 보내기 (Shift+Enter 줄바꿈). 보낸 자리에 이니셜 마커 |
| Cmd+S · [저장] | 파일 덧쓰기. 첫 저장 때 `.bak` |
| [진행중인 <Agent> Session에 제출] | 저장 후 연결된 세션 큐에 알림. 미연결·실패면 수동 전달 안내. 변경·댓글이 없으면 해당 문서의 검토 승인으로 저장 |

## 원칙

- 글자 수정과 댓글만 지원한다. 요소 추가·삭제·이동은 댓글로 받아 에이전트가 한다.
- **.md 는 저장 없이 제출로만 반영한다.** 화면은 보기용 렌더(제목·문단·목록·표·코드·인용)이고 원문 복원용이 아니다. 에이전트가 before→after 치환으로 원문을 고치므로 표·중첩 구조가 깨지지 않는다.
- 규약·설정 성격의 md(CLAUDE.md·AGENTS.md·README.md·SKILL.md·handoff·STATUS 등)와 `.agents/`·`.claude/` 아래 파일은 훅이 산출물로 보지 않는다.
- 저장은 브라우저 DOM 을 그대로 직렬화한다. 클래스·인라인 CSS·SVG 가 깎이지 않는다. 브라우저 확장이 끼운 요소와 편집기 자체는 저장에서 걸러진다.
- **사용자가 저장한 HTML 이 그 시점부터 원본이다.** 재생성 전에 `.bak` 존재를 확인하고, 있으면 원본(md·json)에 먼저 수정을 반영한다.
- 서식과 무관하다. 어떤 HTML 에도 붙는다. 다른 스킬(예: openub-report)이 저장 훅이 필요하면 환경변수(`OPENUB_REPORT_LIB`)로 연동한다.

## 파일

| 파일 | 역할 |
|---|---|
| `review.py` | 편집기 서버 + 브라우저 UI + 완료 ack · `--close` 종료 CLI (탭 닫힘 뒤 `--idle` 분 유휴면 자동 종료) |
| `events.py` · `test_events.py` | 제출 저장·Codex queue·상태 갱신, 격리 회귀 검사 |
| `publish.sh` | 공개 저장소(GitHub `seungmin0209/review-ai-artifacts`) 동기화 + push. **이 폴더를 커밋할 때마다 함께 실행한다** — 공개본이 뒤처지면 마켓플레이스 사용자는 옛 코드를 받는다 (2026-09-15~17 이틀치 18커밋이 밀렸던 전례) |
| `hook.py` · `register_hook.py` | PostToolUse(Write·Edit·Bash) + Stop 훅과 그 등록 스크립트 |
| `~/.config/review-ai-artifacts/state.json` | 세션별 처리 기록(중복 발동 방지) |
| `install.sh` · `install.ps1` | 파이썬 3 확인·설치 + 스킬 폴더 배치 (Mac/Linux · Windows) |
| `README.md` | Codex · Gemini 등 Claude 외 에이전트용 요약 |
| `~/.config/review-ai-artifacts/config.json` | 사용자 설정 (mode · cases · initial · agent) |
| `<문서 폴더>/_review_events.jsonl` | 제출 기록. gitignore 대상 |

## QA 문서 피드백

사용자가 직접 재현하려는 QA 목록에는 제품 화면 이름·진입 경로·대상 주소/기간·조작·기대/관측 결과를 적는다. 번호 ID만으로 화면을 설명하지 않는다. 확보한 실제 스크린샷을 해당 문제 옆에 붙이고, 정지 이미지로 클릭 전후 동작을 입증하지 않는다. 영상이 없으면 없다고 밝힌다. 코드상 가능성은 실제 재현과 구분하며 가짜 화면을 만들지 않는다. 의도된 사양이라는 사용자 판정은 이슈 분류에 반영한다.
