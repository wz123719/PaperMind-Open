"""Private, content-addressed intermediate results. Never public parse artifacts."""
import hashlib,json,os,time,uuid
from .db import STORAGE

VERSION='object-cache-1'

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

class ObjectCache:
    def __init__(self,identity,root=None):
        self.identity=identity;self.root=root or STORAGE/'private-cache'/'objects';self.events=[]
        self.event_path=self.root.parent/'attempt-events'/(uuid.uuid4().hex+'.jsonl')
    def record(self,event):
        self.events.append(event);self.event_path.parent.mkdir(parents=True,exist_ok=True)
        with self.event_path.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({'time':time.time(),'identity':digest(self.identity),**event},ensure_ascii=False)+'\n')
    def key(self,features):return digest({'cache_version':VERSION,'identity':self.identity,'input':features})
    def get(self,features):
        key=self.key(features);path=self.root/key[:2]/(key+'.json')
        try:
            record=json.loads(path.read_text(encoding='utf-8'))
            if record['key']!=key or digest(record['result'])!=record['result_sha256']:raise ValueError('corrupt')
        except (OSError,ValueError,KeyError):
            self.record({'type':'cache_miss','key':key});return None
        self.record({'type':'cache_hit','key':key});return record['result']
    def put(self,features,result):
        key=self.key(features);dest=self.root/key[:2]/(key+'.json');dest.parent.mkdir(parents=True,exist_ok=True)
        record={'key':key,'identity':self.identity,'input':features,'result':result,'result_sha256':digest(result),'created_at':time.time()}
        tmp=dest.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        try:
            tmp.write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8');os.replace(tmp,dest)
        finally:tmp.unlink(missing_ok=True)
        self.record({'type':'cache_write','key':key})
