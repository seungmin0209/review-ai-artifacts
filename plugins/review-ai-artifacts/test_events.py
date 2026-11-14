"""Run: python3 test_events.py. Uses isolated files and a fake queue command."""
from pathlib import Path
import json
import tempfile
import uuid
from unittest.mock import patch
import subprocess
import events

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory); log=root/'_review_events.jsonl'; doc=root/'doc.html'
    payload={'id':str(uuid.uuid4()),'edits':[],'comments':[{'text':'review'}]}
    def accept(argv, **kwargs):
        assert argv[:4] == ['codex','queue','--thread','thread-a']
        # Submission must already be durable when notification is queued.
        assert events.read(log)[0]['id']==payload['id']
        return subprocess.CompletedProcess(argv,0,'Queued','')
    with patch('events.subprocess.run',side_effect=accept) as queue:
        result=events.submit(log,doc,'Codex','html',payload,'thread-a','codex')
        assert result['delivery']=='queued' and result['status']=='new'
        events.submit(log,doc,'Codex','html',payload,'thread-a','codex')
        assert queue.call_count==1 and len(events.read(log))==1
    events.update(log,payload['id'],status='done',result='checked')
    assert events.status(log,doc)['result']=='checked'
    assert events.status(log,root/'other.html')['id'] is None
    for outcome,expected in [(subprocess.CompletedProcess([],1),'failed'),(subprocess.TimeoutExpired('codex',20),'unknown')]:
        p={**payload,'id':str(uuid.uuid4())}
        with patch('events.subprocess.run',side_effect=outcome if isinstance(outcome,Exception) else None,return_value=outcome):
            r=events.submit(log,doc,'Codex','html',p,'thread-a','codex')
        assert r['delivery']==expected and r['status']=='new'
    manual=events.submit(log,doc,'Codex','html',{'edits':[],'comments':[]})
    assert manual['delivery']=='manual' and manual['approved']
    # Updating delivery must preserve a concurrently acknowledged result.
    events.update(log,manual['id'],status='done')
    assert events.update(log,manual['id'],delivery='queued')['status']=='done'
print('PASS: durable save, exact target, idempotency, ack, document isolation, failures, timeout, manual fallback')
