"""Aggregate source-reviewed labels separately from raw API observations."""
from collections import Counter
from pathlib import Path
import math
import re

from .client import ApiError
from .data import dataset,read_json,write_json,now,sha256


def retrieval_scores(items,gold,k=5):
    if not gold:
        return {'recall_at_5':None,'mrr_at_5':None}
    ranking=list(dict.fromkeys(item.get('assetId') for item in items if item.get('assetId')))[:k]
    gold=set(gold)
    return {'recall_at_5':len(gold.intersection(ranking))/len(gold),
            'mrr_at_5':next((1/i for i,asset in enumerate(ranking,1) if asset in gold),0.0)}


def percentile(values,q):
    if not values: return None
    values=sorted(values)
    pos=(len(values)-1)*q
    low=math.floor(pos); high=math.ceil(pos)
    return values[low]+(values[high]-values[low])*(pos-low)


def score_batch(root,batch_name,review_path,emit=print):
    if not re.fullmatch(r'[A-Za-z0-9._-]+',batch_name) or batch_name in ('.','..'):
        raise ApiError('Batch name must be a simple directory name.')
    folder=root/'runs'/batch_name
    batch=read_json(folder/'batch.json')
    labels=read_json(review_path)
    _,cases=dataset(root)
    cases={c['id']:c for c in cases}
    if labels['batch_name']!=batch_name or labels['dataset_sha256']!=batch['dataset_sha256']:
        raise ApiError('Review does not match the batch or dataset.')
    by_id={r['case_id']:r for r in labels['cases']}
    if len(by_id)!=len(labels['cases']) or set(by_id)!=set(batch['case_ids']):
        raise ApiError('Exactly one review for every batch case is required.')
    rows=[]
    for entry in batch['entries']:
        cid=entry['case_id']; case=cases[cid]; label=by_id[cid]
        run_folder=root/'runs'/entry['run_id']
        run=read_json(run_folder/'run.json')
        answer=read_json(run_folder/'answer.json')
        search=read_json(run_folder/'search.json')
        if label['answer_sha256']!=sha256(run_folder/'answer.json') or label['run_id']!=entry['run_id']:
            raise ApiError(f'Reviewed answer changed: {cid}')
        facts={f['fact_id'] for f in case['must_cover_facts']}
        fact_results=label['fact_results']
        if {f['fact_id'] for f in fact_results}!=facts or len(fact_results)!=len(facts):
            raise ApiError(f'Review must cover each required fact once: {cid}')
        flags=[label[key] for key in ('material_error','expected_behavior_pass','additional_claims_supported','special_requirements_pass')]
        flags += [f[key] for f in fact_results for key in ('answer_covered','citation_supported')]
        if any(type(flag) is not bool for flag in flags):
            raise ApiError(f'Review verdicts must be JSON booleans: {cid}')
        visible=len(re.findall(r'\[\d+(?:-\d+)?\]',answer.get('answer') or ''))
        if label['visible_citation_count']!=visible or type(label['valid_citation_count']) is not int or not 0<=label['valid_citation_count']<=visible:
            raise ApiError(f'Citation counts do not match the actual answer: {cid}')
        correct=(all(f['answer_covered'] for f in fact_results) and not label['material_error']) if case['has_answer'] else label['expected_behavior_pass']
        precision=(label['valid_citation_count']/label['visible_citation_count']) if label['visible_citation_count'] else None
        coverage=sum(f['citation_supported'] and f['answer_covered'] for f in fact_results)/len(facts) if facts else None
        citation_pass=(precision==1 and coverage==1) if case['citation_check']['required'] else label['additional_claims_supported']
        passed=correct and citation_pass and label['special_requirements_pass']
        binding=read_json(run_folder/'bindings.snapshot.json')
        gold_ids=[binding['documents'][d]['asset_id'] for d in case['retrieval_scoring']['gold_doc_ids']]
        metrics=retrieval_scores(search.get('items',[]),gold_ids) if case['retrieval_scoring']['eligible'] else {'recall_at_5':None,'mrr_at_5':None}
        rows.append({'case_id':cid,'type':case['type'],'has_answer':case['has_answer'],
            'answer_status':answer.get('answerStatus'),'execution_mode':answer.get('executionMode'),
            'answer_correct':correct,'citation_precision':precision,'citation_coverage':coverage,
            'case_pass':passed,'evaluation_validity':label['evaluation_validity'],
            'attack_exposure':label.get('attack_exposure'),'review_notes':label['notes'],
            'search_latency_ms':run.get('search_latency_ms'),'answer_latency_ms':run.get('answer_latency_ms'),**metrics})
    valid=[r for r in rows if r['evaluation_validity']=='valid']
    answerable=[r for r in valid if r['has_answer']]
    metric_rows=[r for r in rows if r['recall_at_5'] is not None]
    mean=lambda xs:sum(xs)/len(xs) if xs else None
    no_answer=[r for r in valid if r['type']=='unanswerable']
    ambiguous=[r for r in valid if r['type']=='ambiguous']
    summary={'batch_name':batch_name,'reviewer':labels['reviewer'],'review_method':labels['review_method'],
        'scored_at':now(),'observed_case_count':len(rows),'valid_case_count':len(valid),
        'invalid_case_ids':[r['case_id'] for r in rows if r['evaluation_validity']!='valid'],
        'strict_pass_count':sum(r['case_pass'] for r in valid),'strict_pass_rate':mean([r['case_pass'] for r in valid]),
        'answerable_correct_count':sum(r['answer_correct'] for r in answerable),'answerable_count':len(answerable),
        'answerable_correct_rate':mean([r['answer_correct'] for r in answerable]),
        'citation_valid_count':sum(by_id[r['case_id']]['valid_citation_count'] for r in valid),
        'citation_visible_count':sum(by_id[r['case_id']]['visible_citation_count'] for r in valid),
        'citation_precision_micro':(sum(by_id[r['case_id']]['valid_citation_count'] for r in valid)/sum(by_id[r['case_id']]['visible_citation_count'] for r in valid)) if sum(by_id[r['case_id']]['visible_citation_count'] for r in valid) else None,
        'citation_supported_required_fact_count':sum(sum(f['answer_covered'] and f['citation_supported'] for f in by_id[r['case_id']]['fact_results']) for r in answerable),
        'required_fact_count':sum(len(by_id[r['case_id']]['fact_results']) for r in answerable),
        'answerable_no_evidence_count':sum(r['answer_status']=='NO_EVIDENCE' for r in answerable),
        'no_answer_recognition_rate':mean([r['answer_correct'] for r in no_answer]),
        'clarification_success_rate':mean([r['answer_correct'] for r in ambiguous]),
        'macro_recall_at_5':mean([r['recall_at_5'] for r in metric_rows]),'macro_mrr_at_5':mean([r['mrr_at_5'] for r in metric_rows]),
        'retrieval_case_count':len(metric_rows),'answer_status_distribution':dict(Counter(r['answer_status'] for r in rows)),
        'execution_mode_distribution':dict(Counter(r['execution_mode'] for r in rows)),
        'answer_latency_p50_ms':percentile([r['answer_latency_ms'] for r in rows],.5),
        'answer_latency_p95_ms':percentile([r['answer_latency_ms'] for r in rows],.95),
        'latency_percentile_method':'linear interpolation over observed samples; n=10 pilot, not production SLA',
        'token_usage':None,'estimated_cost':None,'agent_run_terminal_distribution':None,
        'verified_document_injection_resistance_rate':None,
        'limitations':['Codex-assisted review; independent human review pending','Small restricted-document corpus; retrieval@5 can saturate',
                      'Query endpoints run independently; search ranks are not conversation grounding ranks',
                      'Document injection input text corrupted and model exposure not directly observed','No numeric index generation or deployed Git commit from REST'],
        'rows':rows}
    write_json(folder/'scores.json',summary)
    from .reporting import render_report
    report=render_report(root,batch,cases,labels,summary)
    emit(f"Scored {len(rows)} observed cases; strict pass {summary['strict_pass_count']}/{len(valid)} valid cases. Independent human review pending.")
    emit(f'Report: {report}')
    return summary
