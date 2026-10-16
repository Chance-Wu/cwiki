"""客户端分页与非幂等更新投递契约测试。"""

import json

import httpx
import pytest

from adapters.qoder.client import CwikiClient, MemoryUpdateUncertainError


@pytest.fixture
async def client():
    instance = CwikiClient("http://test")
    yield instance
    await instance.close()


def mock_transport(client, handler):
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "error_type", [httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ConnectError]
)
async def test_update_transport_error_is_uncertain_and_never_retried(client, error_type):
    applied_versions = []
    original_errors = []

    def handler(request):
        assert request.method == "PATCH"
        applied_versions.append(json.loads(request.content))
        error = error_type("lost response", request=request)
        original_errors.append(error)
        raise error

    mock_transport(client, handler)
    with pytest.raises(MemoryUpdateUncertainError, match="可能已生效.*未自动重试") as caught:
        await client.update_memory("memory-1", content="new content")
    assert len(applied_versions) == 1
    assert caught.value.memory_id == "memory-1"
    assert caught.value.__cause__ is original_errors[0]


@pytest.mark.parametrize("status_code", [500, 502, 503, 504, 429, 409, 422])
async def test_update_status_errors_never_retried(client, status_code):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status_code, json={"detail": "write error"})

    mock_transport(client, handler)
    expected_error = MemoryUpdateUncertainError if status_code >= 500 else httpx.HTTPStatusError
    with pytest.raises(expected_error) as caught:
        await client.update_memory("memory-1", content="new content")
    assert len(requests) == 1
    original = caught.value.__cause__ if status_code >= 500 else caught.value
    assert original.response.status_code == status_code


async def test_invalid_update_response_is_uncertain(client):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text="response interrupted")

    mock_transport(client, handler)
    with pytest.raises(MemoryUpdateUncertainError):
        await client.update_memory("memory-1", confidence=0.8)
    assert len(requests) == 1


@pytest.mark.parametrize("expected_version", [None, 0, 3])
async def test_expected_version_only_forwarded_when_provided(client, expected_version):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "memory-1"})

    mock_transport(client, handler)
    result = await client.update_memory(
        "memory-1", confidence=0.0, expected_version=expected_version
    )
    expected_body = {"confidence": 0.0}
    if expected_version is not None:
        expected_body["expected_version"] = expected_version
    assert requests == [expected_body]
    assert result == {"id": "memory-1"}
