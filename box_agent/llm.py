"""Minimal OpenRouter chat-completions client (OpenAI-compatible, tools + images)."""
from __future__ import annotations

import base64
import time
from typing import Callable

import httpx

URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT = 60.0
RETRY_DELAY = 2


class LLMError(Exception):
    pass


class AuthError(LLMError):
    pass


def image_part(png: bytes) -> dict:
    b64 = base64.b64encode(png).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.api_key = api_key
        self.model = model
        self.http = http or httpx.Client(timeout=TIMEOUT)
        self.sleep = sleep

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        body = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "required",
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "X-Title": "Box Agent"}
        last_error = "unknown error"
        for attempt in range(2):
            if attempt:
                self.sleep(RETRY_DELAY)
            try:
                r = self.http.post(URL, json=body, headers=headers, timeout=TIMEOUT)
            except httpx.TransportError as e:
                last_error = f"Network error: {e}"
                continue
            if r.status_code == 401:
                raise AuthError("OpenRouter rejected the API key (401).")
            if r.status_code == 429 or r.status_code >= 500:
                last_error = f"OpenRouter HTTP {r.status_code}: {r.text[:300]}"
                continue
            if r.status_code >= 400:
                raise LLMError(f"OpenRouter HTTP {r.status_code}: {r.text[:300]}")
            try:
                return r.json()["choices"][0]["message"]
            except (ValueError, KeyError, IndexError, TypeError):
                raise LLMError(f"Unexpected OpenRouter response: {r.text[:300]}")
        raise LLMError(last_error)
