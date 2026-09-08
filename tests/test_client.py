import httpx
import pytest

from anchr_eval.client import AnchrClient, ApiError, Config


def test_application_failure_in_http_200_is_rejected():
    with AnchrClient(Config('https://example.test', 'secret'), transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={'code':401,'errorCode':'AUTH_TOKEN_INVALID'}))) as client:
        with pytest.raises(ApiError, match='AUTH_TOKEN_INVALID'):
            client.get('/api/v1/auth/validate-token')


def test_redirect_does_not_forward_credentials():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={'Location':'https://other.test/'})
    with AnchrClient(Config('https://example.test', 'secret'), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ApiError):
            client.get('/api/v1/kbs')
    assert len(requests) == 1
    assert requests[0].url.host == 'example.test'


def test_timed_out_mutation_is_not_retried():
    attempts = []
    def handler(request):
        attempts.append(request)
        raise httpx.ReadTimeout('timeout with secret', request=request)
    with AnchrClient(Config('https://example.test', 'secret'), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ApiError) as error:
            client.post('/api/v1/conversations', {})
    assert len(attempts) == 1
    assert 'secret' not in str(error.value)


def test_created_envelope_is_success():
    with AnchrClient(Config('https://example.test', 'secret'), transport=httpx.MockTransport(
        lambda req: httpx.Response(201,json={'code':201,'data':{'taskId':'t1'}}))) as client:
        assert client.post('/api/v1/kbs/k1/ingestion-tasks', {}) == {'taskId':'t1'}


def test_external_url_rejected():
    with AnchrClient(Config('https://example.test', 'secret')) as client:
        with pytest.raises(ApiError):
            client.get('https://other.test/api/v1/kbs')
