import pytest
from anchr_eval.batch import reconcile
from anchr_eval.client import ApiError
from anchr_eval.data import write_json


def test_recover_completed_run_after_interruption(tmp_path):
    write_json(tmp_path/'runs/r1/run.json',{'status':'response_received'})
    entry={'case_id':'q1','run_id':'r1','status':'started'}
    assert reconcile(entry,tmp_path)
    assert entry['status']=='response_received'


def test_uncertain_run_is_not_repeated(tmp_path):
    write_json(tmp_path/'runs/r1/run.json',{'status':'running','session_id':'s1'})
    with pytest.raises(ApiError,match='incomplete'):
        reconcile({'case_id':'q1','run_id':'r1','status':'started'},tmp_path)


def test_pending_case_can_start(tmp_path):
    assert reconcile({'case_id':'q1','run_id':'r1','status':'pending'},tmp_path) is False
