"""문서가 키·클릭을 가로채는 화면(발표 장표 등)에서 편집기가 제대로 도는지 본다 — 2026-10-15 승민 실측 회귀.

댓글을 적는 중 ←→·Space·Backspace·글자 키가 장 넘김·문서 단축키로 새지 않는지, 글자 수정 중에도 같은지,
팝업 안 클릭이 문서의 클릭 넘김으로 새지 않는지, 문서 CSS 의 [data-a] 가 보내기 버튼을 가리지 않는지,
장을 넘기면 마커가 숨는지 확인한다. Playwright 가 없으면 건너뛴다.

    python3 test_keys.py
"""
import pathlib, re, subprocess, sys, tempfile, time

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("건너뜀 — playwright 가 없다"); sys.exit(0)

SKILL = pathlib.Path(__file__).resolve().parent
DECK = """<!doctype html><html><head><meta charset="utf-8"><style>
.s{display:none;font:40px sans-serif;padding:80px}.s.on{display:block}[data-a]{opacity:0}</style></head><body>
<section class="s on"><h2>첫 장 제목</h2><p>본문 하나</p></section><section class="s"><h2>둘째 장 제목</h2></section>
<script>let i=0,S=[...document.querySelectorAll('.s')];function go(n){i=Math.max(0,Math.min(S.length-1,n));S.forEach((s,j)=>s.classList.toggle('on',j===i))}
addEventListener('keydown',e=>{if(['ArrowRight',' ','Enter'].includes(e.key)){go(i+1);e.preventDefault()}
 else if(['ArrowLeft','Backspace'].includes(e.key)){go(i-1);e.preventDefault()}else if(e.key==='f')document.title='FULL'});
let clicks=0;addEventListener('click',e=>{clicks++;if(e.target.tagName==='SECTION')go(i+1)})</script></body></html>"""

d = pathlib.Path(tempfile.mkdtemp()); doc = d / "deck.html"; doc.write_text(DECK, encoding="utf-8")
log = d / "log"
srv = subprocess.Popen([sys.executable, str(SKILL / "review.py"), str(doc), "--agent", "Claude", "--no-open", "--session", "test-keys"],
                       stdout=open(log, "w"), stderr=subprocess.STDOUT)
try:
    m = None
    for _ in range(50):
        m = re.search(r"localhost:(\d+)", log.read_text()) if log.exists() else None
        if m: break
        time.sleep(.1)
    url = f"http://localhost:{m.group(1)}/"
    with sync_playwright() as pw:
        b = pw.chromium.launch(); pg = b.new_page(); pg.goto(url); pg.wait_for_timeout(500)
        cur = lambda: pg.evaluate("i")
        pg.locator(".s.on h2").click(button="right"); pg.wait_for_timeout(200)
        ta = pg.locator("#__rv_pop textarea")
        ta.type("ab"); pg.keyboard.press("ArrowLeft"); ta.type("X"); pg.keyboard.press("Space"); pg.keyboard.type("f"); pg.keyboard.press("Backspace")
        assert ta.input_value() == "aX b", ta.input_value()                      # ← 로 커서가 움직이고 Space·Backspace 가 글자에 먹는다
        assert cur() == 0 and pg.title() != "FULL", (cur(), pg.title())         # 장이 넘어가거나 문서 단축키가 돌지 않는다
        assert pg.evaluate("getComputedStyle(document.querySelector('#__rv_pop .go')).opacity") == "1"   # 문서 CSS [data-a] 에 가리지 않는다
        n = pg.evaluate("clicks"); ta.click(); assert pg.evaluate("clicks") == n, "팝업 안 클릭이 문서의 클릭 처리로 샜다"
        pg.keyboard.press("Enter"); pg.wait_for_timeout(300)
        assert pg.locator(".__rv_pin").count() == 1 and cur() == 0
        pg.locator(".s.on p").dblclick(); pg.wait_for_timeout(100)
        pg.keyboard.press("End"); pg.keyboard.press("ArrowLeft"); pg.keyboard.type(" Z")
        assert pg.locator(".s.on p").inner_text() == "본문 하 Z나" and cur() == 0, pg.locator(".s.on p").inner_text()
        pg.evaluate("document.activeElement.blur()"); pg.evaluate("go(1)"); pg.wait_for_timeout(600)
        assert pg.evaluate("getComputedStyle(document.querySelector('.__rv_pin')).display") == "none"   # 넘긴 장의 마커는 숨는다
        pg.evaluate("go(0)"); pg.wait_for_timeout(600)
        assert pg.evaluate("getComputedStyle(document.querySelector('.__rv_pin')).display") != "none"
        b.close()
    print("통과 — 입력 중 키·클릭이 문서로 새지 않음 · 문서 CSS 와 속성 충돌 없음 · 숨은 요소의 마커 숨김")
finally:
    subprocess.run([sys.executable, str(SKILL / "review.py"), str(doc), "--close"], capture_output=True); srv.terminate()
