from pathlib import Path
import anchr_eval.scoring as scoring
from anchr_eval.data import write_json,sha256


def test_invalid_attack_case_is_reported_but_excluded_from_correctness(tmp_path,monkeypatch):
    cases=[]; entries=[]; labels=[]
    for n in (1,2):
        cid=f'q{n}';rid=f'r{n}';fact=f'{cid}-f1';folder=tmp_path/'runs'/rid
        cases.append({'id':cid,'type':'single_document' if n==1 else 'prompt_injection','question':'question',
            'reference_answer':'reference','has_answer':True,'must_cover_facts':[{'fact_id':fact,'text':'fact'}],
            'citation_check':{'required':True},'retrieval_scoring':{'eligible':True,'gold_doc_ids':['D1']}})
        entries.append({'case_id':cid,'run_id':rid})
        write_json(folder/'run.json',{'search_latency_ms':10,'answer_latency_ms':20})
        write_json(folder/'answer.json',{'answer':'fact[1]','answerStatus':'ANSWERED','executionMode':'TRADITIONAL','citations':[]})
        write_json(folder/'search.json',{'items':[{'assetId':'a1'}]})
        write_json(folder/'bindings.snapshot.json',{'documents':{'D1':{'asset_id':'a1'}}})
        labels.append({'case_id':cid,'run_id':rid,'answer_sha256':sha256(folder/'answer.json'),
            'fact_results':[{'fact_id':fact,'answer_covered':n==1,'citation_supported':n==1}],
            'material_error':False,'expected_behavior_pass':False,'additional_claims_supported':True,
            'visible_citation_count':1,'valid_citation_count':1 if n==1 else 0,'special_requirements_pass':n==1,
            'evaluation_validity':'valid' if n==1 else 'invalid_document_attack_input','notes':'reviewed'})
    monkeypatch.setattr(scoring,'dataset',lambda root: ({},cases))
    batch={'name':'test','dataset_sha256':'frozen','case_ids':['q1','q2'],'entries':entries}
    write_json(tmp_path/'runs/test/batch.json',batch)
    review={'batch_name':'test','dataset_sha256':'frozen','reviewer':'test','review_method':'explicit','cases':labels}
    path=tmp_path/'runs/test/review.json';write_json(path,review)
    result=scoring.score_batch(tmp_path,'test',path,lambda x:None)
    assert result['observed_case_count']==2
    assert result['valid_case_count']==1
    assert result['answerable_count']==1
    assert result['strict_pass_rate']==1
    assert result['invalid_case_ids']==['q2']
    assert len(result['rows'])==2
