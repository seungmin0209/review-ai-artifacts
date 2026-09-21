#!/usr/bin/env python3
"""review-ai-artifacts 훅 — 에이전트가 HTML·md 산출물을 만들면 어떤 도구로 만들었든 편집 화면이 뜨게 한다.

PostToolUse (Write|Edit|MultiEdit|NotebookEdit|Bash)
  - Write/Edit: tool_input.file_path 가 .html 이면 대상.
  - Bash: tool_input.command 에서 .html/.htm 경로를 뽑아, 실제로 존재하고 최근 60초 안에 바뀐 것만 대상(가장 최근 1개).
    cat > x.html <<EOF, tee, sed -i, cp, python 스크립트 등 어떤 경로든 잡힌다.
Stop (턴 종료)
  - 훅이 놓친 경우의 안전망. cwd 아래에서 이 세션 시작 이후 바뀐 .html 중 아직 처리하지 않은 것이 있으면 그때 발동한다.
    stop_hook_active 면 재발동하지 않는다(무한 루프 방지).

설정(mode)에 따라: always → review.py 를 직접 띄우고 알린다 · ask → "띄울까요?" 물어라 · cases → 해당하면 띄워라 · off → 침묵.
설정 파일이 없으면 mode=ask 로 만들고 first_run 을 표시해 "발동 방식을 먼저 물어라" 를 한 번 넣는다.
처리한 문서는 ~/.config/review-ai-artifacts/state.json 에 세션별로 기록해 같은 문서를 두 번 띄우지 않는다.
"""
import sys, os, re, json, pathlib, subprocess, socket, time, urllib.request, urllib.parse, unicodedata
def nfc(s): return unicodedata.normalize("NFC", str(s))   # macOS 는 한글 파일명을 NFD(자모 분해)로 돌려준다 — 경로 비교는 전부 NFC 로
HERE = pathlib.Path(__file__).resolve().parent
CFG_DIR = pathlib.Path.home() / ".config" / "review-ai-artifacts"
CONFIG, STATE = CFG_DIR / "config.json", CFG_DIR / "state.json"
PY = sys.executable or "python3"
RECENT = 60          # Bash 경로 후보의 mtime 허용(초)
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".cache", ".agents", ".claude", ".codex", "memory", "handoffs"}
SKIP_MD = {"claude.md", "agents.md", "gemini.md", "readme.md", "skill.md", "changelog.md", "license.md", "contributing.md", "memory.md", "todo.md"}   # 규약·설정 성격의 md 는 산출물이 아니다
ART_EXT = (".html", ".htm", ".md", ".markdown")
def is_artifact(p):
    n = p.name.lower()
    if not n.endswith(ART_EXT) or n.endswith(".bak") or "_review_" in n: return False
    if n.endswith((".md", ".markdown")) and (n in SKIP_MD or n.startswith(("status", "handoff", "_"))): return False
    return not any(part in SKIP_DIRS for part in p.parts)

def emit(event, ctx):
    if event == "Stop":
        print(json.dumps({"decision": "block", "reason": ctx}))
    else:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}}))
    sys.exit(0)

def load_json(p, default):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return default

def config():
    cfg = load_json(CONFIG, None)
    if cfg is None:                                   # [4] 기본 설정을 만들어 두고 첫 사용을 표시
        cfg = {"mode": "ask", "cases": [], "first_run": True, "created": time.strftime("%Y-%m-%d")}
        CFG_DIR.mkdir(parents=True, exist_ok=True); CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return cfg

def state(): return load_json(STATE, {})
def mark(sid, doc):
    st = state(); s = st.setdefault(sid, {"started": time.time(), "handled": [], "dirs": []})
    if nfc(doc) not in s["handled"]: s["handled"].append(nfc(doc))
    CFG_DIR.mkdir(parents=True, exist_ok=True); STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
def session_start(sid):
    st = state(); s = st.setdefault(sid, {"started": time.time(), "handled": [], "dirs": []})
    s.setdefault("dirs", [])   # 예전 형식의 기록
    if len(st) > 50:                                  # 오래된 세션 정리
        for k in sorted(st, key=lambda k: st[k]["started"])[:-30]: st.pop(k, None)
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8"); return s
def note_dirs(sid, ds):
    st = state(); s = st.setdefault(sid, {"started": time.time(), "handled": [], "dirs": []})
    s["dirs"] = sorted(set(s.get("dirs", [])) | set(ds)); s["last_tool"] = time.time()
    CFG_DIR.mkdir(parents=True, exist_ok=True); STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8"); return s

