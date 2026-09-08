"""One-case smoke run. Raw evidence is preserved, scores are never guessed."""
from time import perf_counter
import uuid

from .client import ApiError
from .data import dataset, now, read_json, write_json, sha256


def resolve_scope(case,bindings):
    if not bindings.get('kb_id'):
        raise ApiError('Knowledge base binding missing.')
    asset_ids=[]
    for doc_id in case['scope']['doc_ids']:
        doc=bindings.get('documents',{}).get(doc_id,{})
        if not doc.get('asset_id'):
            raise ApiError(f'Missing document binding: {doc_id}; refusing an unscoped query.')
        if doc.get('kb_id') != bindings['kb_id']:
            raise ApiError('Document belongs to a different knowledge base.')
        asset_ids.append(doc['asset_id'])
    if not asset_ids:
        raise ApiError('An explicit document scope is required.')
    return {'kbIds':[bindings['kb_id']],'assetIdList':asset_ids}


def smoke(root,client,case_id,emit=print,run_id=None):
    corpus,cases=dataset(root)
    case=next((c for c in cases if c['id']==case_id),None)
    if case is None:
        raise ApiError(f'Unknown case: {case_id}')
    reviewed=root/'runs/setup/bindings.reviewed.json'
    binding=read_json(reviewed if reviewed.exists() else root/'runs/setup/bindings.json')
    if binding['base_url']!=client.config.base_url:
        raise ApiError('Bindings belong to another server.')
    scope=resolve_scope(case,binding)
    expected={d['doc_id']:d for d in corpus['documents']}
    for doc_id in case['scope']['doc_ids']:
        doc=binding['documents'][doc_id]
        current=client.get(f"/api/v1/kbs/{binding['kb_id']}/documents/{doc['asset_id']}")
        if current.get('fileHash')!=expected[doc_id]['pdf_sha256'] or current.get('availabilityStatus')!='ANSWERABLE':
            raise ApiError(f'Document changed or is unavailable: {doc_id}')
    run_id=run_id or f'smoke-{uuid.uuid4()}'
    folder=root/'runs'/run_id
    if folder.exists():
        raise ApiError(f'Run directory already exists: {folder}; refusing to repeat a potentially submitted question.')
    record={'run_id':run_id,'case_id':case_id,'kind':'smoke','started_at':now(),
            'base_url':client.config.base_url,'dataset_version':corpus['dataset_version'],
            'dataset_sha256':sha256(root/'datasets/anchr-seed-v1/cases.jsonl'),
            'scope':scope,'requested_execution_mode':'TRADITIONAL','answer_mode':'STRICT',
            'status':'running','grading_status':'manual_review_pending',
            'generation_identifier_available':False}
    write_json(folder/'run.json',record)
    write_json(folder/'bindings.snapshot.json',binding)
    write_json(folder/'case.snapshot.json',case)
    config_snapshot=root/'runs/setup/server-snapshot.json'
    if config_snapshot.exists():
        write_json(folder/'server-snapshot.json',read_json(config_snapshot))
    try:
        start=perf_counter()
        retrieval=client.post('/api/v1/search/kb',{'query':case['question'],**scope,'limit':5,'withAnswer':False})
        record['search_latency_ms']=round((perf_counter()-start)*1000,2)
        write_json(folder/'search.json',retrieval)
        emit(f'Search saved: {run_id}')
        session=client.post('/api/v1/conversations',{'title':f'anchr-eval {case_id}', 'kbIds':scope['kbIds']})
        record['session_id']=session['sessionId']
        record['message_submission_started_at']=now()
        write_json(folder/'run.json',record)
        request={'query':case['question'],**scope,'limit':5,'answerMode':'STRICT','agentEnabled':False,'debug':True}
        write_json(folder/'request.json',request)
        start=perf_counter()
        answer=client.post(f"/api/v1/conversations/{session['sessionId']}/messages",request)
        record['answer_latency_ms']=round((perf_counter()-start)*1000,2)
        write_json(folder/'answer.json',answer)
        record.update({'status':'response_received','turn_id':answer.get('turnId'),
                       'execution_mode':answer.get('executionMode'),'answer_status':answer.get('answerStatus'),
                       'citation_document_count':len(answer.get('citations') or []),
                       'token_usage':None,'estimated_cost':None})
    except ApiError as exc:
        record['status']='client_error_outcome_unconfirmed'
        record['error']=str(exc)
        raise
    finally:
        record['finished_at']=now()
        write_json(folder/'run.json',record)
        emit(f'Run artifacts: {folder}')
    emit(f"Answer status: {record['answer_status']}; citation documents: {record['citation_document_count']}; manual review pending.")
    return record
