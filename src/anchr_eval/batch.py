"""Sequential, resumable batches with persisted per-case intent and no blind repeats."""
from pathlib import Path
import re
import uuid

from .client import ApiError
from .data import dataset,read_json,write_json,sha256,now
from .runner import smoke


def reconcile(entry,root):
    """Read a completed run after interruption; refuse to re-execute unknown writes."""
    path=root/'runs'/entry['run_id']/'run.json'
    if path.exists():
        run=read_json(path)
        if run.get('status')=='response_received':
            entry['status']='response_received'
            entry['record_path']=path.as_posix()
            return True
        raise ApiError(f"{entry['case_id']} has an existing incomplete run; inspect its session before retrying.")
    if entry.get('status')=='started':
        # The runner writes run.json before any evaluation POST. Its absence means no
        # evaluation POST started, provided the persisted directory was not manually removed.
        raise ApiError(f"{entry['case_id']} has persisted start intent but no result. Reconcile before resuming.")
    return False


def run_batch(root,client,name,case_ids=None,reuse_run=None,emit=print):
    if not re.fullmatch(r'[A-Za-z0-9._-]+',name) or name in ('.','..'):
        raise ApiError('Batch name must be a simple directory name.')
    corpus,cases=dataset(root)
    known={c['id'] for c in cases}
    selected=case_ids or [c['id'] for c in cases]
    if len(selected)!=len(set(selected)) or not set(selected)<=known:
        raise ApiError('Unknown or duplicate case IDs.')
    folder=root/'runs'/name
    path=folder/'batch.json'
    data_hash=sha256(root/'datasets/anchr-seed-v1/cases.jsonl')
    if path.exists():
        batch=read_json(path)
        if batch['base_url']!=client.config.base_url or batch['dataset_sha256']!=data_hash or batch['case_ids']!=selected:
            raise ApiError('Existing batch has different server, dataset or cases.')
    else:
        batch={'name':name,'started_at':now(),'base_url':client.config.base_url,'dataset_sha256':data_hash,
               'dataset_version':corpus['dataset_version'],'case_ids':selected,'status':'running','entries':[]}
        reused=None
        if reuse_run:
            p=Path(reuse_run)
            if not p.is_absolute(): p=root/p
            reused=read_json(p/'run.json')
            if reused['case_id'] not in selected or reused['status']!='response_received' or reused['base_url']!=client.config.base_url or reused['dataset_sha256']!=data_hash:
                raise ApiError('Reused run does not match this batch.')
        for cid in selected:
            if reused and cid==reused['case_id']:
                batch['entries'].append({'case_id':cid,'run_id':reused['run_id'],'status':'response_received','reused':True})
            else:
                batch['entries'].append({'case_id':cid,'run_id':f'smoke-{uuid.uuid4()}','status':'pending','reused':False})
        write_json(path,batch)
        if (root/'runs/setup/server-snapshot.json').exists():
            write_json(folder/'server-snapshot.json',read_json(root/'runs/setup/server-snapshot.json'))
    for entry in batch['entries']:
        if entry['status']=='response_received':
            reconcile(entry,root)
            emit(f"Reuse completed: {entry['case_id']}")
            continue
        if reconcile(entry,root):
            write_json(path,batch)
            continue
        entry['status']='started'
        entry['started_at']=now()
        write_json(path,batch)
        emit(f"Start {entry['case_id']}")
        try:
            record=smoke(root,client,entry['case_id'],emit,run_id=entry['run_id'])
        except ApiError as exc:
            entry['status']='needs_reconciliation'
            entry['error']=str(exc)
            batch['status']='needs_reconciliation'
            write_json(path,batch)
            raise
        entry['status']=record['status']
        entry['finished_at']=now()
        write_json(path,batch)
    batch['status']='responses_received'
    batch['finished_at']=now()
    write_json(path,batch)
    emit(f"Batch {name}: {len(batch['entries'])} responses saved, scoring pending.")
    return batch
