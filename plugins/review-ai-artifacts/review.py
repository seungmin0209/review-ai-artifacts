#!/usr/bin/env python3
"""review-ai-artifacts — Edit & Tell <Agent> what to do. AI 와 함께 만든 HTML 을 브라우저에서 바로 고치고 댓글을 달아 에이전트에게 돌려보낸다.
Claude Code · Codex · Gemini CLI 등 어느 에이전트와도 쓴다. 화면 문구의 에이전트 이름은 --agent 로 정하거나 환경변수로 감지한다.

    python3 review.py <문서.html | 문서.md> [--port 8901]

브라우저에서:
- 더블클릭 = 그 자리에서 글자 수정 · 바깥 클릭 = 끝 · Cmd+S / [저장] = 파일 덧쓰기(첫 저장 때 .bak)
- .md 는 보기용으로 렌더해 띄운다. 화면에서 파일을 쓰지 않고, 제출 이벤트(before/after)로 에이전트가 원문에 반영한다 (source: md)
- 우클릭 = 그 요소에 댓글. 문구를 드래그해 고른 뒤 우클릭하면 그 문구에만 댓글
- [진행중인 <Agent> Session에 제출] = 파일에 기록. Claude 는 훅·Monitor 가 이벤트 파일을 받고, Codex 는 세션 ID가 있으면 codex queue 로 알림. 저장·큐 접수·반영 완료는 별도 상태.
  변경·댓글 없이 누르면 approved=true — "이상 없음" 승인으로 전달된다

에이전트 쪽: 이 스크립트를 띄운 세션이 이벤트 파일을 지켜본다(SKILL.md / README.md).
문서에 <script id="oub-meta"> 가 있고 OPENUB_REPORT_LIB 환경변수가 있으면 저장 때 수정일·이력을 갱신한다(openub-report 연동, 선택).
ponytail: 글자 수정과 댓글만. 요소 추가·삭제·이동은 댓글로 에이전트에게 맡긴다.
"""
import sys, os, re, json, pathlib, datetime, webbrowser, http.server, argparse, shutil, threading, time, unicodedata, urllib.parse
def nfc(s): return unicodedata.normalize("NFC", str(s))   # macOS 한글 파일명(NFD) 과 사람이 친 경로(NFC) 를 같게 본다
import events as review_events
from html import escape as html_escape
for _st in (sys.stdout, sys.stderr):   # Windows 기본 cp949 파이프에서 한글·기호가 깨지거나 훅이 죽는다
    try: _st.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

CONFIG = pathlib.Path.home() / ".config" / "review-ai-artifacts" / "config.json"   # 사용자별 설정(mode·cases·initial·agent). SKILL.md 참조
AGENT_ENV = [("CLAUDECODE", "Claude"), ("CLAUDE_CODE_ENTRYPOINT", "Claude"), ("CODEX_THREAD_ID", "Codex"), ("CODEX_SANDBOX", "Codex"), ("CODEX_HOME", "Codex"),
             ("GEMINI_CLI", "Gemini"), ("GEMINI_API_KEY", "Gemini"), ("CURSOR_TRACE_ID", "Cursor"), ("COPILOT_AGENT", "Copilot")]
def detect_agent():
    for k, v in AGENT_ENV:
        if os.environ.get(k): return v
    return None
ap = argparse.ArgumentParser(); ap.add_argument("doc", nargs="?"); ap.add_argument("--port", type=int, default=None, help="생략하면 문서 경로로 정해지는 고정 포트(8901~8990). 같은 문서는 항상 같은 포트"); ap.add_argument("--no-open", action="store_true")
ap.add_argument("--set-mode", choices=["always", "ask", "cases", "off"], help="발동 방식 저장 후 종료")
ap.add_argument("--cases", default="", help="--set-mode cases 일 때 쉼표 목록. 예: artifact,report,dashboard")
ap.add_argument("--show-config", action="store_true")
ap.add_argument("--set-initial", help="댓글 마커에 보일 한 글자 (예: 승)")
ap.add_argument("--agent", help="화면에 표시할 에이전트 이름: Claude · Codex · Gemini … (기본: 환경변수로 감지, 없으면 설정값, 없으면 'AI')")
ap.add_argument("--set-agent", help="기본 에이전트 이름을 설정에 저장")
ap.add_argument("--thread", help="Codex 제출 대상 UUID. 기본 CODEX_THREAD_ID. --agent는 표시명일 뿐 전달 경로가 아님")
ap.add_argument("--manual", action="store_true", help="자동 전달 없이 제출 기록만 저장")
ap.add_argument("--session", help="이 서버를 띄운 세션 ID. 제출 신호가 이 세션 것임을 표시한다. 생략하면 프로세스 고유값")
ap.add_argument("--session-label", help="제출 버튼에 커서를 올리면 보이는 세션 이름. 예: 'Seungmin-OUBSST · 4f20a925'. 생략하면 세션 ID 앞 8자")
ap.add_argument("--ack", help="반영을 완료한 제출 ID")
ap.add_argument("--result", default="반영 완료", help="--ack 처리 결과")
ap.add_argument("--changes", help='--ack 와 함께: 무엇을 왜 바꿨는지. JSON 목록 [{"n":1,"what":"...","why":"...","path":"(생략하면 그 댓글의 요소)"}]. 화면에서 노란 테두리로 보인다')
ap.add_argument("--close", action="store_true", help="이 문서의 편집기 서버만 내린다 (다른 문서 서버는 그대로)")
ap.add_argument("--idle", type=int, default=120, help="브라우저 탭이 닫혀 요청이 이만큼(분) 없으면 스스로 종료. 0 이면 끄지 않음")
A = ap.parse_args()
cfg = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
INITIAL = cfg.get("initial", "나")
AGENT = A.agent or detect_agent() or cfg.get("agent") or "AI"
if A.set_mode or A.show_config or A.set_initial or A.set_agent:
    if A.set_mode:
        cfg.update(mode=A.set_mode, cases=[c.strip() for c in A.cases.split(",") if c.strip()], updated=datetime.date.today().isoformat())
    if A.set_initial: cfg["initial"] = A.set_initial[:1]
    if A.set_agent: cfg["agent"] = A.set_agent
    if A.set_mode or A.set_initial or A.set_agent:
        CONFIG.parent.mkdir(parents=True, exist_ok=True); CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(cfg, ensure_ascii=False) if cfg else "설정 없음 — 첫 사용. SKILL.md 의 '처음 한 번 묻기' 절을 따른다"); sys.exit(0)
if not A.doc: raise SystemExit("HTML 파일 경로를 준다")
DOC = pathlib.Path(A.doc).resolve(); assert A.close or (DOC.is_file() and DOC.suffix.lower() in (".html", ".htm", ".md", ".markdown")), "HTML 또는 md 파일 하나를 준다"   # --close 는 파일이 지워진 뒤에도 서버를 내릴 수 있어야 한다

def pick_port(doc, want=None):
    """문서별 고정 포트. 이미 그 포트에 같은 문서가 떠 있으면 (port, True). 다른 문서가 쓰고 있으면 다음 빈 포트."""
    import socket, urllib.request, zlib
    start = want or 8901 + zlib.crc32(str(doc).encode()) % 90
    order = list(range(start, 8991)) + list(range(8901, start))
    busy = []
    for p in order:   # 빈 포트에서 멈추지 않고 전 구간을 본다 — --port 로 다른 자리에 떠 있는 같은 문서도 찾아야 한다
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) == 0: busy.append(p)
    for p in busy:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{p}/doc", timeout=0.3) as r:
                if nfc(r.read().decode("utf-8","replace")) == nfc(doc): return p, True
        except Exception: pass
    free = next((p for p in order if p not in busy), None)
    if free is None: raise SystemExit("8901~8990 포트가 모두 사용 중")
    return free, False
EVENTS = DOC.parent / "_review_events.jsonl"
OWNER = A.session or os.environ.get("REVIEW_OWNER_SESSION") or f"pid-{os.getpid()}"   # 이 문서를 누구에게 돌려보낼지
OWNER_LABEL = A.session_label or os.environ.get("REVIEW_OWNER_LABEL") or (OWNER if OWNER.startswith("pid-") else OWNER[:8])
THREAD = (A.thread or os.environ.get("CODEX_THREAD_ID")) if AGENT.lower() == "codex" and not A.manual else None
CODEX = shutil.which("codex") if THREAD else None
if THREAD:
    import uuid
    THREAD = str(uuid.UUID(THREAD))  # Exact session only; never route by display name or --last.
