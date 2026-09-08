from pathlib import Path
from types import SimpleNamespace
import pytest

from anchr_eval.client import ApiError
from anchr_eval.data import write_json, read_json
from anchr_eval.ingestion import DESCRIPTION, prepare
import anchr_eval.ingestion as ingestion


def test_uncertain_submission_reconciles_without_reupload(tmp_path, monkeypatch):
    monkeypatch.setattr(ingestion, 'dataset', lambda root: ({'documents':[]}, []))
    state={'base_url':'https://example.test','kb_id':'kb1','client_request_id':'same-request',
           'task_submit_started':'earlier','uploads':{}}
    write_json(tmp_path/'runs/setup/ingestion.json',state)
    calls=[]
    class Client:
        config=SimpleNamespace(base_url='https://example.test')
        def get(self,path,**kwargs):
            calls.append(path)
            if path.endswith('/validate-token'): return {'valid':True,'role':'ADMIN'}
            if path.endswith('/kbs/kb1'): return {'description':DESCRIPTION}
            if '/by-client-request/' in path: return {'taskId':'t1'}
            if path.endswith('/ingestion-tasks/t1'):
                return {'status':'SUCCESS','successCount':0,'failureCount':0,'runningCount':0,'items':[]}
            if path.endswith('/documents'): return {'items':[]}
            raise AssertionError(path)
        def post(self,*args):
            raise AssertionError('Must not create again')
    prepare(tmp_path,Client(),lambda s:None)
    assert any('/by-client-request/same-request' in p for p in calls)
    assert not any(p.endswith('/sts') for p in calls)
    assert read_json(tmp_path/'runs/setup/ingestion.json')['task_id']=='t1'


def test_unrelated_same_name_kb_is_not_reused(tmp_path,monkeypatch):
    monkeypatch.setattr(ingestion,'dataset',lambda root: ({'documents':[]},[]))
    class Client:
        config=SimpleNamespace(base_url='https://example.test')
        def get(self,*args): return {'valid':True,'role':'ADMIN'}
        def post(self,path,payload):
            assert path=='/api/v1/kbs/search'
            return {'items':[{'id':'other','name':'anchr-eval-seed-v1','description':'Unrelated data'}]}
    with pytest.raises(ApiError,match='conflicting'):
        prepare(tmp_path,Client())


def test_other_server_state_is_rejected(tmp_path,monkeypatch):
    monkeypatch.setattr(ingestion,'dataset',lambda root: ({'documents':[]},[]))
    write_json(tmp_path/'runs/setup/ingestion.json',{'base_url':'https://first.test'})
    client=SimpleNamespace(config=SimpleNamespace(base_url='https://second.test'))
    with pytest.raises(ApiError,match='another API server'):
        prepare(tmp_path,client)
