"""Apply explicit source reviews to the exact captured segment snapshot, offline."""
from copy import deepcopy
import hashlib
import json

from .client import ApiError
from .data import dataset, now, read_json, sha256, write_json


def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def apply_reviews(bindings, segments, gold, review):
    result=deepcopy(bindings)
    if review['base_url']!=bindings['base_url'] or review['kb_id']!=bindings['kb_id']:
        raise ApiError('Review belongs to another server or knowledge base.')
    seen=set()
    for item in review['items']:
        eid=item['evidence_id']
        if eid in seen:
            raise ApiError(f'Duplicate review: {eid}')
        seen.add(eid)
        evidence=gold[eid]
        doc_id=evidence['doc_id']
        doc=bindings['documents'][doc_id]
        if item['doc_id']!=doc_id or item['document_sha256']!=doc['document_sha256'] or item['quote_sha256']!=evidence['quote_sha256']:
            raise ApiError(f'Review source version mismatch: {eid}')
        if item['text_fidelity'] not in ('equivalent','partial') or not item.get('note'):
            raise ApiError(f'Review requires a fidelity assessment and rationale: {eid}')
        ids=[]
        for witness in item['segments']:
            sid=witness['segment_id']
            segment=segments.get(doc_id,{}).get(sid)
            if not segment or segment.get('assetId')!=doc['asset_id'] or segment.get('kbId')!=bindings['kb_id']:
                raise ApiError(f'Review segment outside source scope: {eid}/{sid}')
            page=(segment.get('anchor') or {}).get('pageNo')
            content=segment.get('content') or ''
            if page!=evidence['page_no'] or text_hash(content)!=witness['content_sha256']:
                raise ApiError(f'Review segment page or content changed: {eid}/{sid}')
            if not witness['observed_quote'] or witness['observed_quote'] not in content:
                raise ApiError(f'Review excerpt not found in captured segment: {eid}/{sid}')
            ids.append(sid)
        if not ids:
            raise ApiError(f'Review needs an observed segment: {eid}')
        result['evidence'][eid].update({
            'segment_ids':ids,'source_location_verified':True,
            'status':'reviewed_equivalent' if item['text_fidelity']=='equivalent' else 'located_text_partial',
            'verified_quote_coverage':item['text_fidelity']=='equivalent',
            'text_fidelity':item['text_fidelity'],'reviewer':review['reviewer'],
            'reviewed_at':review['reviewed_at'],'note':item['note'],
            'review_segments':item['segments'],
            'active_segment_check':'preview endpoint accepted at captured binding time'})
    for evidence in result['evidence'].values():
        if evidence['status']=='quote_verified':
            evidence['source_location_verified']=True
            evidence['text_fidelity']='exact_after_layout_normalization'
    result['source_location_count']=sum(bool(e.get('source_location_verified')) for e in result['evidence'].values())
    result['verified_evidence_count']=sum(e['verified_quote_coverage'] for e in result['evidence'].values())
    result['status']='source_locations_reviewed' if result['source_location_count']==len(result['evidence']) else 'partial'
    return result


def review_bindings(root, review_path, emit=print):
    corpus,cases=dataset(root)
    folder=root/'runs/setup'
    segments=read_json(folder/'segments.json')
    review=read_json(review_path)
    if review['segments_snapshot_sha256']!=sha256(folder/'segments.json'):
        raise ApiError('Captured segments changed; review must be repeated.')
    gold={e['evidence_id']:e for c in cases for e in c['evidence']}
    binding=apply_reviews(read_json(folder/'bindings.json'),segments,gold,review)
    write_json(folder/'bindings.reviewed.json',binding)
    # A derived dataset leaves the frozen gold source entirely unchanged.
    bound=deepcopy(cases)
    for case in bound:
        case['scope'].update({'kb_ids':[binding['kb_id']],
            'asset_ids':[binding['documents'][doc_id]['asset_id'] for doc_id in case['scope']['doc_ids']],
            'binding_status':'documents_bound'})
        for e in case['evidence']:
            entry=binding['evidence'][e['evidence_id']]
            e['segment_ids']=entry['segment_ids']
            e['segment_binding_status']=entry['status']
            e['binding_note']=entry['note']
            e['kb_id']=binding['kb_id']
            e['asset_id']=binding['documents'][e['doc_id']]['asset_id']
            e['index_generation']=None
            e['parsed_quote_coverage_verified']=entry['verified_quote_coverage']
        case['binding_review']={'created_at':now(),'reviewer':review['reviewer'],
            'segments_snapshot_sha256':review['segments_snapshot_sha256'],
            'partial_text_evidence_ids':[e['evidence_id'] for e in case['evidence'] if not e['parsed_quote_coverage_verified']]}
    target=folder/'cases.bound.jsonl'
    target.write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in bound),encoding='utf-8')
    emit(f"Located {binding['source_location_count']}/{len(gold)} evidence anchors; text coverage verified for {binding['verified_evidence_count']}/{len(gold)}. Derived cases: {target}")
    return binding