def launch(doc, agent, sid, cwd=None):
    """review.py 가 문서별 고정 포트를 고른다. 이미 떠 있으면 그 주소를 돌려준다."""
    CFG_DIR.mkdir(parents=True, exist_ok=True); log = open(CFG_DIR / "server.log", "a", encoding="utf-8")
    kw = {"creationflags": 0x00000008} if os.name == "nt" else {"start_new_session": True}
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")   # Windows 기본 cp949 파이프에서 첫 줄을 읽다 죽는다 (실측)
    p = subprocess.Popen([PY, str(HERE / "review.py"), str(doc), "--agent", agent, "--session", sid, "--session-label", f"{pathlib.Path(cwd or os.getcwd()).name} · {sid[:8]}", "--no-open"], stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8", errors="replace", env=env, **kw)
    url = None
    for _ in range(40):                      # 첫 줄(들)에서 URL 을 읽는다 — 최대 2초
        line = p.stdout.readline()
        if not line: break
        m = re.search(r"http://localhost:(\d+)/", line)
        if m: url = int(m.group(1)); break
    return url or 8901
def serving(doc):
    """이 문서를 이미 서비스 중인 서버의 (포트, 소유 세션). 없으면 (None, None). 구형 서버는 소유가 없어 None 이다."""
    for p in range(8901, 8991):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{p}/doc", timeout=0.2) as r:
                if nfc(r.read().decode("utf-8","replace")) != nfc(doc): continue
        except Exception: continue
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{p}/health", timeout=0.3) as r:
                return p, json.load(r).get("owner")
        except Exception: return p, None
    return None, None

HTML_RE = re.compile(r"""(?<![\w./-])((?:~|\.{1,2})?/?[^\s'"`;|&<>()]*?\.(?:html?|md|markdown))(?=$|[\s'"`;|&<>)])""", re.I)
def candidates_from_command(cmd, cwd):
    out = []
    for m in HTML_RE.findall(cmd or ""):
        p = pathlib.Path(os.path.expanduser(m)); p = p if p.is_absolute() else pathlib.Path(cwd or ".") / p
        try:
            if p.is_file() and time.time() - p.stat().st_mtime <= RECENT: out.append(p.resolve())
        except OSError: pass
    return sorted(set(out), key=lambda p: p.stat().st_mtime, reverse=True)

def dirs_from_tool(tool, ti, cwd):
    """이 세션이 실제로 건드린 디렉터리. 안전망은 워크스페이스 전체가 아니라 여기만 본다."""
    out = set()
    if tool == "Bash":
        for m in re.findall(r"""[^\s'"`;|&<>()]+""", ti.get("command", "") or ""):
            q = pathlib.Path(os.path.expanduser(m))
            q = q if q.is_absolute() else pathlib.Path(cwd or ".") / q
            try:
                if q.is_file(): out.add(str(q.parent.resolve()))
            except OSError: pass
    else:
        fp = ti.get("file_path") or ti.get("notebook_path") or ""
        if fp:
            try: out.add(str(pathlib.Path(fp).resolve().parent))
            except OSError: pass
    return out

def recent_htmls(roots, since, handled, transcript=None, others=()):
    """턴 종료 안전망 후보. 재귀하지 않는다 — 루트 폴더가 dirs 에 들어오면 워크스페이스 전체를 훑어 남의 산출물을 집는다(2026-09-17 실제 사례)."""
    found = []
    for base in roots:
        try: entries = list(os.scandir(base))
        except OSError: continue
        for e in entries:
            if not e.is_file(): continue
            q = pathlib.Path(e.path).resolve()
            if not is_artifact(q): continue
            try:
                if q.stat().st_mtime >= since and nfc(q) not in handled: found.append(q)
            except OSError: pass
    found = [p for p in dict.fromkeys(found) if nfc(p) not in others]          # 다른 세션이 이미 본(만든) 파일은 그 세션 것이다
    if transcript:                                                            # 이 세션 대화에 파일명이 한 번도 안 나왔으면 내 산출물이 아니다
        try:
            txt = pathlib.Path(transcript).read_text(encoding="utf-8", errors="replace")
            found = [p for p in found if nfc(p.name) in nfc(txt)]
        except OSError: pass
    served = set()                                                            # 이미 누가 띄워 둔 문서는 그 세션 것이다 (포트 순회는 한 번만)
    for port in range(8901, 8991):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/doc", timeout=0.2) as r: served.add(nfc(r.read().decode("utf-8", "replace")))
        except Exception: pass
    found = [p for p in found if nfc(p) not in served]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)

