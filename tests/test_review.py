from copy import deepcopy
import pytest
from anchr_eval.client import ApiError
from anchr_eval.review import apply_reviews,text_hash


def fixture():
    bindings={'base_url':'https://example.test','kb_id':'k1','documents':{'D1':{'asset_id':'a1','document_sha256':'hash'}},
              'evidence':{'E1':{'status':'needs_review','verified_quote_coverage':False}}}
    segments={'D1':{'s1':{'assetId':'a1','kbId':'k1','anchor':{'pageNo':1},'content':'字段 / 丢失'}}}
    gold={'E1':{'doc_id':'D1','quote_sha256':'quote','page_no':1}}
    review={'base_url':'https://example.test','kb_id':'k1','reviewer':'fixture','reviewed_at':'now',
            'items':[{'evidence_id':'E1','doc_id':'D1','document_sha256':'hash','quote_sha256':'quote',
                      'text_fidelity':'partial','note':'A source character was lost.',
                      'segments':[{'segment_id':'s1','content_sha256':text_hash('字段 / 丢失'),'observed_quote':'字段 / 丢失'}]}]}
    return bindings,segments,gold,review


def test_located_but_corrupt_text_is_not_verified():
    result=apply_reviews(*fixture())
    assert result['source_location_count']==1
    assert result['verified_evidence_count']==0
    assert result['evidence']['E1']['segment_ids']==['s1']


def test_changed_segment_invalidates_old_review():
    b,s,g,r=fixture()
    s['D1']['s1']['content']='新版本内容'
    with pytest.raises(ApiError,match='content changed'):
        apply_reviews(b,s,g,r)


def test_wrong_page_and_fabricated_excerpt_rejected():
    b,s,g,r=fixture()
    s['D1']['s1']['anchor']['pageNo']=2
    with pytest.raises(ApiError,match='page or content'):
        apply_reviews(b,s,g,r)
    b,s,g,r=fixture()
    r['items'][0]['segments'][0]['observed_quote']='a made-up quote'
    with pytest.raises(ApiError,match='excerpt not found'):
        apply_reviews(b,s,g,r)
