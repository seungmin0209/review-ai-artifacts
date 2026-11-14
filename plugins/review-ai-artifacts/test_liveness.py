"""감시 신호 점검 — 화면이 말하는 상태와 실제가 어긋나지 않는지 본다.

고치는 동안 heartbeat 가 멎는 구간, 주인이 끊긴 서버, 이어받은 세션으로의 전달,
그리고 --doctor 가 묻힌 제출을 집어내는지까지 확인한다.
감시 창은 환경변수로 줄여서 돌리므로 20초 안에 끝난다.

    python3 test_liveness.py
"""
import json, os, pathlib, subprocess, sys, tempfile, time, urllib.request, uuid

SKILL = pathlib.Path(__file__).resolve().parent
WINDOW = 3            # 이 검사에서 쓸 heartbeat 창(초)
ENV = dict(os.environ, REVIEW_WATCH_WINDOW=str(WINDOW), REVIEW_WORKING_WINDOW="60")


def call(port, path, body=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method="POST" if body is not None else "GET",
        headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"} if body is not None else {})
    with urllib.request.urlopen(req, timeout=5) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw.startswith(("{", "[")) else raw


def boot(folder, name, port, session):
    doc = folder / name
    doc.write_text("<html><body><p id=a>원문</p></body></html>", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(SKILL / "review.py"), str(doc), "--no-open",
                             "--port", str(port), "--agent", "Claude", "--session", session],
                            env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            call(port, "/health"); return doc, proc
        except Exception:
            time.sleep(.1)
    raise SystemExit(f"서버가 뜨지 않았습니다 (포트 {port})")


def comment(n=1):
    return {"id": str(uuid.uuid4()), "edits": [],
            "comments": [{"n": n, "path": "#a", "anchor": "", "quote": "", "text": "봐 주세요"}], "final": False}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        folder = pathlib.Path(tmp)
        woken_doc, woken = boot(folder, "woken.html", 8988, "sess-woken")      # 감시 세션이 있었던 문서
        orphan_doc, orphan = boot(folder, "orphan.html", 8989, "sess-orphan")  # 아무도 지켜본 적 없는 문서
        procs = [woken, orphan]
        try:
            assert call(8988, "/status")["watched"] is False, "heartbeat 전에는 연결로 보이면 안 된다"

            call(8988, "/watch?session=sess-woken&label=L1", {})
            st = call(8988, "/status")
            assert st["watched"] is True and st["working"] is False, st

            eid = str(uuid.uuid4())
            ev = call(8988, "/confirm", {"id": eid, "edits": [{"path": "#a", "before": "원문", "after": "고친 글"}],
                                         "comments": [], "final": False})
            assert ev["watched"] is True, ev
            st = call(8988, "/status")
            assert st["pending_count"] == 1 and st["working"] is False, st   # 아직 heartbeat 가 살아 있다

            call(8989, "/confirm", comment())

            time.sleep(WINDOW + 2)   # heartbeat 가 끊기기를 기다린다

            st = call(8988, "/status")
            assert st["watched"] is False, st
            assert st["working"] is True, f"깨워 둔 세션이 반영 중인데 끊김으로 봤다: {st}"

            st = call(8989, "/status")
            assert st["watched"] is False and st["working"] is False, f"지켜본 적 없는 문서를 반영 중으로 봤다: {st}"

            # --doctor 는 묻힌 제출을 집어내야 한다. 8989 는 주인이 끊겼고 미처리가 남아 있다.
            out = subprocess.run([sys.executable, str(SKILL / "review.py"), "--doctor"],
                                 env=ENV, capture_output=True, text=True).stdout
            assert "orphan.html" in out and "아무에게도 가지 않았다" in out, f"--doctor 가 묻힌 제출을 놓쳤다:\n{out}"

            # 주인이 끊긴 서버에 다른 세션이 이어받아 듣고 있으면, 제출은 그 세션 앞으로 가야 한다.
            # 예전에는 서버 기동 때 고정된 주인 앞으로만 기록돼, 아무 Monitor 도 집지 않고 묻혔다.
            call(8989, "/watch?session=taker&label=taker", {})
            handover = comment(2); call(8989, "/confirm", handover)
            rows = [json.loads(l) for l in (folder / "_review_events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            row = next(r for r in rows if r["id"] == handover["id"])
            assert row["owner"] == "taker", f"제출이 끊긴 주인 앞으로 갔다: {row['owner']}"
            assert call(8989, "/status")["pending_count"] == 2, "이어받은 세션 앞으로 간 제출이 대기 건수에서 빠졌다"

            # 사용자가 "이어받아" 라고 하면 --takeover: 서버를 내 세션으로 다시 띄우고, 묻힌 제출을 내 앞으로 돌리고,
            # 같은 문서의 다른 판(이름 줄기가 같은 파일)이 떠 있으면 알린다. 2026-11-14 md 만 이어받고 html 쪽 제출을 놓쳤다.
            sib_doc, sib = boot(folder, "or_phan.md", 8987, "sess-orphan"); procs.append(sib)
            log = folder / "takeover.log"
            taker = subprocess.Popen([sys.executable, str(SKILL / "review.py"), str(orphan_doc), "--no-open", "--port", "8989",
                                      "--agent", "Claude", "--session", "boss", "--takeover"],
                                     env=ENV, stdout=log.open("w"), stderr=subprocess.STDOUT); procs.append(taker)
            for _ in range(50):
                try:
                    if call(8989, "/health")["owner"] == "boss": break
                except Exception: pass
                time.sleep(.1)
            assert call(8989, "/health")["owner"] == "boss", "이어받기 뒤에도 옛 주인이 서버를 쥐고 있다"
            rows = [json.loads(l) for l in (folder / "_review_events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            left = [r["owner"] for r in rows if r["doc"] == str(orphan_doc.resolve()) and r["status"] == "new"]
            assert left and set(left) == {"boss"}, f"묻힌 제출이 이어받은 세션 앞으로 오지 않았다: {left}"
            assert "8987" in log.read_text(encoding="utf-8"), f"같은 문서의 다른 판을 알리지 않았다:\n{log.read_text(encoding='utf-8')}"

            subprocess.run([sys.executable, str(SKILL / "review.py"), str(woken_doc), "--ack", eid,
                            "--result", "반영함"], env=ENV, check=True, stdout=subprocess.DEVNULL)
            st = call(8988, "/status")
            assert st["pending_count"] == 0 and st["working"] is False, f"ack 뒤에도 반영 중으로 남았다: {st}"
            assert st["status"] == "done", st

            print("통과 — 반영 중 공백 유지 · 주인 없는 문서는 끊김 · 이어받은 세션 전달 · --doctor 가 묻힌 제출 포착 · --takeover")
        finally:
            for p in procs:
                p.terminate(); p.wait(timeout=5)


if __name__ == "__main__":
    main()