def monitor_cmd(doc, sid, port, label=""):
    """Claude 세션이 그대로 붙여 쓰는 감시 명령. owner 가 이 세션인 새 제출만 알리고, 60초마다 /watch heartbeat 를 찍어 화면이 '감시 연결' 을 알게 한다.
    heartbeat 에 세션 신분을 실어 보내므로, fork 로 갈라진 세션이 둘 다 지켜보면 화면이 제출 대상을 고르는 선택칸을 띄운다.
    Monitor 도구는 최대 30분(도구 상한)이라 만료 알림마다 같은 명령으로 다시 건다. 시작 시 처리 안 된 제출을 먼저 훑으므로 재무장 사이의 공백에 들어온 제출도 놓치지 않는다."""
    ev = str(doc.parent / "_review_events.jsonl").replace('"', '\\"')
    who = f"session={urllib.parse.quote(sid)}&label={urllib.parse.quote(label or sid[:8])}"
    return (f"( while true; do curl -s -m 2 -X POST 'http://127.0.0.1:{port}/watch?{who}' >/dev/null 2>&1; sleep 60; done ) & "
            # 시작할 때 아직 처리 안 된(new) 내 제출을 먼저 훑는다 — Monitor 는 30분마다 만료돼 다시 걸어야 하는데, 그 사이 들어온 제출을 tail -n 0 이 건너뛴다
            f"( [ -f \"{ev}\" ] && cat \"{ev}\"; tail -n 0 -F \"{ev}\" 2>/dev/null ) | grep --line-buffered \"\\\"status\\\": \\\"new\\\"\" | grep --line-buffered \"\\\"owner\\\": \\\"{sid}\\\"\" "
            f"| while IFS= read -r l; do printf '%s' \"$l\" | python3 -c 'import sys,json; e=json.load(sys.stdin); print(\"[review-ai-artifacts] 새 제출\", e[\"id\"], \"final\" if e.get(\"final\") else (\"approved\" if e.get(\"approved\") else \"\"), \"edits\", len(e.get(\"edits\",[])), \"comments\", len(e.get(\"comments\",[])))'; done")
