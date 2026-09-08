import pytest
from anchr_eval.client import ApiError
from anchr_eval.runner import resolve_scope


def test_missing_asset_never_falls_back_to_all_documents():
    with pytest.raises(ApiError,match='Missing document binding'):
        resolve_scope({'scope':{'doc_ids':['D001']}},{'kb_id':'kb1','documents':{}})


def test_explicit_scope_resolved_from_real_bindings():
    case={'scope':{'doc_ids':['D002','D001']}}
    bindings={'kb_id':'kb1','documents':{'D001':{'asset_id':'a1','kb_id':'kb1'},'D002':{'asset_id':'a2','kb_id':'kb1'}}}
    assert resolve_scope(case,bindings)=={'kbIds':['kb1'],'assetIdList':['a2','a1']}
