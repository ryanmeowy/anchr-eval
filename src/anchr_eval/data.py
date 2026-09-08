from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write('\n')
    temp.replace(path)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dataset(root):
    base = root / 'datasets/anchr-seed-v1'
    corpus = read_json(base / 'corpus.json')
    cases = [json.loads(line) for line in (base / 'cases.jsonl').read_text().splitlines() if line.strip()]
    if len({c['id'] for c in cases}) != len(cases):
        raise ValueError('Duplicate question IDs.')
    for doc in corpus['documents']:
        if sha256(root / doc['pdf_path']) != doc['pdf_sha256']:
            raise ValueError(f"Document hash mismatch: {doc['doc_id']}")
    return corpus, cases