if A.ack:
    row = next((r for r in review_events.read(EVENTS) if r.get("id") == A.ack), None)
    if row is None or row.get("doc") != str(DOC): raise SystemExit("이 문서의 제출 ID가 아닙니다")
    fields = dict(status="done", result=A.result)
    if A.changes:
        try: items = json.loads(A.changes)
        except json.JSONDecodeError as e: raise SystemExit(f"--changes 가 JSON 이 아닙니다: {e}")
        if not isinstance(items, list): raise SystemExit("--changes 는 목록이어야 합니다")
        by_n = {c.get("n"): c for c in row.get("comments", [])}
        out = []
        for it in items:
            if not isinstance(it, dict) or not it.get("what"): raise SystemExit("--changes 의 각 항목에 what 이 필요합니다")
            path = it.get("path") or (by_n.get(it.get("n")) or {}).get("path")
            if path is None: raise SystemExit(f"--changes 항목 n={it.get('n')} 의 path 를 찾지 못했습니다 — path 를 직접 주세요")
            out.append({"n": it.get("n"), "path": path, "what": it["what"], "why": it.get("why", "")})
        fields["changes"] = out
    review_events.update(EVENTS, A.ack, **fields)
    print("반영 완료 기록:", A.ack + (f" · 변경 표시 {len(fields['changes'])}건" if A.changes else ""))
    sys.exit(0)
def port_closed(port, wait=3.0):
    """포트가 실제로 닫힐 때까지 기다린다. 닫혔으면 True."""
    import socket
    end = time.time() + wait
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0: return True
        time.sleep(.15)
    return False
def listening_pids(port):
    """그 포트를 LISTEN 중인 PID 목록. macOS·Linux 는 lsof, Windows 는 netstat."""
    import subprocess
    try:
        if os.name == "nt":
            out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
            return sorted({l.split()[-1] for l in out.splitlines() if f":{port} " in l and "LISTENING" in l})
        return subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()
    except FileNotFoundError:
        return []
def kill_port(port, why):
    import signal
    pids = listening_pids(port)
    for pid in pids:
        try: os.kill(int(pid), signal.SIGTERM)
        except OSError: pass
    if not pids: print(f"편집기 종료 확인 불가({why}): 포트 {port} 의 PID 를 찾지 못했습니다", flush=True); return
    print(f"편집기 종료({why}, PID {' '.join(pids)}): {DOC.name} (포트 {port})"
          + ("" if port_closed(port) else " — 아직 응답합니다. 직접 확인하세요"), flush=True)

PORT, ALREADY = pick_port(DOC, A.port)
if A.close:
    if not ALREADY: print(f"떠 있지 않음: {DOC.name}" + ("" if A.port else " — 8901~8990 만 훑었다. --port 로 다른 자리에 띄웠다면 같은 --port 를 함께 준다")); sys.exit(0)
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/quit", data=b"", method="POST"), timeout=3) as r: print(r.read().decode())
    except urllib.error.HTTPError:   # /quit 이 없는 구형 서버 — 포트로 PID 를 찾아 내린다
        kill_port(PORT, "구형 서버")
    else:
        if not port_closed(PORT): kill_port(PORT, "응답은 왔지만 내려가지 않음")   # 응답만으로 성공을 보고하지 않는다
    sys.exit(0)
if ALREADY:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r: health = json.load(r)
        if health.get("owner") and health.get("owner") != OWNER:   # 다른 세션이 이 문서를 맡고 있다 — 신호를 가로채지 않는다
            print(f"주의: 이 문서는 다른 세션({health['owner']})이 검토 중입니다. 제출은 그 세션으로 갑니다. "
                  f"이 세션이 이어받아야 하면 사용자에게 확인한 뒤 --close 로 내리고 다시 띄우세요.", flush=True)
        if health.get("thread_id") != THREAD or health.get("version", 0) < 2:
            print("주의: 기존 서버의 전달 연결이 현재 세션과 다릅니다. /doc와 PID 확인 후 해당 서버만 재시작하세요.", flush=True)
    except Exception:
        print("주의: 기존 서버는 전달 상태를 지원하지 않습니다. /doc와 PID 확인 후 해당 서버만 재시작하세요.", flush=True)
    print(f"이미 떠 있음: http://localhost:{PORT}/  ({DOC.name})", flush=True); sys.exit(0)
IS_MD = DOC.suffix.lower() in (".md", ".markdown")
EVENTS = DOC.parent / "_review_events.jsonl"

