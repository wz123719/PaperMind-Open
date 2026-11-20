import subprocess
from pathlib import Path

def test_codepoint_offsets_and_stream_event_reducer():
    root=Path(__file__).resolve().parents[1]
    node='node'
    script='''
import assert from 'node:assert/strict';
import {codePointOffset,layerText} from './frontend/src/services/selection.ts';
import {reduceEvent,questionIssue} from './frontend/src/services/chat.ts';
assert.equal(questionIssue('😀'.repeat(4000)),'');assert.notEqual(questionIssue('😀'.repeat(4001)),'');
assert.deepEqual([0,1,2,3,4,5,6].map(i=>codePointOffset('中😀e\\u0301文',i)),[0,1,null,2,3,4,5]);
const txt=value=>({nodeType:3,nodeValue:value,childNodes:[]});
const logical=layerText({nodeType:1,nodeName:'DIV',childNodes:[txt('The change is'),{nodeType:1,nodeName:'BR',childNodes:[]},txt('-3😀 percent.')]});
assert.equal(logical,'The change is\\n-3😀 percent.');
let s={lastId:0,attempt:0,content:'',status:'draft',claims:[],error:''};
s=reduceEvent(s,1,'start',{attempt:1});s=reduceEvent(s,2,'delta',{attempt:1,text:'old'});
s=reduceEvent(s,2,'delta',{attempt:1,text:'old'});assert.equal(s.content,'old');
s=reduceEvent(s,3,'failed',{attempt:1,retrying:true,error:'partial'});
s=reduceEvent(s,4,'start',{attempt:2});s=reduceEvent(s,5,'delta',{attempt:2,text:'new😀'});
assert.equal(s.content,'new😀');
s=reduceEvent(s,6,'completed',{attempt:2,content:'new😀 done',claims:[],source_version:'chat-source-2-symbols',identity:{paper_file_id:'version-two',parse_run_id:'source-run'}});
assert.equal(s.status,'completed');assert.equal(s.content,'new😀 done');
assert.equal(s.identity.paper_file_id,'version-two');assert.equal(s.identity.parse_run_id,'source-run');
assert.equal(s.sourceVersion,'chat-source-2-symbols');
const prestart=reduceEvent({lastId:0,attempt:0,content:'',status:'draft',claims:[],error:''},1,'failed',{attempt:1,retrying:false,error:'legacy contract rejected'});
assert.equal(prestart.status,'failed');assert.equal(prestart.attempt,1);
console.log('UTF16/codepoint and retry/replay reducer passed');
'''
    result=subprocess.run([str(node),'--input-type=module','-e',script],cwd=root,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
