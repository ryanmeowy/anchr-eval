"""Resumable seed uploads. Persist intent before remote writes; no destructive cleanup."""
from pathlib import Path
from urllib.parse import urlsplit
import uuid

from .client import ApiError
from .data import dataset, now, read_json, write_json

NAME = 'anchr-eval-seed-v1'
DESCRIPTION = 'anchr-eval managed seed corpus v1; four frozen PDFs; no questions or gold answers.'


def load_state(root, client):
    path = root / 'runs/setup/ingestion.json'
    state = read_json(path) if path.exists() else {
        'base_url':client.config.base_url, 'created_at':now(), 'kb_id':None,
        'client_request_id':f'anchr-eval-{uuid.uuid4()}', 'uploads':{}}
    if state['base_url'] != client.config.base_url:
        raise ApiError('Setup state belongs to another API server.')
    return path, state


def prepare(root, client, emit=print):
    import oss2
    corpus, _ = dataset(root)
    path, state = load_state(root, client)
    auth = client.get('/api/v1/auth/validate-token')
    if not auth.get('valid') or auth.get('role') not in ('ADMIN','USER'):
        raise ApiError('A valid ADMIN or USER token is required for ingestion.')
    if not state['kb_id']:
        result = client.post('/api/v1/kbs/search', {'keyword':NAME,'page':1,'size':100})
        matches = [k for k in result.get('items',[]) if k.get('name')==NAME]
        if len(matches)>1 or (matches and matches[0].get('description') != DESCRIPTION):
            raise ApiError('A conflicting knowledge base name exists; refusing to reuse unrelated data.')
        write_json(path,state)
        kb = matches[0] if matches else client.post('/api/v1/kbs',{'name':NAME,'description':DESCRIPTION})
        state['kb_id']=kb['id']
        write_json(path,state)
        emit(f"Knowledge base ready: {state['kb_id']}")
    else:
        kb=client.get(f"/api/v1/kbs/{state['kb_id']}")
        if kb.get('description') != DESCRIPTION:
            raise ApiError('Managed knowledge base identity changed.')
    if state.get('task_id'):
        return refresh(root,client,emit)
    # Reconcile a potentially accepted create before touching any upload again.
    if state.get('task_submit_started'):
        task=client.get(f"/api/v1/kbs/{state['kb_id']}/ingestion-tasks/by-client-request/{state['client_request_id']}")
        state['task_id']=task['taskId']
        state['task']=task
        write_json(path,state)
        return refresh(root,client,emit)
    credential = client.get('/api/v1/auth/sts')
    raw = credential['endpoint']
    endpoint = urlsplit(raw if '://' in raw else 'https://'+raw)
    if endpoint.scheme != 'https' or not endpoint.hostname or endpoint.username or endpoint.password:
        raise ApiError('Upload endpoint must be a valid HTTPS host.')
    bucket=oss2.Bucket(oss2.StsAuth(credential['accessKeyId'],credential['accessKeySecret'],credential['securityToken']),
                       f'https://{endpoint.netloc}',credential['bucket'],connect_timeout=30)
    for doc in corpus['documents']:
        doc_id=doc['doc_id']
        existing=state['uploads'].get(doc_id)
        if existing and existing['item']['fileHash'] != doc['pdf_sha256']:
            raise ApiError(f'Upload hash changed: {doc_id}')
        if existing and existing.get('uploaded'):
            continue
        local=root/doc['pdf_path']
        prefix=credential['prefix'].strip('/')
        # Credential prefixes may be scoped. Use its prefix and a collision-resistant basename.
        key='/'.join(x for x in [prefix,state['client_request_id']+'-'+local.name] if x)
        item={'fileName':local.name,'title':doc['title'],'fileType':'PDF','mimeType':'application/pdf',
              'sizeBytes':local.stat().st_size,'objectKey':key,'fileHash':doc['pdf_sha256']}
        state['uploads'][doc_id]={'item':item,'uploaded':False}
        write_json(path,state)
        try:
            bucket.put_object_from_file(key,str(local),headers={'Content-Type':'application/pdf'})
        except Exception as exc:
            # SDK exception messages may include signed request details.
            raise ApiError(f'Upload {doc_id} failed: {type(exc).__name__}; local state preserved.') from None
        state['uploads'][doc_id]['uploaded']=True
        write_json(path,state)
        emit(f'Uploaded {doc_id}: {local.name}')
    payload={'clientRequestId':state['client_request_id'],'sourceType':'UPLOAD','dedupeStrategy':'SKIP',
             'items':[state['uploads'][d['doc_id']]['item'] for d in corpus['documents']]}
    state['task_submit_started']=now()
    write_json(path,state)
    task=client.post(f"/api/v1/kbs/{state['kb_id']}/ingestion-tasks",payload)
    state['task_id']=task['taskId']
    state['task']=task
    write_json(path,state)
    emit(f"Ingestion submitted: {task['taskId']} / {task['status']}")
    return state


def refresh(root,client,emit=print):
    path,state=load_state(root,client)
    if not state.get('task_id'):
        raise ApiError('No submitted ingestion task; run ingest first.')
    task=client.get(f"/api/v1/kbs/{state['kb_id']}/ingestion-tasks/{state['task_id']}")
    state['task']=task
    state['checked_at']=now()
    documents=client.get(f"/api/v1/kbs/{state['kb_id']}/documents",params={'page':1,'size':50})
    state['documents']=documents.get('items',[])
    write_json(path,state)
    corpus,_=dataset(root)
    mappings={'base_url':client.config.base_url,'kb_id':state['kb_id'],'task_id':state['task_id'],
              'checked_at':state['checked_at'],'documents':{}}
    for doc in corpus['documents']:
        matches=[a for a in state['documents'] if a.get('fileHash')==doc['pdf_sha256']]
        if len(matches)==1:
            asset=matches[0]
            mappings['documents'][doc['doc_id']]={'asset_id':asset['id'],'kb_id':state['kb_id'],
                'document_sha256':doc['pdf_sha256'],'asset_version_no':asset.get('versionNo'),
                'availability_status':asset.get('availabilityStatus'),'parse_status':asset.get('parseStatus'),
                'index_status':asset.get('indexStatus'),'index_generation':None,'segment_ids':None,
                'error_code':asset.get('errorCode'),'error_message':asset.get('errorMessage')}
    write_json(root/'runs/setup/document-bindings.json',mappings)
    emit(f"Task {task['status']}: success={task['successCount']}, failed={task['failureCount']}, running={task['runningCount']}")
    for item in task.get('items',[]):
        emit(f"  {item['fileName']}: {item['status']} / {item['stage']} / {item.get('errorCode') or '-'}")
    return state


def retry_failed(root,client,emit=print):
    """Explicitly retry failed items of the existing task after its cause is fixed."""
    path,state=load_state(root,client)
    if not state.get('task_id'):
        raise ApiError('No existing ingestion task to retry.')
    task=client.get(f"/api/v1/kbs/{state['kb_id']}/ingestion-tasks/{state['task_id']}")
    if task['status'] not in ('FAILED','PARTIAL_SUCCESS'):
        raise ApiError('Wait until the task is terminal and investigate its cause before retrying.')
    task=client.post(f"/api/v1/kbs/{state['kb_id']}/ingestion-tasks/{state['task_id']}/retry-failed",{})
    state['task']=task
    state['retry_requested_at']=now()
    write_json(path,state)
    emit(f"Retry requested on existing task: {state['task_id']} / {task['status']}")
    return state
