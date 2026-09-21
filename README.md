# review-ai-artifacts — Edit & Tell <Agent> what to do

**설치는 AI 에게 한 줄.** Claude Code(또는 Codex·Gemini) 에 이렇게 말한다:

> `https://github.com/seungmin0209/review-ai-artifacts` 보고 review-ai-artifacts 깔아줘

에이전트가 할 일 (이 README 를 읽은 에이전트는 그대로 따른다):
1. **Claude Code 라면 터미널 명령 두 줄로 플러그인을 설치한다.** 파일 복사·권한 문제가 없고, 자동 발동 훅이 함께 설치된다.
   ```bash
   claude plugin marketplace add seungmin0209/review-ai-artifacts
   claude plugin install review-ai-artifacts@review-ai-artifacts
   ```
   끝나면 "새 Claude Code 세션부터 적용된다. 첫 HTML 을 만들 때 발동 방식을 묻는다" 고 알린다. 갱신은 `claude plugin update review-ai-artifacts@review-ai-artifacts`.
2. Claude Code 가 아니거나(Codex·Gemini) 1 이 안 되면 로컬 설치:
   `git clone https://github.com/seungmin0209/review-ai-artifacts ~/.config/review-ai-artifacts/repo` 후
   Mac/Linux `sh ~/.config/review-ai-artifacts/repo/plugins/review-ai-artifacts/install.sh` · Windows `powershell -ExecutionPolicy Bypass -File $HOME\.config\review-ai-artifacts\repo\plugins\review-ai-artifacts\install.ps1`
   (파이썬 3 가 없으면 스크립트가 설치하고, `~/.claude/skills/review-ai-artifacts` 배치와 PostToolUse 훅 등록까지 한다.
   `~/.claude` 쓰기가 막혀 실패하면 그 한 줄만 사용자에게 보여 직접 실행하게 한다.)

**그 뒤로도 전부 자연어다.** "review-ai-artifacts 업데이트해줘" · "리뷰 모드 물어봐로" · "편집기 열어줘" · "review-ai-artifacts 지워줘" — 에이전트가 대응 명령을 대신 친다(SKILL.md 표).

사람이 직접 하려면 Claude Code 입력창에 `/plugin marketplace add seungmin0209/review-ai-artifacts` → `/plugin install review-ai-artifacts@review-ai-artifacts`.

플러그인과 로컬 설치를 **둘 다** 하지 않는다 — 스킬과 훅이 두 번 뜬다. 로컬 설치를 지우려면 `python3 ~/.claude/skills/review-ai-artifacts/register_hook.py --remove` 후 폴더 삭제.

---

AI 와 함께 만든 아티팩트(.html · .md)를 브라우저에서 바로 고치고(이중클릭), 문구에 댓글을 달아(우클릭) 작업 중인 에이전트 세션에 돌려보내는 도구. 특정 부분이 아닌 총평은 상단 바 [종합댓글달기] 로 남긴다. md 는 렌더해 보여 주고, 수정은 제출 시 에이전트가 원문에 반영한다.

그림·아이콘에도 댓글을 달 수 있다. 이미지·SVG·캔버스·영상을 우클릭하면 댓글창 인용 자리에 **실물이 52px 로 축소되어** 보이므로 무엇에 대한 말인지 헷갈리지 않는다. 버튼 안의 아이콘을 골라도 대상은 그 버튼이 된다.
Claude Code · Codex · Gemini CLI 어디서든 같은 화면. 파이썬 3 표준 라이브러리만 쓴다 (Mac/Windows/Linux).

```bash
sh install.sh                                          # Mac/Linux — 파이썬 3 없으면 설치까지
powershell -ExecutionPolicy Bypass -File install.ps1   # Windows  — winget 으로 파이썬 3 설치까지
python3 review.py <문서.html> --agent Codex            # Windows 는 python. http://localhost:8901
```

파이썬 3 외 의존성은 없다. 에이전트가 설치 스크립트를 대신 실행해도 된다. `~/.claude` 쓰기가 막힌 환경이면 zip 을 풀어 넣는 한 줄만 직접 실행한다
(Mac `unzip ~/Downloads/review-ai-artifacts.zip -d ~/.claude/skills/` · Windows `Expand-Archive "$HOME\Downloads\review-ai-artifacts.zip" -DestinationPath "$HOME\.claude\skills\" -Force`).

설치 스크립트가 PostToolUse 훅을 등록해, 에이전트가 .html 을 저장할 때마다 스킬 이름을 부르지 않아도 자동으로 발동한다.

에이전트 규약(무엇을 언제 띄우고, 제출 이벤트를 어떻게 처리하는지)은 `SKILL.md` 에 있다. Claude Code 는 스킬로 자동 로드되고,
Codex 는 `AGENTS.md` 에, Gemini 는 `GEMINI.md` 에 "HTML 산출물은 review-ai-artifacts 규약(SKILL.md)으로 띄운다" 한 줄을 넣으면 같은 규약을 따른다.

제출 이벤트는 `<문서 폴더>/_review_events.jsonl` 에 한 줄 JSON 으로 쌓인다:
`{"edits":[{path,before,after}], "comments":[{n,path,anchor,quote,text}], "doc", "agent", "ts", "status":"new"}`

한 문서를 **여러 세션이 함께 지켜볼 때**(fork 로 갈라진 경우) 상단 바에 제출 대상 선택칸이 뜬다. 고른 세션이 그 제출의 주인이 되므로 각 세션이 자기 것만 받아 간다. 손으로 띄울 때는 `--session-label` 로 선택칸에 보일 이름을 준다.

반영을 마치면 `--ack … --changes '[{n,what,why}]'` 로 고친 곳을 함께 기록한다. 상단 바 [변경사항 확인] 에 커서를 올리면 그 요소들에 노란 테두리가 보이고, 누르면 고정된 채 무엇을 왜 바꿨는지 볼 수 있다.

## Codex 제출 연결

`--agent Codex`는 표시 이름만 바꾼다. 자동 전달에는 현재 세션의 `CODEX_THREAD_ID`(또는 `--thread <UUID>`)와 `codex queue` 지원 CLI가 필요하다. 서버는 제출을 파일에 먼저 저장한 뒤 해당 UUID에 알림을 보낸다. 다른 세션이나 `--last`로 대체하지 않는다.

화면은 저장·큐 접수·반영 완료를 구분한다. 에이전트는 실제 반영 후 `python3 review.py <문서> --ack <제출ID> --result <요약>`으로 완료를 기록하고, 검토가 끝나면(approved 또는 사용자의 완료 표시) `python3 review.py <문서> --close`로 그 문서의 서버만 내린다. 서버는 탭이 닫혀 요청이 끊긴 뒤 `--idle`(기본 120분)이 지나면 스스로 종료한다. 미연결·실패 시 제출은 보존되고 `전달 요청 복사`가 표시된다. 파일 tail만으로 종료된 Codex 턴이 다시 시작되지는 않는다. Claude Code의 PostToolUse/Stop 훅도 Codex에 자동 적용되지 않는다.

검증: `python3 test_events.py`. 실환경 연결은 테스트 문서 제출 후 현재 세션의 수신까지 별도로 확인한다. 기존 실행 서버는 파일만 고쳐도 새 코드로 바뀌지 않으므로 `/doc`로 대상 확인 후 해당 서버만 재시작한다.
