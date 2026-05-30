from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_pr_review.llm import LLMError, _call_structured, _parse_json_object


class FakeResponses:
    def __init__(self, *, text: str | None = None, exc: Exception | None = None) -> None:
        self.text = text
        self.exc = exc
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return SimpleNamespace(output_text=self.text)


class FakeChatCompletions:
    def __init__(self, *, content, raise_with_response_format: bool = False) -> None:
        self.content = content
        self.raise_with_response_format = raise_with_response_format
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_with_response_format and "response_format" in kwargs:
            raise RuntimeError("response_format unsupported")
        message = SimpleNamespace(content=self.content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class FakeClient:
    def __init__(self, responses: FakeResponses, chat: FakeChatCompletions) -> None:
        self.responses = responses
        self.chat = SimpleNamespace(completions=chat)


def test_call_structured_auto_falls_back_to_chat_when_responses_fails() -> None:
    client = FakeClient(
        responses=FakeResponses(exc=RuntimeError("responses unsupported")),
        chat=FakeChatCompletions(content='{"summary":"ok","findings":[]}'),
    )

    result = _call_structured(client, model="test-model", system="system", user="user")

    assert result.payload == {"summary": "ok", "findings": []}
    assert client.responses.calls
    assert client.chat.completions.calls
    assert any("降级到 Chat Completions" in item for item in result.limitations)


def test_call_structured_chat_retries_without_response_format() -> None:
    chat = FakeChatCompletions(
        content='{"summary":"ok","findings":[]}',
        raise_with_response_format=True,
    )
    client = FakeClient(
        responses=FakeResponses(text='{"summary":"unused","findings":[]}'),
        chat=chat,
    )

    result = _call_structured(
        client,
        model="test-model",
        system="system",
        user="user",
        api_mode="chat",
    )

    assert result.payload["summary"] == "ok"
    assert len(chat.calls) == 2
    assert "response_format" in chat.calls[0]
    assert "response_format" not in chat.calls[1]


def test_parse_json_object_accepts_markdown_fenced_json() -> None:
    payload = _parse_json_object('```json\n{"summary":"ok","findings":[]}\n```')

    assert payload == {"summary": "ok", "findings": []}


def test_responses_mode_does_not_fallback_to_chat() -> None:
    client = FakeClient(
        responses=FakeResponses(exc=RuntimeError("responses unsupported")),
        chat=FakeChatCompletions(content='{"summary":"ok","findings":[]}'),
    )

    with pytest.raises(LLMError):
        _call_structured(
            client,
            model="test-model",
            system="system",
            user="user",
            api_mode="responses",
        )

    assert not client.chat.completions.calls