UI = r"""
<style id="__rv_css">
[data-rv-hover]{outline:2px dashed #b45f06;outline-offset:2px;cursor:text}
[data-rv-hover]:empty,[contenteditable]:empty{min-width:24px;min-height:1em;display:inline-block}
[data-rv-target]{outline:2px solid #d97706!important;outline-offset:2px}
[contenteditable="plaintext-only"]{outline:2px solid #2f6bdc;outline-offset:2px;background:rgba(47,107,220,.06)}
[data-rv-note]{outline:2px solid rgba(120,140,170,.6);outline-offset:2px}
mark[data-rv-mark]{background:rgba(128,140,160,.35);color:inherit;border-radius:3px;padding:0 1px}
[data-rv-changed]{outline:2px solid #e0a000;outline-offset:3px;border-radius:2px;background:rgba(224,160,0,.07)}
#__rv_tip{position:absolute;z-index:100001;max-width:380px;background:#2b2b2b;color:#ececec;border:1px solid #e0a000;border-radius:10px;padding:10px 13px;
  font:13px/1.55 -apple-system,system-ui,"Apple SD Gothic Neo",sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.4);pointer-events:none}
#__rv_tip b{display:block;color:#f0c040;font-size:12px;margin-bottom:4px}#__rv_tip i{display:block;color:#a8a8a8;font-style:normal;margin-top:6px}
.__rv_pin{position:absolute;z-index:99998;width:30px;height:30px;border-radius:50%;background:#2b2b2b;color:#e8e8e8;border:3px solid #2f6bdc;
  display:flex;align-items:center;justify-content:center;font:600 12px/1 -apple-system,system-ui,sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.35);cursor:pointer}
.__rv_pin[data-n]::after{content:attr(data-n);position:absolute;right:-6px;top:-6px;background:#c96442;color:#fff;border-radius:9px;font-size:10px;padding:1px 5px}
#__rv_pop .list{margin:0 0 10px;padding:0;list-style:none;max-height:160px;overflow:auto}#__rv_pop .list li{display:flex;gap:8px;align-items:flex-start;padding:6px 0;border-bottom:1px solid #3a3a3a;font-size:14px;color:#ddd}
#__rv_pop .list li b{color:#9aa4b2;font-weight:600;min-width:22px}#__rv_pop .list li span{flex:1}#__rv_pop .list li button{background:none;border:0;color:#8a8a8a;cursor:pointer;font-size:14px;padding:0 4px}#__rv_pop .list li button:hover{color:#f87171}
#__rv_bar{position:fixed;left:0;right:0;top:0;z-index:99999;display:flex;gap:10px;align-items:center;color-scheme:dark;
  padding:9px 18px;background:#1f1f1f;color:#d4d4d4;font:13px/1.4 -apple-system,system-ui,sans-serif;border-bottom:1px solid #333}
body{padding-top:50px!important}
#__rv_bar b{color:#fff;margin-right:6px;letter-spacing:-.2px}#__rv_bar button{font:inherit;padding:6px 14px;border-radius:8px;border:1px solid #3a3a3a;background:#2b2b2b;color:#e8e8e8;cursor:pointer}
#__rv_bar button.pri{background:#c96442;border-color:#c96442;color:#fff;font-weight:600}#__rv_bar button.pri.off,#__rv_bar button.fin.off{background:#4a4a4a;border-color:#5a5a5a;color:#bdbdbd}#__rv_bar .warn{color:#f0c040}#__rv_bar button.fin{background:#1f8a4c;border-color:#1f8a4c;color:#fff;font-weight:600}#__rv_bar #__rv_marks.on{border-color:#e0a000;color:#f0c040}#__rv_bar button:disabled{opacity:.45;cursor:default}#__rv_bar .st{color:#8a8a8a}#__rv_bar .hint{margin-left:auto;color:#8a8a8a;text-align:right}
#__rv_pop{position:absolute;z-index:100000;color-scheme:dark;background:#2b2b2b;color:#ececec;border:1px solid #3d3d3d;border-radius:16px;padding:18px 22px 16px;
  box-shadow:0 12px 40px rgba(0,0,0,.45);width:560px;max-width:calc(100vw - 32px);font:15px/1.5 -apple-system,system-ui,"Apple SD Gothic Neo",sans-serif}
/* 문서 쪽 CSS(overflow-wrap:anywhere, word-break, writing-mode 등)가 새어 들어와 글자가 한 자씩 세로로 끊기는 것을 막는다 */
#__rv_bar,#__rv_pop,.__rv_pin,#__rv_bar *,#__rv_pop *{word-break:keep-all;overflow-wrap:normal;white-space:normal;writing-mode:horizontal-tb;letter-spacing:normal;text-transform:none;text-align:left;box-sizing:border-box}
#__rv_bar *,#__rv_pop *{position:static;float:none;min-width:0;max-width:none;min-height:0;transform:none}
#__rv_bar,#__rv_bar *{white-space:nowrap}#__rv_bar{flex-wrap:nowrap;min-height:50px;box-sizing:border-box}
#__rv_bar button,#__rv_bar b,#__rv_bar select{flex:0 0 auto}   /* 버튼은 줄어들지 않는다 — 줄어드는 건 상태줄과 안내문만 */
#__rv_bar #__rv_to{font:inherit;font-size:13px;max-width:240px;padding:6px 8px;border-radius:8px;border:1px solid #3a3a3a;background:#2b2b2b;color:#e8e8e8;cursor:pointer}   /* 지켜보는 세션이 둘 이상일 때만 나타난다 */
#__rv_bar .st{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis}#__rv_bar .hint{flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis}
#__rv_pop .t{color:#8f8f8f;font-size:15px;margin-bottom:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#__rv_pop .a{color:#a8a8a8;font-size:14px;border-left:2px solid #6b6b6b;padding-left:10px;margin-bottom:12px;max-height:44px;overflow:hidden}
#__rv_pop .a.th{max-height:none;padding-top:2px;padding-bottom:2px}   /* 그림은 글로 설명하지 않고 실물을 축소해 보여준다 */
/* 체커보드 — 흰 아이콘도 투명 배경도 보인다. 단색 흰 바탕이면 흰 아이콘이 통째로 사라진다 */
#__rv_pop .a .thb{display:inline-flex;align-items:center;justify-content:center;width:52px;height:52px;border-radius:5px;padding:5px;box-sizing:border-box;overflow:hidden;
 background-color:#fff;background-image:linear-gradient(45deg,#dfe2e7 25%,transparent 25%),linear-gradient(-45deg,#dfe2e7 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#dfe2e7 75%),linear-gradient(-45deg,transparent 75%,#dfe2e7 75%);
 background-size:10px 10px;background-position:0 0,0 5px,5px -5px,-5px 0}
#__rv_pop .a .thb>*{max-width:100%;max-height:100%;width:auto;height:auto;object-fit:contain;display:block}
#__rv_pop textarea{width:100%;min-height:64px;font:inherit;font-size:17px;color:#fff;background:transparent;border:0;outline:0;padding:0;resize:none;box-sizing:border-box}
#__rv_pop textarea::placeholder{color:#6f6f6f}
#__rv_pop .sw{margin:-4px 0 6px}#__rv_pop .sw button{font:inherit;font-size:12.5px;color:#9aa4b2;background:none;border:0;padding:0;cursor:pointer;text-decoration:underline dotted}#__rv_pop .sw button:disabled{text-decoration:none;cursor:default;color:#8a8a8a}
#__rv_pop .r{display:flex;align-items:center;justify-content:space-between;margin-top:14px}
#__rv_pop .lbl{color:#e8e8e8;font-size:17px}
#__rv_pop .go{width:44px;height:44px;border-radius:12px;border:0;background:#c96442;color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0}
#__rv_pop .go:disabled{background:#4a3a34;color:#8a7a74;cursor:default}#__rv_pop .go svg{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:2.4;stroke-linecap:round;stroke-linejoin:round}
@media print{#__rv_bar,#__rv_css,#__rv_pop,.__rv_pin{display:none}body{padding-top:0!important}}
</style>
<div id="__rv_bar"><b>Edit &amp; Tell __AGENT__ what to do</b>
<button id="__rv_whole">종합댓글달기</button><button id="__rv_save" hidden disabled>저장</button><button id="__rv_fin" class="fin" title="더 고칠 것 없음 — 수정이 있으면 반영 확인만 받고 이 검토를 끝낸다">마무리</button><button id="__rv_ok" class="pri">진행중인 __AGENT__ Session에 제출</button><button id="__rv_copy" hidden>전달 요청 복사</button><button id="__rv_fresh" hidden>새 판 불러오기</button><button id="__rv_marks" hidden title="커서를 올리면 고친 곳이 노란 테두리로 보이고, 누르면 고정됩니다">변경사항 확인</button><span class="st" id="__rv_st" role="status" aria-live="polite">__DELIVERY_LABEL__</span><span class="hint">이중클릭하여 직접 편집. 우클릭하여 현 __AGENT__ Session에게 Comment</span></div>
<script id="__rv_js">
(function(){
Array.from(document.body.children).forEach(function(x){if(String(x.id||'').indexOf('__rv_')!==0)x.setAttribute('data-rv-orig','')});   // 편집기 요소는 제외 — 표식이 붙으면 저장 때 걸러지지 않는다
var dirty=false,submitted=false,orig=new Map(),notes=[],INITIAL=__INITIAL__,ISMD=__ISMD__,requestId=null,lastEvent=null,STALE=false;   // STALE: 에이전트가 새 판을 올렸지만 내 수정이 있어 불러오지 않은 상태
// [저장] 버튼은 숨겨 둔다 — 제출·마무리가 저장을 포함한다. Cmd+S 로만 남긴다
var bar=document.getElementById('__rv_bar'),st=document.getElementById('__rv_st'),btn=document.getElementById('__rv_save'),ok=document.getElementById('__rv_ok'),fresh=document.getElementById('__rv_fresh'),AGENT='__AGENT__';
fresh.addEventListener('click',function(){if(notes.length||dirty){if(!confirm('지금 화면의 수정과 댓글이 사라집니다. 새 판을 불러올까요?'))return}location.reload()});
document.getElementById('__rv_whole').addEventListener('click',function(e){var r=e.currentTarget.getBoundingClientRect();openPop(null,'',null,r.left+window.scrollX,r.bottom+window.scrollY)});   // 특정 요소가 아닌 문서 전체에 다는 총평
function ours(el){return el.closest('#__rv_bar,#__rv_pop,.__rv_pin')}
var VOID={IMG:1,SVG:1,BR:1,HR:1,INPUT:1,VIDEO:1,CANVAS:1,PICTURE:1,SOURCE:1};
function hasText(el){if(Array.from(el.childNodes).some(function(n){return n.nodeType===3&&n.textContent.trim()}))return true;
  return el.children.length===0&&!VOID[el.tagName]&&(orig.has(el)||el.isContentEditable||/^(H[1-6]|P|LI|TD|TH|SPAN|B|EM|STRONG|SMALL|FIGCAPTION|SUMMARY|LABEL|A|CODE)$/.test(el.tagName))}  // 글자를 다 지운 요소도 다시 잡힌다
function mediaTarget(e){var m=e.target.closest('img,svg,video,canvas,picture,figure');if(!m||ours(m))return null;
  var b=m.closest('button,a,[role=button]');return (b&&!ours(b)&&!b.contains(document.getElementById('__rv_pop')))?b:m}   // 버튼·링크 속 아이콘은 그 버튼을 대상으로 올린다. 이름이 버튼 쪽에 붙어 있다
function target(e){var t=e.target;if(!(t instanceof Element)||ours(t))return null;   // 글자를 직접 품은 가장 가까운 요소 — 태그 종류를 가리지 않는다
  while(t&&t!==document.body&&t!==document.documentElement){if(hasText(t))return t;t=t.parentElement}return null}
function path(el){var p=[];while(el&&el!==document.body){var s=el.tagName.toLowerCase();if(el.id){p.unshift(s+'#'+(window.CSS&&CSS.escape?CSS.escape(el.id):el.id));break}
  var i=1,x=el;while((x=x.previousElementSibling))if(x.tagName===el.tagName)i++;var sib=el.parentElement?Array.from(el.parentElement.children).filter(function(c){return c.tagName===el.tagName}).length:1;
  p.unshift(sib>1?s+':nth-of-type('+i+')':s);el=el.parentElement}return p.join(' > ')}
document.addEventListener('mouseover',function(e){var t=target(e);document.querySelectorAll('[data-rv-hover]').forEach(function(x){x.removeAttribute('data-rv-hover')});if(t&&!t.isContentEditable)t.setAttribute('data-rv-hover','')});
function flatten(t){   // contenteditable 이 붙으면 white-space 가 pre-wrap 이 되어, 소스에만 있던 줄바꿈이 화면에서 갈라진다
  var ws=getComputedStyle(t).whiteSpace;   // 반드시 contenteditable 을 붙이기 전에 읽는다
  if(/^(PRE|TEXTAREA|CODE)$/.test(t.tagName)||/^pre/.test(ws)||ws==='break-spaces')return;   // 줄바꿈이 뜻을 가지는 자리는 건드리지 않는다
  var w=document.createTreeWalker(t,NodeFilter.SHOW_TEXT),n;
  while(n=w.nextNode())if(n.nodeValue.indexOf('\n')>=0)n.nodeValue=n.nodeValue.replace(/[ \t]*\n[ \t]*/g,' ')}
document.addEventListener('dblclick',function(e){var t=target(e);if(!t)return;e.preventDefault();
  flatten(t);
  if(!orig.has(t))orig.set(t,t.innerText);
  if(t.tagName==='A'){t.dataset.rvHref=t.getAttribute('href');t.removeAttribute('href')}
  t.setAttribute('contenteditable','plaintext-only');t.focus();
  t.addEventListener('input',function(){dirty=true;btn.disabled=false;st.textContent=ISMD?'수정됨 — 제출하면 원문에 반영':'수정됨 — 제출하면 파일에 함께 저장됩니다'},{once:true});
  t.addEventListener('blur',function(){t.removeAttribute('contenteditable');brify(t);if(t.dataset.rvHref!==undefined){t.setAttribute('href',t.dataset.rvHref);delete t.dataset.rvHref}},{once:true});
},true);
document.addEventListener('mousedown',function(e){var d=document.getElementById('__rv_pop');if(d&&!d.contains(e.target)&&!d.querySelector('textarea').value.trim())closePop()},true); // 적기 전이면 바깥 클릭으로 닫힘
document.addEventListener('click',function(e){if(ours(e.target))return;var a=e.target.closest('a');if(a&&!e.target.isContentEditable&&!(a.getAttribute('href')||'').startsWith('#')&&!a.hasAttribute('download'))e.preventDefault()},true); // 편집 중 링크 이동 방지
document.addEventListener('contextmenu',function(e){var t=target(e)||mediaTarget(e);if(!t)return;e.preventDefault();
  var sel=window.getSelection(),quote='',range=null;
  if(sel&&!sel.isCollapsed&&t.contains(sel.anchorNode)&&sel.toString().trim()){quote=sel.toString().trim();range=sel.getRangeAt(0).cloneRange()}
  openPop(t,quote,range,e.pageX,e.pageY)});
function aname(el){   // 글자가 없는 요소의 이름은 aria-label·title·alt 에 들어 있다. 자기 자신을 먼저 보고 없으면 자손에서 찾는다
  var a=el.getAttribute('aria-label')||el.getAttribute('title')||el.getAttribute('alt')||'';
  if(!a.trim()){var t=el.querySelector('title');if(t)a=t.textContent||''}
  if(!a.trim()){var d=el.querySelector('[aria-label],[title],img[alt]');
    if(d)a=d.getAttribute('aria-label')||d.getAttribute('title')||d.getAttribute('alt')||''}
  if(!a.trim()){var f=el.closest('figure'),cap=f&&f.querySelector('figcaption');if(cap)a=cap.textContent||''}
  return a.replace(/\s+/g,' ').trim().slice(0,120)}
function gkind(el){   // svg 는 대부분 아이콘이다. 그래프라고 부르려면 크기와 자리가 받쳐줘야 한다
  if(el.closest('button,a,[role=button],nav,header,footer'))return '아이콘';
  var r=el.getBoundingClientRect();return (r.width>=160&&r.height>=100)?'그래프':'아이콘'}
var KIND={img:'이미지',picture:'이미지',video:'영상',canvas:'그래프',figure:'그림',button:'버튼',a:'링크',summary:'접기',label:'입력칸'};
function label(el){var tag=el.tagName.toLowerCase();   // 인라인 SVG 의 tagName 은 소문자라 대문자 비교로는 빗나간다
  if(tag==='img')return '[이미지] '+(el.alt||el.getAttribute('src')||'').slice(0,120);
  if(/^(svg|video|canvas|picture)$/.test(tag))return ('['+(tag==='svg'?gkind(el):KIND[tag])+'] '+aname(el)).trim();
  if(tag==='figure'){var c=el.querySelector('figcaption');return '[그림] '+(c?c.textContent.replace(/\s+/g,' ').trim().slice(0,120):'')}
  var c=el.cloneNode(true);c.querySelectorAll('svg,script,style,canvas').forEach(function(x){x.remove()});c.querySelectorAll('p,div,h1,h2,h3,h4,h5,h6,li,tr,td,th,br,figcaption').forEach(function(x){x.insertAdjacentText('afterend',' ')});var s=c.textContent.replace(/\s+/g,' ').trim();
  if(!s){var g=el.querySelector('svg,canvas'),   // 글자가 없으면 무엇인지부터 밝힌다. svg 가 들었다는 이유만으로 그래프라 부르지 않는다
      k=KIND[tag]||(el.getAttribute('role')==='button'?'버튼':'')||(g?(g.tagName.toLowerCase()==='canvas'?'그래프':gkind(g)):''),
      n=aname(el)||(el.querySelector('figcaption,h1,h2,h3,h4')||{textContent:''}).textContent.replace(/\s+/g,' ').trim().slice(0,120);
    if(k||n)return ('['+(k||'요소')+'] '+n).trim()}
  return s.slice(0,160)}
function thumb(el){   // 그림·아이콘은 글로 설명하는 것보다 실물을 축소해 보여주는 편이 확실하다. 라벨은 화면에서 빼고 제출 데이터에만 싣는다
  var tag=el.tagName.toLowerCase(),
      g=/^(img|svg|canvas|video|picture)$/.test(tag)?el:el.querySelector('img,svg,canvas,video');
  if(!g)return null;
  var t=g.tagName.toLowerCase(),box=document.createElement('span');box.className='thb';
  try{
    if(t==='img'){if(!(g.currentSrc||g.src))return null;var i=new Image();i.src=g.currentSrc||g.src;box.appendChild(i)}
    else if(t==='picture'){var s=g.querySelector('img');if(!s||!(s.currentSrc||s.src))return null;var i2=new Image();i2.src=s.currentSrc||s.src;box.appendChild(i2)}
    else if(t==='svg'){var c=g.cloneNode(true),vb=(g.getAttribute('viewBox')||'').split(/[\s,]+/).filter(Boolean),   // 비율은 viewBox 에서 읽는다 — 100% 로 늘리면 세로로 긴 그림도 정사각 상자에 눌린다
      w=vb.length===4?parseFloat(vb[2]):(parseFloat(g.getAttribute('width'))||g.getBoundingClientRect().width),
      h=vb.length===4?parseFloat(vb[3]):(parseFloat(g.getAttribute('height'))||g.getBoundingClientRect().height);
      c.removeAttribute('width');c.removeAttribute('height');c.removeAttribute('class');c.removeAttribute('style');
      if(w>0&&h>0){c.style.aspectRatio=w+'/'+h;c.style.width=(w>=h?'100%':'auto');c.style.height=(w>=h?'auto':'100%')}
      else{c.style.width='100%';c.style.height='100%'}
      box.appendChild(c)}
    else if(t==='canvas'){var i3=new Image();i3.src=g.toDataURL();box.appendChild(i3)}   // 교차출처로 오염된 캔버스는 여기서 예외가 난다
    else if(t==='video'){if(!g.poster)return null;var i4=new Image();i4.src=g.poster;box.appendChild(i4)}
    else return null;
  }catch(e){return null}
  return box}
function paintA(d,th,txt){var a=d.querySelector('.a');a.classList.remove('th');a.textContent='';
  if(th){a.classList.add('th');a.appendChild(th)}else a.textContent=txt}
function openPop(t,quote,range,x,y){closePop();if(t)t.setAttribute('data-rv-target','');var d=document.createElement('div');d.id='__rv_pop';
  d.style.left=Math.max(8,Math.min(x,window.innerWidth-580+window.scrollX))+'px';d.style.top=(y+10)+'px';
  var wholeRaw=t?label(t):'문서 전체에 대한 종합 댓글',whole=wholeRaw.replace(/</g,'&lt;'),TH=t?thumb(t):null;
  var mine=notes.filter(function(x){return x.el===t});
  var list=mine.length?'<ul class="list">'+mine.map(function(x){return '<li><b>#'+x.n+'</b><span>'+(x.quote?'“'+x.quote.slice(0,40).replace(/</g,'&lt;')+'” · ':'')+x.text.replace(/</g,'&lt;')+'</span><button type="button" data-del="'+x.n+'" title="이 댓글 삭제">✕</button></li>'}).join('')+'</ul>':'';
  d.innerHTML='<div class="t">'+(document.title||location.pathname).replace(/</g,'&lt;')+'</div>'+list+'<div class="a" data-mode="'+(quote?'quote':'whole')+'">'+(quote?quote.slice(0,160).replace(/</g,'&lt;'):whole)+'</div>'
   +(t?'<div class="sw"><button type="button" data-a="sw">'+(quote?'이 요소 전체에 달기':'문구만 고르려면 드래그 후 우클릭')+'</button></div>':'')
   +'<textarea rows="2" placeholder="'+(mine.length?'댓글 추가':'댓글 남기기')+'"></textarea><div class="r"><span class="lbl">Send to __AGENT__</span><button class="go" data-a="ok" disabled aria-label="보내기"><svg viewBox="0 0 24 24"><path d="M12 19V5M5 12l7-7 7 7"/></svg></button></div>';
  document.body.appendChild(d);var ta=d.querySelector('textarea'),go=d.querySelector('.go');ta.focus();
  if(!quote)paintA(d,TH,wholeRaw);
  d.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;
    if(b.dataset.del){var n=+b.dataset.del;notes=notes.filter(function(x){return x.n!==n});refreshPins();closePop();return}   // 댓글 삭제
    if(b.dataset.a==='sw'&&quote){quote='';range=null;paintA(d,TH,wholeRaw);d.querySelector('.a').dataset.mode='whole';b.textContent='요소 전체에 달기로 바꿨습니다';b.disabled=true;ta.focus()}});
  ta.addEventListener('input',function(){go.disabled=!ta.value.trim();ta.style.height='auto';ta.style.height=Math.min(ta.scrollHeight,240)+'px'});
  ta.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();go.click()}});
  go.addEventListener('click',function(){if(!ta.value.trim())return;
    notes.push({n:(notes.length?Math.max.apply(null,notes.map(function(x){return x.n})):0)+1,el:t,path:t?path(t):'',anchor:t?label(t):'[문서 전체]',quote:quote||null,text:ta.value.trim()});
    if(range){try{var m=document.createElement('mark');m.setAttribute('data-rv-mark','');range.surroundContents(m)}catch(err){}}
    if(t){t.setAttribute('data-rv-note','');pin(t)}closePop();finVis();st.textContent='댓글 '+notes.length+'개 (제출 전)'})}
var pins=new Map();   // 요소 → 마커
function pin(el){var p=pins.get(el);if(!p){p=document.createElement('span');p.className='__rv_pin';p.textContent=INITIAL;document.body.appendChild(p);pins.set(el,p);
    p.addEventListener('click',function(e){e.stopPropagation();openPop(el,'',null,e.pageX,e.pageY)})}
  var r=el.getBoundingClientRect(),n=notes.filter(function(x){return x.el===el}).length;
  p.style.left=(r.left+window.scrollX-36)+'px';p.style.top=(r.top+window.scrollY+r.height/2-15)+'px';
  if(n>1)p.setAttribute('data-n',n);else p.removeAttribute('data-n');p.title='댓글 '+n+'개 — 클릭하면 보기·추가·삭제'}
function refreshPins(){pins.forEach(function(p,el){if(!notes.some(function(x){return x.el===el})){p.remove();pins.delete(el);el.removeAttribute('data-rv-note');el.querySelectorAll('mark[data-rv-mark]').forEach(function(m){m.replaceWith(document.createTextNode(m.textContent))})}else pin(el)});
  finVis();st.textContent=notes.length?('댓글 '+notes.length+'개 (제출 전)'):''}
function closePop(){var d=document.getElementById('__rv_pop');if(d)d.remove();document.querySelectorAll('[data-rv-target]').forEach(function(x){x.removeAttribute('data-rv-target')});var s=window.getSelection();if(s)s.removeAllRanges()}
function brify(el){var w=document.createTreeWalker(el,NodeFilter.SHOW_TEXT),nodes=[];while(w.nextNode())if(w.currentNode.nodeValue.indexOf('\n')>=0)nodes.push(w.currentNode);
  nodes.forEach(function(n){var parts=n.nodeValue.split('\n'),f=document.createDocumentFragment();parts.forEach(function(p,i){if(i)f.appendChild(document.createElement('br'));if(p)f.appendChild(document.createTextNode(p))});n.parentNode.replaceChild(f,n)})}
function edits(){var out=[];orig.forEach(function(before,el){var after=el.innerText;if(before!==after)out.push({path:path(el),before:before.trim(),after:after.trim()})});return out}
function serialize(){orig.forEach(function(v,el){brify(el)});   // 편집한 요소의 줄바꿈을 <br> 로 (blur 를 놓친 경우 대비)
  var c=document.documentElement.cloneNode(true);
  c.querySelectorAll('#__rv_css,#__rv_bar,#__rv_js,#__rv_pop,#__rv_tip,.__rv_pin').forEach(function(x){x.remove()});   // 핀은 클래스라 id 목록에서 빠져 파일에 박히곤 했다 (댓글 원문이 title 로 남는다)
  Array.from(c.querySelector('body').children).forEach(function(x){if(!x.hasAttribute('data-rv-orig'))x.remove()});    // 확장·스크립트가 끼운 것. 속성을 지우기 전에 판정한다
  c.querySelectorAll('mark[data-rv-mark]').forEach(function(m){m.replaceWith(document.createTextNode(m.textContent))});
  c.querySelectorAll('[contenteditable]').forEach(function(x){x.removeAttribute('contenteditable')});
  c.querySelectorAll('*').forEach(function(x){Array.from(x.attributes).forEach(function(a){if(a.name.indexOf('data-rv-')===0){if(a.name==='data-rv-href')x.setAttribute('href',a.value);x.removeAttribute(a.name)}})});
  c.removeAttribute('data-theme');return '<!doctype html>'+c.outerHTML}
function post(url,body,type,extra){var h={'Content-Type':type};for(var k in (extra||{}))h[k]=extra[k];
  return fetch(url,{method:'POST',headers:h,body:body}).then(function(r){return r.text().then(function(t){if(!r.ok){var e=new Error(t||('HTTP '+r.status));e.code=r.status;throw e}return t})})}
function save(force,fromSubmit){if(document.activeElement&&document.activeElement.isContentEditable)document.activeElement.blur();
  st.textContent='저장 중…';
  return post('/save',serialize(),'text/html;charset=utf-8',force?{'X-Force':'1'}:{'X-Base-Mtime':MT})
   .then(function(t){dirty=false;STALE=false;fresh.hidden=true;btn.disabled=true;st.textContent=t;return fetch('/mtime').then(function(r){return r.text()}).then(function(m){MT=m;return t})})
   .catch(function(e){
     if(e.code===409&&!force){   // 그 사이 에이전트가 문서를 고쳤다 — 말없이 덮어쓰지 않는다
       if(fromSubmit)throw e;    // 제출 경로: 묻지 않는다. 파일 대신 수정 내역(before→after)만 넘겨 새 판 위에 얹게 한다
       if(confirm(AGENT+' 가 그 사이 문서를 새로 올렸습니다.\n지금 화면 내용으로 덮어쓰면 '+AGENT+' 가 새 판에서 한 작업이 사라집니다.\n\n덮어쓸까요?  [취소] 하고 [제출] 을 누르면 이 수정을 새 판 위에 얹어 달라고 보낼 수 있습니다.')) return save(true);
       st.textContent=AGENT+' 의 새 판이 있습니다 — 덮어쓰지 않았습니다. [제출] 하면 이 수정을 새 판 위에 얹어 달라고 보냅니다';fresh.hidden=false;STALE=true;throw e}
     st.textContent='저장 실패: '+e;throw e})}
btn.addEventListener('click',function(){save().catch(function(){})});
var fin=document.getElementById('__rv_fin'),OWNER_LABEL=__OWNER_LABEL__;
var SEL=null,LIST=[];   // 이 문서를 지켜보는 세션 목록. fork 로 갈라지면 둘 이상이 된다
function setListeners(rows){rows=rows||[];
  if(rows.length===LIST.length&&rows.every(function(r,i){return r.session===LIST[i].session&&r.label===LIST[i].label}))return;
  LIST=rows;var box=document.getElementById('__rv_to');
  if(rows.length<2){if(box)box.remove();SEL=null;return}   // 한 세션뿐이면 고를 것이 없다 — 지금까지와 똑같이 동작한다
  if(!box){box=document.createElement('select');box.id='__rv_to';box.title='제출을 받을 세션';ok.parentNode.insertBefore(box,ok)}
  var keep=SEL;box.innerHTML=rows.map(function(r){return '<option value="'+String(r.session).replace(/"/g,'&quot;')+'">'+String(r.label).replace(/</g,'&lt;')+'</option>'}).join('');
  box.value=(keep&&rows.some(function(r){return r.session===keep}))?keep:rows[0].session;SEL=box.value;
  box.onchange=function(){SEL=box.value}}
function submit(btnEl,final){if(btnEl.disabled)return;ok.disabled=fin.disabled=true;requestId=requestId||crypto.randomUUID();
  var ev={id:requestId,final:!!final,edits:edits(),comments:notes.map(function(x){return {n:x.n,path:x.path,anchor:x.anchor,quote:x.quote,text:x.text}})};ev.approved=!!final||(!ev.edits.length&&!ev.comments.length);   // 변경·댓글 없이 제출 = 이상 없음(승인) · 마무리 = 수정이 있어도 이걸로 끝
  if(SEL)ev.to=SEL;   // 이 문서를 지켜보는 세션이 둘 이상이면(fork 쌍둥이) 고른 쪽으로만 보낸다
  ((dirty&&!ISMD)?save(false,true).catch(function(e){if(e.code===409){ev.conflict=true;return}throw e}):Promise.resolve())   // 409 = 새 판 위에 얹어 달라는 제출
  .then(function(){return post('/confirm',JSON.stringify(ev),'application/json')})
  .then(function(t){if(!ev.conflict)return t;   // 옛 판 위에서 제출했다 — 지금 파일(새 판)을 기준으로 삼아, 에이전트가 이 수정을 얹은 다음 판이 나올 때 새로 고친다
    return fetch('/mtime').then(function(r){return r.text()}).then(function(m){MT=m;STALE=false;fresh.hidden=true;return t})})
  .then(function(t){lastEvent=JSON.parse(t);submitted=true;marks.hidden=true;setMarks(false);CH=[];PIN=false;showStatus(lastEvent);requestId=null;notes=[];document.querySelectorAll('[data-rv-note]').forEach(function(x){x.removeAttribute('data-rv-note')});
    document.querySelectorAll('mark[data-rv-mark]').forEach(function(m){m.replaceWith(document.createTextNode(m.textContent))});pins.forEach(function(p){p.remove()});pins.clear();orig.forEach(function(v,el){orig.set(el,el.innerText)});dirty=false;btn.disabled=true;finVis()}).catch(function(e){st.textContent='제출 확인 실패 · 입력 보존됨: '+e}).finally(function(){ok.disabled=fin.disabled=false})}
ok.addEventListener('click',function(){submit(ok,false)});
fin.addEventListener('click',function(){submit(fin,true)});
function finVis(){fin.hidden=notes.length>0}   // 댓글이 있으면 '마무리'가 아니다 — 제출만 남긴다
// 제출 버튼에 커서를 올리면 어느 세션으로 가는지 보인다
ok.addEventListener('mouseenter',function(){tipOff();TIP=document.createElement('div');TIP.id='__rv_tip';TIP.__for=ok;
  TIP.innerHTML='<b>제출 대상 세션</b>'+String(OWNER_LABEL).replace(/</g,'&lt;')+'<i>'+AGENT+' · 이 문서를 띄운 세션으로만 갑니다</i>';
  var r=ok.getBoundingClientRect();TIP.style.top=(r.bottom+window.scrollY+8)+'px';TIP.style.left=(r.left+window.scrollX)+'px';TIP.style.borderColor='#c96442';document.body.appendChild(TIP)});
ok.addEventListener('mouseleave',tipOff);
document.addEventListener('keydown',function(e){if((e.metaKey||e.ctrlKey)&&e.key==='s'){e.preventDefault();if(!ISMD)save().catch(function(){});else st.textContent='md 는 제출하면 에이전트가 원문에 반영합니다'}if(e.key==='Escape')closePop()});
window.addEventListener('resize',function(){pins.forEach(function(p,el){pin(el)})});
window.addEventListener('beforeunload',function(e){if(dirty||notes.length){e.preventDefault();e.returnValue=''}});
function showStatus(r){
  var copy=document.getElementById('__rv_copy'),AG='__AGENT__';
  if(STALE)return;   // 새 판 안내가 우선이다
  if(r.status==='done'){copy.hidden=true;fresh.hidden=true;if(!CH.length)showChanges();
    st.textContent=r.result||'반영 완료';st.title=st.textContent;return}
  if(r.pending_count>1){st.textContent='제출 '+r.pending_count+'건 대기 중 — '+AG+' 가 모아서 한 번에 반영합니다';copy.hidden=true;return}
  if(AG!=='Codex'&&(r.delivery==='manual'||!r.delivery)){   // Claude 등: 세션이 건 Monitor 가 이벤트 파일을 지켜본다 — heartbeat 로 확인한다
    if(r.conflict){st.textContent='제출되었습니다 — 화면은 옛 판이라 파일에 쓰지 않고, 이 수정을 '+AG+' 의 새 판 위에 얹어 달라고 보냈습니다. 반영되면 새 판을 불러옵니다';copy.hidden=r.watched!==false;return}
    if(r.watched===false){st.textContent='저장됨 — 지금 이 문서를 지켜보는 '+AG+' 세션이 없습니다. 대화창에 "제출 반영해줘" 라고 알려 주세요 (오른쪽 버튼으로 문구 복사)';copy.hidden=false;return}
    st.textContent=r.final?(r.watched===false?('마무리가 저장되었습니다 — 지켜보는 '+AG+' 세션이 없어 아직 전달되지 않았습니다. 대화창에 알려 주세요'):('마무리로 제출되었습니다 — '+AG+' 가 확인하면 이 편집기를 내립니다')):r.approved?('이상 없음으로 제출되었습니다 — '+AG+' 에게 승인이 전달됩니다'):('제출이 완료되었습니다 — '+AG+' 가 반영하면 화면이 자동으로 새로 고쳐집니다');copy.hidden=true;return}
  if(r.result){st.textContent=r.result;copy.hidden=false;return}
  var labels={queued:'저장됨 · Codex 큐 접수 · 반영 대기',pending:'저장됨 · 전달 확인 중',manual:'저장됨 · 자동 전달 미연결',failed:'저장됨 · 자동 전달 실패',unknown:'저장됨 · 전달 결과 미확인'};
  st.textContent=labels[r.delivery]||'저장됨 · 반영 대기';
  copy.hidden=r.delivery==='queued'||r.delivery==='pending';
}
document.getElementById('__rv_copy').addEventListener('click',function(){
  var message='review-ai-artifacts 제출 내용을 반영해줘. 문서: '+__DOC_JSON__+' / 제출 ID: '+((lastEvent||{}).id||'기존 미처리 제출');
  navigator.clipboard.writeText(message).then(function(){st.textContent='전달 요청 복사 완료 · 현재 대화에 붙여넣기'}).catch(function(){st.textContent=message});
});
var marks=document.getElementById('__rv_marks'),CH=[],WATCHED=null;
function setWatched(w){if(w===WATCHED)return;WATCHED=w;   // 누르기 전에 보이게 한다 — 눌러 보고 나서야 아는 것은 늦다
  var off=(w===false),tip=off?(AGENT+' 세션이 이 문서를 지켜보고 있지 않습니다. 지금 제출하면 파일에 저장만 되고, 대화창에 알려야 반영됩니다'):'';
  [ok,fin].forEach(function(b){b.classList.toggle('off',off);if(off)b.title=tip;else b.removeAttribute('title')});
  if(off&&!st.textContent)st.innerHTML='<span class="warn">'+AGENT+' 세션 미연결 — 제출은 저장되지만 알려야 반영됩니다</span>';
  if(!off&&st.textContent.indexOf('미연결')>=0)st.textContent=''}
var PIN=false;   // [변경사항 확인] 을 눌러 테두리를 고정했는가
function setMarks(on){CH.forEach(function(el){if(on)el.setAttribute('data-rv-changed','');else el.removeAttribute('data-rv-changed')});if(!on)tipOff()}
function showChanges(){fetch('/changes').then(function(r){return r.json()}).then(function(list){
  setMarks(false);CH=[];PIN=false;
  var miss=0;
  list.forEach(function(c){var el=null;try{el=c.path?document.querySelector(c.path):null}catch(e){}
    if(!el||ours(el)){miss++;return}
    el.__rvWhat=c;CH.push(el)});
  marks.hidden=!CH.length;marks.textContent='변경사항 확인 ('+CH.length+(miss?' · 못 찾음 '+miss:'')+')';marks.classList.remove('on')}).catch(function(){})}
marks.addEventListener('mouseenter',function(){setMarks(true)});
marks.addEventListener('mouseleave',function(){if(!PIN)setMarks(false)});
marks.addEventListener('click',function(){PIN=!PIN;setMarks(PIN);marks.classList.toggle('on',PIN)});
var TIP=null;
function tipOff(){if(TIP){TIP.remove();TIP=null}}
document.addEventListener('mouseover',function(e){
  var el=(e.target instanceof Element)?e.target.closest('[data-rv-changed]'):null;
  if(!el||!el.__rvWhat){if(TIP&&!(e.target instanceof Element&&e.target.closest('[data-rv-changed]')))tipOff();return}
  if(TIP&&TIP.__for===el)return;
  tipOff();var c=el.__rvWhat;TIP=document.createElement('div');TIP.id='__rv_tip';TIP.__for=el;
  TIP.innerHTML='<b>'+(c.n?'댓글 #'+c.n+' 반영':'반영')+'</b>'+String(c.what).replace(/</g,'&lt;')+(c.why?'<i>왜 — '+String(c.why).replace(/</g,'&lt;')+'</i>':'');
  var r=el.getBoundingClientRect();   // 붙이기 전에 잰다 — 붙인 뒤 재면 툴팁 자신의 자리가 섞인다
  TIP.style.top=(r.bottom+window.scrollY+8)+'px';TIP.style.left=Math.max(8,r.left+window.scrollX)+'px';
  document.body.appendChild(TIP);
  requestAnimationFrame(function(){if(!TIP)return;var t=TIP.getBoundingClientRect();
    if(t.right>window.innerWidth-8)TIP.style.left=Math.max(8,window.innerWidth-t.width-8+window.scrollX)+'px'})});
showChanges();
setInterval(function(){if(STALE||ok.disabled)return;fetch('/status').then(function(r){return r.json()}).then(function(r){setWatched(r.watched);setListeners(r.listeners);if(r.id||r.pending_count){lastEvent=r;showStatus(r)}}).catch(function(){})},2000);
var MT=__MTIME__;setInterval(function(){fetch('/mtime').then(function(r){return r.text()}).then(function(m){if(m===MT)return;
  if(dirty||notes.length||(document.activeElement&&document.activeElement.isContentEditable)){
    STALE=true;fresh.hidden=false;
    st.textContent='__AGENT__ 가 새 판을 올렸습니다 — 수정 중이라 불러오지 않았습니다. [제출] 하면 이 수정이 반영되고, [새 판 불러오기] 를 누르면 지금 수정은 사라집니다';return}
  location.reload()}).catch(function(){})},2000);
})();
</script>
"""