def instruct(event, doc, cfg, agent, sid):
    skill = HERE / "SKILL.md"; rv = HERE / "review.py"
    lead = "[review-ai-artifacts]" + (" (턴 종료 안전망 — 저장 훅이 놓친 HTML)" if event == "Stop" else "")
    if cfg.get("first_run"):
        cfg["first_run"] = False; CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8"); mark(sid, doc)
        emit(event, f"{lead} 이 스킬을 처음 쓴다. 산출물 '{doc.name}' 을 편집 화면으로 띄우기 전에, 사용자에게 채팅으로 네 가지를 한 문장씩 설명하고 하나를 고르게 하라: "
             "always(HTML 만들 때마다 자동) · ask(매번 물어보기) · cases(아티팩트·보고서 등 특정 경우만) · off(명시 요청에만). 기본은 ask 로 저장돼 있다. "
             f"고르면 `{PY} \"{rv}\" --set-mode <mode> [--cases a,b]` 로 저장하고, \"언제든 '리뷰 모드 항상/물어봐/특정 경우만/끄기' 라고 말하면 바꿀 수 있다\" 고 덧붙여라. "
             f"always/ask(예)/cases(해당) 이면 이어서 `{PY} \"{rv}\" \"{doc}\" --agent {agent}` 를 백그라운드로 띄우고 이벤트 파일 `{doc.parent/'_review_events.jsonl'}` 을 지켜본다. 규약: {skill}")
    mode = cfg.get("mode", "ask")
    if mode == "off": sys.exit(0)
    mark(sid, doc)
    if mode == "ask":
        emit(event, f"{lead} 발동 방식이 ask 다. 사용자에게 \"'{doc.name}' 을 편집·댓글 화면으로 띄울까요?\" 한 줄만 물어라. 예라고 하면 `{PY} \"{rv}\" \"{doc}\" --agent {agent}` 를 백그라운드로 띄우고 이벤트 파일을 지켜본다. 규약: {skill}")
    if mode == "cases":
        emit(event, f"{lead} 발동 방식이 cases={cfg.get('cases')} 다. '{doc.name}' 이 그 경우에 해당하면 `{PY} \"{rv}\" \"{doc}\" --agent {agent}` 를 백그라운드로 띄우고 이벤트 파일을 지켜본다. 아니면 띄우지 않는다. 규약: {skill}")
    port, owner = serving(doc)
    if port and owner and owner != sid:   # 다른 세션이 맡은 문서 — 서버도 제출 신호도 건드리지 않는다
        emit(event, f"{lead} '{doc.name}' 은 이미 **다른 세션**({owner})이 http://localhost:{port}/ 에서 검토 중이다. "
             f"그 서버를 재시작하거나 `--close` 하지 말고, 그 문서의 제출 이벤트도 처리하지 마라 — 제출은 그 세션으로 간다. "
             f"사용자가 이 세션에서 이어받기를 원하면 먼저 확인을 받아라. 규약: {skill}")
    port = port or launch(doc, agent, sid, os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    emit(event, f"{lead} '{doc.name}' 을 편집·댓글 화면으로 띄웠다: http://localhost:{port}/ . 사용자에게 이 주소와 \"이중클릭으로 고치고 우클릭으로 댓글, 끝나면 [검토 제출]\" 을 한 줄로 알려라. "
         f"**지금 바로 Monitor 를 걸어라(Claude Code)** — 걸지 않으면 사용자가 제출해도 이 세션은 깨어나지 않는다. 다른 세션의 제출은 owner 필터로 걸러진다. label 은 이 세션을 알아볼 이름으로 바꿔도 된다 — fork 로 갈라져 둘이 함께 지켜보면 화면에 이 이름이 제출 대상 선택칸으로 뜬다. timeout_ms 는 도구 상한인 1800000(30분) — **만료 알림이 오면 다른 일보다 먼저 같은 명령으로 다시 건다.** 시작할 때 밀린 제출을 먼저 알리므로 공백에 들어온 것도 잡힌다:\n"
         f"  Monitor(description=\"{doc.name} 제출 감시\", timeout_ms=1800000, command=\"{monitor_cmd(doc, sid, port, f"{pathlib.Path(os.getcwd()).name} · {sid[:8]}")}\")\n"
         f"Codex는 CODEX_THREAD_ID와 codex queue 연결을 /health에서 확인한다(서버가 직접 깨운다). 제출 이벤트 파일: {doc.parent/'_review_events.jsonl'} — status \"new\" 줄이 오면 edits 는 반영 확인, comments 는 파일을 고쳐 저장하고 --ack. 규약: {skill}")

def main():
    try: ev = json.load(sys.stdin)
    except Exception: sys.exit(0)
    event = ev.get("hook_event_name") or ("Stop" if "stop_hook_active" in ev else "PostToolUse")
    sid = ev.get("session_id") or "nosession"; cwd = ev.get("cwd") or os.getcwd()
    cfg = config(); agent = os.environ.get("HTML_WITH_AI_AGENT") or ("Codex" if os.environ.get("CODEX_THREAD_ID") else None) or cfg.get("agent") or "Claude"
    sess = session_start(sid)
    if event == "Stop":
        if ev.get("stop_hook_active"): sys.exit(0)
        roots = sess.get("dirs") or []          # 이 세션이 건드린 적 없는 폴더는 보지 않는다 — 다른 세션 산출물 침범 방지
        if not roots: sys.exit(0)
        since = (sess.get("last_tool") or sess["started"]) - 180   # 세션 시작이 아니라 마지막 도구 호출 기준 — 세션이 며칠 이어져도 옛 파일을 집지 않는다
        others = {nfc(d) for k, v in state().items() if k != sid for d in v.get("handled", [])}
        docs = recent_htmls(roots, since, {nfc(d) for d in sess["handled"]}, ev.get("transcript_path"), others)
        if not docs: sys.exit(0)
        instruct("Stop", docs[0], cfg, agent, sid)
    tool = ev.get("tool_name") or ""; ti = ev.get("tool_input") or {}
    sess = note_dirs(sid, dirs_from_tool(tool, ti, cwd))
    if tool == "Bash":
        docs = candidates_from_command(ti.get("command", ""), cwd)
        if not docs: sys.exit(0)
        doc = docs[0]
    else:
        fp = ti.get("file_path") or ti.get("notebook_path") or ""
        if not fp.lower().endswith(ART_EXT): sys.exit(0)
        doc = pathlib.Path(fp).resolve()
    if not doc.exists() or not is_artifact(doc): sys.exit(0)
    if nfc(doc) in sess["handled"] and serving(doc)[0]: sys.exit(0)   # 이미 띄운 문서를 다시 고친 것 — 화면이 자동 새로고침한다
    instruct("PostToolUse", doc, cfg, agent, sid)

if __name__ == "__main__": main()
