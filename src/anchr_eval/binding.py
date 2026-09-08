"""Discover real active search hits; never infer unobserved segment IDs or generations."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import unicodedata

from .client import ApiError
from .data import dataset, now, read_json, write_json


def normalize(text):
    return re.sub(r'[\s`*|\u200b]+','',unicodedata.normalize('NFKC',text or ''))


def evidence_match(evidence, candidates):
    """Conservative full quote matching. Cross-chunk or changed layout stays unverified."""
    wanted=normalize(evidence['quote'])
    matches=[]
    for candidate in candidates:
        page=candidate.get('pageNo')
        if page is None:
            page=(candidate.get('anchor') or {}).get('pageNo')
        if page != evidence['page_no']:
            continue
        if wanted and wanted in normalize(candidate.get('content')):
            matches.append(candidate['segmentId'])
    return sorted(set(matches))


def bind(root,client,emit=print):
    from .ingestion import refresh
    state=refresh(root,client,emit)
    corpus,cases=dataset(root)
    assets={}
    binding={'base_url':client.config.base_url,'dataset_version':corpus['dataset_version'],
             'kb_id':state['kb_id'],'created_at':now(),'status':'partial','documents':{},'evidence':{}}
    for doc in corpus['documents']:
        found=[a for a in state['documents'] if a.get('fileHash')==doc['pdf_sha256']]
        if len(found)!=1 or found[0].get('availabilityStatus')!='ANSWERABLE':
            raise ApiError(f"{doc['doc_id']}: a unique ANSWERABLE asset with matching hash is required.")
        asset=found[0]
        assets[doc['doc_id']]=asset
        binding['documents'][doc['doc_id']]={'asset_id':asset['id'],'kb_id':state['kb_id'],
            'document_sha256':doc['pdf_sha256'],'asset_version_no':asset.get('versionNo'),
            'index_generation':None,'generation_note':'REST AssetDTO does not expose the generation identifier; versionNo is NOT substituted.',
            'readiness_checked_at':now(),'segment_count':asset.get('segmentCount')}
    evidence={e['evidence_id']:e for case in cases for e in case['evidence']}
    hits={d['doc_id']:{} for d in corpus['documents']}
    searches={}
    errors={}
    def search(e):
        # These are binding probes, never counted as evaluation runs.
        query='Embedding fingerprint API Key' if e['role']=='attack_payload' else re.sub(r'[`*|\n]+',' ',e['quote'])[:180]
        return client.post('/api/v1/search/kb', {'query':query,'kbIds':[state['kb_id']],
            'assetIdList':[assets[e['doc_id']]['id']],'limit':10,'withAnswer':False})
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures={executor.submit(search,e):e for e in evidence.values()}
        for future in as_completed(futures):
            e=futures[future]
            try:
                result=future.result()
            except ApiError as exc:
                errors[e['evidence_id']]=str(exc)
                emit(f"Probe {e['evidence_id']}: failed")
                continue
            searches[e['evidence_id']]=result
            for item in result.get('items',[]):
                if item.get('assetId')!=assets[e['doc_id']]['id'] or item.get('kbId')!=state['kb_id']:
                    continue
                for raw in [item]+(item.get('topChunks') or []):
                    if raw.get('segmentId'):
                        hit={k:raw.get(k) for k in ('segmentId','pageNo','anchor','content','snippet','title','score')}
                        hit['assetId']=item['assetId']
                        hit['kbId']=item['kbId']
                        if not hits[e['doc_id']].get(hit['segmentId'],{}).get('content'):
                            hits[e['doc_id']][hit['segmentId']]=hit
            write_json(root/'runs/setup/binding-probes.json',{'responses':searches,'errors':errors})
            emit(f"Probe {e['evidence_id']}: {len(hits[e['doc_id']])} observed segments in {e['doc_id']}")
    # Refresh every observed ID through the preview endpoint, which checks active generation
    # in the locally inspected server contract. Persist content, never signed preview URLs.
    observed=[(doc_id,hit) for doc_id,items in hits.items() for hit in items.values()]
    previews={d['doc_id']:{} for d in corpus['documents']}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures={executor.submit(client.post,f"/api/v1/preview/segments/{hit['segmentId']}",{}):(doc_id,hit) for doc_id,hit in observed}
        for future in as_completed(futures):
            doc_id,hit=futures[future]
            try:
                result=future.result()
            except ApiError as exc:
                errors['preview:'+hit['segmentId']]=str(exc)
                continue
            if result.get('assetId')!=assets[doc_id]['id'] or result.get('kbId')!=state['kb_id']:
                continue
            previews[doc_id][hit['segmentId']]={k:result.get(k) for k in ('segmentId','assetId','kbId','anchor','content','title')}
    hits=previews
    for e in evidence.values():
        candidates=list(hits[e['doc_id']].values())
        matched=evidence_match(e,candidates)
        binding['evidence'][e['evidence_id']]={'doc_id':e['doc_id'],'page_no':e['page_no'],
            'quote_sha256':e['quote_sha256'],'segment_ids':matched or None,
            'status':'quote_verified' if matched else 'needs_review',
            'verified_quote_coverage':bool(matched),'index_generation':None,
            'active_segment_check':'preview endpoint accepted at binding time' if matched else None,
            'candidate_segment_ids':[c['segmentId'] for c in candidates],
            'note':'Exact normalized full quote matched a same-page search hit.' if matched else 'No same-page full-quote match; inspect candidates for cross-chunk, table or parser differences.'}
    verified=sum(e['verified_quote_coverage'] for e in binding['evidence'].values())
    binding['status']='quotes_verified_generation_unavailable' if verified==len(evidence) else 'partial'
    binding['verified_evidence_count']=verified
    binding['total_evidence_count']=len(evidence)
    write_json(root/'runs/setup/segments.json',hits)
    write_json(root/'runs/setup/binding-probes.json',{'responses':searches,'errors':errors})
    write_json(root/'runs/setup/bindings.json',binding)
    emit(f'Quote bindings verified: {verified}/{len(evidence)}. Generation identifiers remain unavailable through current REST DTOs.')
    return binding