MD_CSS = """<style>:root{color-scheme:light dark}body{max-width:860px;margin:40px auto;padding:0 24px 80px;font:16px/1.75 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",Pretendard,"Segoe UI",sans-serif;color:#1c2431;background:#fff;word-break:keep-all}
@media(prefers-color-scheme:dark){body{color:#e6edf7;background:#141b26}a{color:#a9c5ff}code,pre{background:#233043}th{background:#233043}td,th{border-color:#38475c}blockquote{border-color:#38475c;color:#a8b8cb}}
h1{font-size:32px;line-height:1.3;margin:0 0 20px}h2{font-size:24px;margin:36px 0 12px}h3{font-size:18px;margin:26px 0 8px}p{margin:0 0 14px}ul,ol{padding-left:24px;margin:0 0 14px}li+li{margin-top:4px}
code{font:13.5px ui-monospace,Menlo,monospace;background:#eef2f7;padding:1px 5px;border-radius:4px}pre{background:#eef2f7;padding:14px 16px;border-radius:8px;overflow:auto}pre code{background:none;padding:0}
table{border-collapse:collapse;width:100%;margin:0 0 16px;font-size:14.5px}th,td{border:1px solid #dce3ed;padding:8px 12px;text-align:left;vertical-align:top}th{background:#eaf0f8}
blockquote{border-left:3px solid #dce3ed;margin:0 0 14px;padding:4px 16px;color:#57677c}hr{border:0;border-top:1px solid #dce3ed;margin:24px 0}img{max-width:100%}
.mdnote{font-size:12.5px;color:#8a97a8;border-top:1px solid #dce3ed;margin-top:40px;padding-top:12px}</style>"""

