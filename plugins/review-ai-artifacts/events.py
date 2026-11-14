"""Durable review submission and Codex queue delivery (stdlib only)."""
import contextlib
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

@contextlib.contextmanager
def locked(events):
    # A directory lock also works on Windows and across server/ack processes.
    lock = events.with_name(events.name + '.lock')
    deadline = time.monotonic() + 10
    while True:
        try:
            lock.mkdir(); break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError('제출 기록이 사용 중입니다. 잠시 후 다시 시도하세요.')
            time.sleep(.05)
    try:
        yield
    finally:
        lock.rmdir()

def read(events):
    return [json.loads(line) for line in events.read_text(encoding='utf-8').splitlines() if line.strip()] if events.exists() else []

def update(events, event_id, **fields):
    with locked(events):
        rows = read(events)
        row = next((r for r in rows if r.get('id') == event_id), None)
        if row is None:
            raise ValueError('제출 ID를 찾지 못했습니다.')
        row.update(fields)
        tmp = events.with_name(events.name + '.tmp')
        with tmp.open('w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, events)
        return row

def submit(events, doc, agent, source, payload, thread=None, executable=None, owner=None):
    event_id = str(uuid.UUID(payload.get('id') or str(uuid.uuid4())))
    if not isinstance(payload.get('edits'), list) or not isinstance(payload.get('comments'), list):
        raise ValueError('edits와 comments는 목록이어야 합니다.')
    with locked(events):
        existing = next((r for r in read(events) if r.get('id') == event_id), None)
        if existing:
            if existing.get('doc') != str(doc):
                raise ValueError('다른 문서의 제출 ID입니다.')
            return existing  # Same request retried: never queue it twice.
        final = bool(payload.get('final'))   # '마무리' — 수정이 있어도 이걸로 끝, 더 고칠 것 없음
        conflict = bool(payload.get('conflict'))   # 화면이 옛 판이라 파일에 저장하지 못했다 — edits 는 에이전트가 현재 파일에 before→after 로 적용한다
        row = dict(id=event_id, edits=payload['edits'], comments=payload['comments'], final=final, conflict=conflict,
                   approved=final or (not payload['edits'] and not payload['comments']),
                   ts=datetime.datetime.now().isoformat(timespec='seconds'), doc=str(doc),
                   agent=agent, source=source, status='new', thread_id=thread, owner=owner,
                   delivery='pending' if thread and executable else 'manual')
        with events.open('a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())
    if not thread or not executable:
        return row
    message = (f'[review-ai-artifacts] 사용자 제출이 저장되었습니다. 이벤트 ID: {event_id}\n'
               f'문서: {doc}\n제출 파일: {events}\n'
               '이 ID의 수정·댓글을 읽고 반영하세요. 사용자 HTML 편집을 보존하고 원본에도 동기화하세요. '
               '해당 문서의 검토 승인은 외부 배포·공유 승인이 아닙니다. '
               '이미 처리한 ID면 중복 작업하지 마세요. 완료 후 스킬의 --ack 절차로 처리 결과를 기록하세요.')
    try:
        result = subprocess.run([executable, 'queue', '--thread', thread, '--message', message],
                                capture_output=True, text=True, timeout=20)
        delivery = 'queued' if result.returncode == 0 else 'failed'
    except subprocess.TimeoutExpired:
        delivery = 'unknown'  # Queue may have accepted it; do not retry automatically.
    except OSError:
        delivery = 'failed'
    return update(events, event_id, delivery=delivery)

def status(events, doc, thread=None, owner=None):
    # 남의 세션 제출은 이 화면의 대기 건수가 아니다 (owner 없는 구형 줄은 포함).
    # owner 로 집합을 주면 그 세션들 전부를 이 화면 것으로 본다 — 주인이 끊겨 이어받은 세션 앞으로 간 제출을 놓치지 않는다.
    allowed = owner if isinstance(owner, (set, frozenset)) else ({owner} if owner else None)
    rows = [r for r in read(events) if r.get('doc') == str(doc) and (allowed is None or r.get('owner') is None or r.get('owner') in allowed)]
    row = rows[-1] if rows else {}
    result = {k:row.get(k) for k in ('id','status','delivery','result','approved','final','conflict')}
    result.update(automatic=bool(thread), pending_count=sum(r.get('status') == 'new' for r in rows))
    return result
