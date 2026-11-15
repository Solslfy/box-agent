import base64
import json

import httpx
import pytest

from box_agent.llm import AuthError, LLMError, OpenRouterClient, image_part

OK = {"choices": [{"message": {"role": "assistant", "tool_calls": []}}]}


def make(responses):
    """responses: list of int status / dict body / Exception, consumed in order."""
    seen = []
    sleeps = []

    def handler(request):
        seen.append(request)
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        if isinstance(r, int):
            return httpx.Response(r, text="boom")
        return httpx.Response(200, json=r)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenRouterClient("k", "some/model", http=http, sleep=sleeps.append)
    return client, seen, sleeps


def test_success_returns_message_and_sends_headers():
    client, seen, _ = make([OK])
    msg = client.chat([{"role": "user", "content": "hi"}], [{"type": "function"}])
    assert msg == OK["choices"][0]["message"]
    req = seen[0]
    assert str(req.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert req.headers["Authorization"] == "Bearer k"
    assert req.headers["X-Title"] == "Box Agent"
    body = json.loads(req.content)
    assert body["tool_choice"] == "required"
    assert body["model"] == "some/model"


def test_retry_once_on_500_then_success():
    client, seen, sleeps = make([500, OK])
    client.chat([], [])
    assert len(seen) == 2 and sleeps == [2]


def test_retry_on_429():
    client, seen, _ = make([429, OK])
    client.chat([], [])
    assert len(seen) == 2


def test_two_failures_raise():
    client, _, _ = make([500, 500])
    with pytest.raises(LLMError):
        client.chat([], [])


def test_401_raises_auth_no_retry():
    client, seen, _ = make([401, OK])
    with pytest.raises(AuthError):
        client.chat([], [])
    assert len(seen) == 1


def test_other_4xx_no_retry():
    client, seen, _ = make([400, OK])
    with pytest.raises(LLMError):
        client.chat([], [])
    assert len(seen) == 1


def test_transport_error_retried():
    client, seen, _ = make([httpx.ConnectError("down"), OK])
    client.chat([], [])
    assert len(seen) == 2


def test_missing_choices_raises():
    client, _, _ = make([{"error": {"message": "no"}}])
    with pytest.raises(LLMError):
        client.chat([], [])


def test_image_part_prefix():
    part = image_part(b"\x89PNGdata")
    url = part["image_url"]["url"]
    assert part["type"] == "image_url"
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == b"\x89PNGdata"