def md_to_html(md):
    """md → 보기용 HTML. 원문 복원용이 아니다 — 수정은 제출 이벤트(before/after)로 에이전트가 원문에 반영한다."""
    import html as H
    def inl(s):
        s = H.escape(s, quote=False)
        s = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img alt="\1" src="\2">', s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s); s = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*(?!\*)", r"<i>\1</i>", s)
        return s
    lines = md.splitlines()
    if sum(1 for l in lines if l.strip()) <= 3 and len(md) > 1500:   # 블록 구분 없이 한 줄로 쓰인 md — 표식 앞에서 나눈다
        md = re.sub(r"\s(?=#{1,6}\s)", "\n\n", md); md = re.sub(r"\s-\s(?=\S)", "\n- ", md); md = re.sub(r"\s(?=\|[^|]+\|)", "\n", md, count=1)
        lines = md.splitlines()
    out, i = [], 0
    while i < len(lines):
        l = lines[i]
        if l.startswith("```"):
            j = i + 1; buf = []
            while j < len(lines) and not lines[j].startswith("```"): buf.append(lines[j]); j += 1
            out.append("<pre><code>" + H.escape("\n".join(buf)) + "</code></pre>"); i = j + 1; continue
        m = re.match(r"^(#{1,6})\s+(.*)", l)
        if m: out.append(f"<h{len(m.group(1))}>{inl(m.group(2))}</h{len(m.group(1))}>"); i += 1; continue
        if re.match(r"^(-{3,}|\*{3,})\s*$", l): out.append("<hr>"); i += 1; continue
        if l.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.match(r"^\|[\s:|-]+\|\s*$", lines[i]): rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            if rows:
                th = "".join(f"<th>{inl(c)}</th>" for c in rows[0]); body = "".join("<tr>" + "".join(f"<td>{inl(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
                out.append(f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>")
            continue
        if re.match(r"^\s*([-*+]|\d+\.)\s+", l):
            ordered = bool(re.match(r"^\s*\d+\.", l)); items = []
            while i < len(lines) and re.match(r"^\s*([-*+]|\d+\.)\s+", lines[i]):
                items.append(re.sub(r"^\s*([-*+]|\d+\.)\s+", "", lines[i])); i += 1
                while i < len(lines) and lines[i].startswith("  ") and not re.match(r"^\s*([-*+]|\d+\.)\s+", lines[i]): items[-1] += " " + lines[i].strip(); i += 1
            tag = "ol" if ordered else "ul"; out.append(f"<{tag}>" + "".join(f"<li>{inl(x)}</li>" for x in items) + f"</{tag}>"); continue
        if l.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"): buf.append(lines[i].lstrip("> ").strip()); i += 1
            out.append("<blockquote>" + inl(" ".join(buf)) + "</blockquote>"); continue
        if not l.strip(): i += 1; continue
        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,6}\s|```|\||>|\s*([-*+]|\d+\.)\s|-{3,}\s*$)", lines[i]): buf.append(lines[i].strip()); i += 1
        out.append("<p>" + inl(" ".join(buf)) + "</p>")
    title = next((re.sub(r"^#\s+", "", x) for x in lines if x.startswith("# ")), DOC.name)
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{H.escape(title)}</title>{MD_CSS}</head>'
            f'<body>{"".join(out)}<p class="mdnote">원문 {H.escape(DOC.name)} · 마크다운을 보기용으로 렌더한 화면이다. 이중클릭 수정과 댓글은 제출 시 에이전트가 원문에 반영한다.</p></body></html>')

def bump_meta(html):
    """openub-report 문서면 수정일·이력 갱신. 라이브러리가 없으면 그대로 둔다."""
    lib_dir = os.environ.get("OPENUB_REPORT_LIB")
    if 'id="oub-meta"' not in html or not lib_dir: return html
    sys.path.insert(0, lib_dir); import lib
    meta = lib.meta_next(lib.meta_load(html), "편집기 저장", by="사용자")
    html = re.sub(r'<header class="topbar">.*?</header>', lambda m: lib.topbar(meta), html, count=1, flags=re.S)
    return re.sub(r'(<footer class="footer">Openub Artifacts · 작성 [^·]+ · 수정 )[^·<]+', lambda m: m.group(1) + meta["modified"], html, count=1)

def reply(h, code, text, ctype="text/plain;charset=utf-8"):
    data = text.encode(); h.send_response(code); h.send_header("Content-Type", ctype)
    h.send_header("Content-Length", str(len(data))); h.end_headers(); h.wfile.write(data)

LAST = [time.time()]   # 마지막 요청 시각. 브라우저 탭이 열려 있으면 2초마다 /mtime 이 들어온다
WATCH = [0.0]          # 이 문서를 지켜보는 세션(Monitor)의 마지막 heartbeat. 90초 안이면 "감시 연결"
LISTENERS = {}         # 세션ID -> {label, ts}. fork 로 갈라진 쌍둥이가 같은 문서를 함께 지켜볼 수 있다
def watched(): return CODEX is not None or time.time() - WATCH[0] < 90
def listeners():   # 최근 3분 안에 heartbeat 를 보낸 세션만 살아 있다고 본다. 죽은 세션은 폴링이 끊겨 저절로 빠진다
    now = time.time()
    rows = [{"session": s, "label": v["label"], "self": s == OWNER} for s, v in LISTENERS.items() if now - v["ts"] < 180]
    return sorted(rows, key=lambda r: (not r["self"], r["label"]))
def quit_server(why):
    threading.Thread(target=lambda: (time.sleep(.3), SRV.shutdown()), daemon=True).start()   # 먼저 예약한다 — 로그가 실패해도 종료는 취소되지 않는다
    try:   # 훅이 띄운 서버는 stdout 파이프가 닫혀 있어 print 에서 BrokenPipeError 가 난다 (그 탓에 종료가 통째로 취소되곤 했다)
        pending = [r["id"] for r in review_events.read(EVENTS) if nfc(r.get("doc", "")) == nfc(DOC) and r.get("status") == "new"]
        print(f"종료({why}): {DOC.name}" + (f" — 미처리 제출 {len(pending)}건 남음, 다음 세션이 {EVENTS.name} 의 status new 를 처리한다" if pending else ""), flush=True)
    except Exception: pass
def idle_watch():
    while True:
        time.sleep(60)
        if A.idle and time.time() - LAST[0] > A.idle * 60: return quit_server(f"{A.idle}분 유휴")
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def parse_request(self):
        ok = super().parse_request()
        if ok and not self.path.startswith("/watch"): LAST[0] = time.time()   # 감시 heartbeat 는 "사람이 보고 있다" 가 아니다 — 이걸 세면 유휴 자동 종료가 영원히 오지 않는다
        return ok
    def do_GET(self):
        if self.path == "/health": return reply(self, 200, json.dumps({"version":3,"doc":str(DOC),"owner":OWNER,"owner_label":OWNER_LABEL,"thread_id":THREAD,"automatic":bool(THREAD and CODEX)}), "application/json")
        if self.path == "/status":
            st_ = review_events.status(EVENTS, DOC, THREAD if CODEX else None, OWNER); st_["watched"] = watched(); st_["listeners"] = listeners()
            return reply(self, 200, json.dumps(st_, ensure_ascii=False), "application/json")
        if self.path.startswith("/mtime"): return reply(self, 200, str(DOC.stat().st_mtime_ns))
        if self.path == "/changes":   # 가장 최근 반영의 변경 표시
            rows = [r for r in review_events.read(EVENTS) if r.get("doc") == str(DOC) and r.get("changes")]
            return reply(self, 200, json.dumps(rows[-1]["changes"] if rows else [], ensure_ascii=False), "application/json")
        if self.path.startswith("/doc"): return reply(self, 200, nfc(DOC))
        body = md_to_html(DOC.read_text(encoding="utf-8")) if IS_MD else DOC.read_text(encoding="utf-8")
        ui = (UI.replace("__INITIAL__", json.dumps(INITIAL, ensure_ascii=False)).replace("__MTIME__", json.dumps(str(DOC.stat().st_mtime_ns)))
                .replace("__AGENT__", html_escape(AGENT)).replace("__OWNER_LABEL__", json.dumps(OWNER_LABEL, ensure_ascii=False).replace("<", "\\u003c")).replace("__DELIVERY_LABEL__", ("Codex 자동 전달 연결" if THREAD and CODEX else "자동 전달 미연결 · 제출 저장 후 대화에서 알림 필요") if AGENT.lower() == "codex" else "").replace("__DOC_JSON__", json.dumps(str(DOC), ensure_ascii=False).replace("<", "\\u003c")).replace("__ISMD__", "true" if IS_MD else "false"))
        body = body.replace("</body>", ui + "</body>", 1) if "</body>" in body else body + ui
        reply(self, 200, body, "text/html;charset=utf-8")
    def do_POST(self):
        allowed = {f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}
        if self.headers.get("Host") not in {f"localhost:{PORT}", f"127.0.0.1:{PORT}"} or self.headers.get("Origin") not in allowed | {None}:
            return reply(self, 403, "다른 사이트에서 제출할 수 없습니다")
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
        if self.path.startswith("/save"):
            if IS_MD: return reply(self, 200, "md 는 화면에서 바로 저장하지 않습니다 — 제출하면 에이전트가 원문에 반영합니다")
            base = self.headers.get("X-Base-Mtime")
            if base and not self.headers.get("X-Force") and base != str(DOC.stat().st_mtime_ns):   # 에이전트가 그 사이 고쳤다
                return reply(self, 409, "그 사이 문서가 바뀌었습니다")
            leak = next((m for m in ("__rv_bar", "__rv_pop", "__rv_pin", "__rv_tip", "__rv_js", "data-rv-note", "data-rv-changed") if m in raw), None)
            if leak: return reply(self, 400, f"편집기 흔적({leak})이 섞여 들어와 저장하지 않았습니다 — 화면을 새로 고친 뒤 다시 시도하세요")
            bak = DOC.with_suffix(".html.bak")
            if not bak.exists(): bak.write_bytes(DOC.read_bytes())
            raw = bump_meta(raw); DOC.write_text(raw, encoding="utf-8")
            return reply(self, 200, f"저장됨 {len(raw.encode()):,}B")
        if self.path.startswith("/watch"):   # 감시 세션의 heartbeat. ?session=&label= 를 붙이면 명단에 오른다 (fork 쌍둥이 구분용)
            WATCH[0] = time.time()
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            s = (q.get("session") or [""])[0]
            if s: LISTENERS[s] = {"label": ((q.get("label") or [""])[0] or s)[:80], "ts": time.time()}   # 신분 없는 구형 heartbeat 도 그대로 받는다
            return reply(self, 200, json.dumps({"listeners": listeners()}, ensure_ascii=False), "application/json")
        if self.path.startswith("/quit"):
            reply(self, 200, f"편집기 종료: {DOC.name} (포트 {PORT})"); return quit_server("--close")
        if self.path.startswith("/confirm"):
            try:
                payload = json.loads(raw); to = str(payload.pop("to", "") or "") or OWNER   # 지켜보는 세션이 여럿이면 화면에서 고른 쪽으로 보낸다
                ev = review_events.submit(EVENTS, DOC, AGENT, "md" if IS_MD else "html", payload, THREAD, CODEX, to)
                ev = dict(ev, watched=watched())   # 제출 직후 화면이 "깨어날 세션이 있는지" 를 바로 알아야 한다 (/status 만으로는 한 박자 늦다)
                return reply(self, 200, json.dumps(ev, ensure_ascii=False), "application/json")
            except (ValueError, TypeError, TimeoutError) as error:
                return reply(self, 400, str(error))
        reply(self, 404, "?")

if __name__ == "__main__":
    print(f"문서: {DOC}\n이벤트: {EVENTS}\nhttp://localhost:{PORT}/   (--close 로 종료" + (f" · 탭 닫힘 뒤 {A.idle}분 유휴면 자동 종료" if A.idle else "") + ")", flush=True)
    if not A.no_open: webbrowser.open(f"http://localhost:{PORT}/")
    SRV = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    SRV.daemon_threads = True          # 남은 요청 스레드가 프로세스 종료를 붙잡지 못하게 한다
    threading.Thread(target=idle_watch, daemon=True).start()
    SRV.serve_forever(); SRV.server_close()
