"""Small REST client; never retries mutations or follows authenticated redirects."""
from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx


class ApiError(RuntimeError):
    def __init__(self, message, *, status=None, code=None):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass
class Config:
    base_url: str
    token: str = field(repr=False)

    @classmethod
    def load(cls, root: Path):
        values = {}
        path = root / '.env'
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    values[key.strip()] = value.strip().strip('"').strip("'")
        base = os.getenv('ANCHR_BASE_URL', values.get('ANCHR_BASE_URL', '')).rstrip('/')
        token = os.getenv('ANCHR_ACCESS_TOKEN', values.get('ANCHR_ACCESS_TOKEN', ''))
        parsed = urlsplit(base)
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ApiError('Invalid ANCHR_BASE_URL.')
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')):
            raise ApiError('Remote API connections require HTTPS.')
        if not token:
            raise ApiError('Set ANCHR_ACCESS_TOKEN in .env or the environment.')
        return cls(base, token)


class AnchrClient:
    def __init__(self, config: Config, *, transport=None):
        self.config = config
        self.http = httpx.Client(base_url=config.base_url, headers={
            'X-Access-Token': config.token, 'User-Agent': 'anchr-eval/0.1', 'Accept': 'application/json'},
            timeout=httpx.Timeout(180, connect=20), follow_redirects=False, transport=transport)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.http.close()

    def request(self, method, path, **kwargs):
        if not path.startswith('/api/v1/') or '://' in path:
            raise ApiError('Only relative Anchr API paths are accepted.')
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            # Exception internals may contain request metadata. Keep public errors minimal.
            raise ApiError(f'{method} {path}: {type(exc).__name__}; outcome may be unknown, no automatic retry.') from None
        try:
            payload = response.json()
        except ValueError:
            raise ApiError(f'{method} {path}: HTTP {response.status_code}, non-JSON gateway response.', status=response.status_code) from None
        if not isinstance(payload, dict):
            raise ApiError(f'{method} {path}: invalid API envelope.')
        code = payload.get('code')
        if not response.is_success or not isinstance(code, int) or not 200 <= code < 300:
            error_code = str(payload.get('errorCode') or code or 'UNKNOWN').replace(self.config.token, '[REDACTED]')
            raise ApiError(f'{method} {path}: HTTP {response.status_code}, {error_code}', status=response.status_code, code=error_code)
        return payload.get('data')

    def get(self, path, **kwargs):
        return self.request('GET', path, **kwargs)

    def post(self, path, payload):
        return self.request('POST', path, json=payload)
