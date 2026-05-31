from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_pr_review.context import RetrievedContext
from ai_pr_review.diff_parser import DiffChunk, FileClassification
from ai_pr_review.comments import build_comment_context
from ai_pr_review.llm import (
    LLMError,
    _call_structured,
    _parse_json_object,
    analyze_chunks,
    verify_high_risk_findings,
)
from ai_pr_review.schemas import Finding


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
    def __init__(
        self,
        *,
        content,
        raise_with_response_format: bool = False,
    ) -> None:
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


class FakeChatChoiceTextCompletions:
    def __init__(self, *, text: str) -> None:
        self.text = text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        choice = SimpleNamespace(text=self.text)
        return SimpleNamespace(choices=[choice])


class FakeChatOutputTextCompletions:
    def __init__(self, *, output_text: str) -> None:
        self.output_text = output_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.output_text)


class FakeChatDictCompletions:
    def __init__(self, *, payload: dict) -> None:
        self.payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


class FakeChatRawStringCompletions:
    def __init__(self, *, text: str) -> None:
        self.text = text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.text


class FakeClient:
    def __init__(self, responses: FakeResponses, chat) -> None:
        self.responses = responses
        self.chat = SimpleNamespace(completions=chat)


def test_call_structured_auto_falls_back_to_chat_when_responses_fails() -> None:
    client = FakeClient(
        responses=FakeResponses(exc=RuntimeError("responses unsupported")),
        chat=FakeChatCompletions(content='{"summary":"ok","findings":[]}'),
    )

    result = _call_structured(
        client,
        model="test-model",
        system="system",
        user="user",
        api_mode="auto",
    )

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
    assert any("不支持 response_format" in item for item in result.limitations)


def test_call_structured_chat_accepts_content_parts_list() -> None:
    client = FakeClient(
        responses=FakeResponses(text='{"summary":"unused","findings":[]}'),
        chat=FakeChatCompletions(
            content=[
                {
                    "type": "text",
                    "text": '{"summary":"ok","findings":[]}',
                }
            ]
        ),
    )

    result = _call_structured(
        client,
        model="test-model",
        system="system",
        user="user",
        api_mode="chat",
    )

    assert result.payload == {"summary": "ok", "findings": []}


def test_call_structured_chat_accepts_choice_text() -> None:
    client = FakeClient(
        responses=FakeResponses(text='{"summary":"unused","findings":[]}'),
        chat=FakeChatChoiceTextCompletions(text='{"summary":"ok","findings":[]}'),
    )

    result = _call_structured(
        client,
        model="test-model",
        system="system",
        user="user",
        api_mode="chat",
    )

    assert result.payload == {"summary": "ok", "findings": []}


def test_call_structured_chat_accepts_response_output_text() -> None:
    client = FakeClient(
        responses=FakeResponses(text='{"summary":"unused","findings":[]}'),
        chat=FakeChatOutputTextCompletions(output_text='{"summary":"ok","findings":[]}'),
    )

    result = _call_structured(
        client,
        model="test-model",
        system="system",
        user="user",
        api_mode="chat",
    )

    assert result.payload == {"summary": "ok", "findings": []}


def test_call_structured_chat_accepts_dict_response() -> None:
    client = FakeClient(
        responses=FakeResponses(text='{"summary":"unused","findings":[]}'),
        chat=FakeChatDictCompletions(
            payload={
                "choices": [
                    {
                        "message": {
                            "content": '{"summary":"ok","findings":[]}',
                        }
                    }
                ]
            }
        ),
    )

    result = _call_structured(
        client,
        model="test-model",
        system="system",
        user="user",
        api_mode="chat",
    )

    assert result.payload == {"summary": "ok", "findings": []}


def test_call_structured_chat_accepts_raw_string_response() -> None:
    client = FakeClient(
        responses=FakeResponses(text='{"summary":"unused","findings":[]}'),
        chat=FakeChatRawStringCompletions(text='{"summary":"ok","findings":[]}'),
    )

    result = _call_structured(
        client,
        model="test-model",
        system="system",
        user="user",
        api_mode="chat",
    )

    assert result.payload == {"summary": "ok", "findings": []}


def test_parse_json_object_accepts_markdown_fenced_json() -> None:
    payload = _parse_json_object(
        '模型输出如下：\n```json\n{"summary":"ok","findings":[]}\n```\n请查收。'
    )

    assert payload == {"summary": "ok", "findings": []}


def test_parse_json_object_reports_html_response_as_base_url_error() -> None:
    with pytest.raises(LLMError, match="OPENAI_BASE_URL"):
        _parse_json_object("<!doctype html><html><head><title>One API</title></head></html>")


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


def test_analyze_chunks_collects_findings_and_call_limitations(monkeypatch) -> None:
    client = FakeClient(
        responses=FakeResponses(exc=RuntimeError("responses unsupported")),
        chat=FakeChatCompletions(
            content="""
```json
{
  "summary": "found issue",
  "findings": [
    {
      "path": "src/app.py",
      "line": 2,
      "severity": "medium",
      "category": "logic",
      "confidence": 0.7,
      "evidence": ["+return value"],
      "problem": "示例问题",
      "suggestion": "修复示例问题",
      "blocking": false
    }
  ]
}
```
"""
        ),
    )
    monkeypatch.setattr("ai_pr_review.llm._create_client", lambda **_: client)
    chunk = DiffChunk(
        path="src/app.py",
        patch="+return value",
        old_start=1,
        new_start=1,
        old_length=1,
        new_length=1,
        classification=FileClassification(path="src/app.py"),
    )

    findings, limitations = analyze_chunks(
        [chunk],
        pr_summary="summary",
        context=RetrievedContext(),
        comments_summary="",
        model="test-model",
        api_key="test-key",
        api_mode="auto",
    )

    assert len(findings) == 1
    assert findings[0].path == "src/app.py"
    assert findings[0].source == "llm"
    assert any("降级到 Chat Completions" in item for item in limitations)


def test_analyze_chunks_can_be_disabled() -> None:
    chunk = DiffChunk(
        path="src/app.py",
        patch="+return value",
        old_start=1,
        new_start=1,
        old_length=1,
        new_length=1,
        classification=FileClassification(path="src/app.py"),
    )

    findings, limitations = analyze_chunks(
        [chunk],
        pr_summary="summary",
        context=RetrievedContext(),
        comments_summary="",
        model="test-model",
        api_key="test-key",
        enabled=False,
    )

    assert findings == []
    assert limitations == ["已按配置跳过 LLM 分析，仅输出规则引擎结果"]


def test_analyze_chunks_respects_max_chunks(monkeypatch) -> None:
    client = FakeClient(
        responses=FakeResponses(text='{"summary":"ok","findings":[]}'),
        chat=FakeChatCompletions(content='{"summary":"unused","findings":[]}'),
    )
    monkeypatch.setattr("ai_pr_review.llm._create_client", lambda **_: client)
    chunks = [
        DiffChunk(
            path=f"src/app_{index}.py",
            patch="+return value",
            old_start=1,
            new_start=1,
            old_length=1,
            new_length=1,
            classification=FileClassification(path=f"src/app_{index}.py"),
        )
        for index in range(3)
    ]

    findings, limitations = analyze_chunks(
        chunks,
        pr_summary="summary",
        context=RetrievedContext(),
        comments_summary="",
        model="test-model",
        api_key="test-key",
        max_chunks=1,
    )

    assert findings == []
    assert len(client.responses.calls) == 1
    assert limitations == ["LLM 分析已限制为前 1 个 chunk，跳过 2 个 chunk"]


def test_analyze_chunks_drops_findings_for_other_paths(monkeypatch) -> None:
    client = FakeClient(
        responses=FakeResponses(
            text="""
{
  "summary": "mixed",
  "findings": [
    {
      "path": "src/app.py",
      "line": 2,
      "severity": "low",
      "category": "logic",
      "confidence": 0.7,
      "evidence": ["+return value"],
      "problem": "当前文件问题",
      "suggestion": "修复当前文件问题",
      "blocking": false
    },
    {
      "path": "tests/ (推测)",
      "line": null,
      "severity": "medium",
      "category": "test",
      "confidence": 0.8,
      "evidence": ["PR 描述"],
      "problem": "推测路径问题",
      "suggestion": "补测试",
      "blocking": false
    }
  ]
}
"""
        ),
        chat=FakeChatCompletions(content='{"summary":"unused","findings":[]}'),
    )
    monkeypatch.setattr("ai_pr_review.llm._create_client", lambda **_: client)
    chunk = DiffChunk(
        path="src/app.py",
        patch="+return value",
        old_start=1,
        new_start=1,
        old_length=1,
        new_length=1,
        classification=FileClassification(path="src/app.py"),
    )

    findings, limitations = analyze_chunks(
        [chunk],
        pr_summary="summary",
        context=RetrievedContext(),
        comments_summary="",
        model="test-model",
        api_key="test-key",
        api_mode="responses",
    )

    assert [finding.path for finding in findings] == ["src/app.py"]
    assert any("非当前文件" in item for item in limitations)


def test_analyze_chunks_drops_comment_derived_findings(monkeypatch) -> None:
    client = FakeClient(
        responses=FakeResponses(
            text="""
{
  "summary": "comment-derived",
  "findings": [
    {
      "path": "src/app.py",
      "line": null,
      "severity": "medium",
      "category": "compatibility",
      "confidence": 0.9,
      "evidence": ["Copilot 行内评论指出，其他接口可能仍返回旧错误文案"],
      "problem": "Copilot 提到跨接口不一致",
      "suggestion": "根据评论更新其他接口",
      "blocking": false
    }
  ]
}
"""
        ),
        chat=FakeChatCompletions(content='{"summary":"unused","findings":[]}'),
    )
    monkeypatch.setattr("ai_pr_review.llm._create_client", lambda **_: client)
    chunk = DiffChunk(
        path="src/app.py",
        patch='-raise HTTPException(status_code=404, detail="user not found")\n+raise HTTPException(status_code=404, detail="User not found")',
        old_start=1,
        new_start=1,
        old_length=1,
        new_length=1,
        classification=FileClassification(path="src/app.py"),
    )

    findings, limitations = analyze_chunks(
        [chunk],
        pr_summary="summary",
        context=RetrievedContext(),
        comments_summary="用户接口之外还有旧文案",
        model="test-model",
        api_key="test-key",
        api_mode="responses",
    )

    assert findings == []
    assert any("已有评论" in item for item in limitations)


def test_analyze_chunks_drops_review_comment_marker_findings(monkeypatch) -> None:
    client = FakeClient(
        responses=FakeResponses(
            text="""
{
  "summary": "comment-derived",
  "findings": [
    {
      "path": "src/app.py",
      "line": null,
      "severity": "medium",
      "category": "compatibility",
      "confidence": 0.85,
      "evidence": ["review_comment: other endpoints still return user not found"],
      "problem": "评论指出其他接口文案不一致",
      "suggestion": "统一所有接口文案",
      "blocking": false
    }
  ]
}
"""
        ),
        chat=FakeChatCompletions(content='{"summary":"unused","findings":[]}'),
    )
    monkeypatch.setattr("ai_pr_review.llm._create_client", lambda **_: client)
    chunk = DiffChunk(
        path="src/app.py",
        patch='-detail="user not found"\n+detail="User not found"',
        old_start=1,
        new_start=1,
        old_length=1,
        new_length=1,
        classification=FileClassification(path="src/app.py"),
    )

    findings, limitations = analyze_chunks(
        [chunk],
        pr_summary="summary",
        context=RetrievedContext(),
        comments_summary="",
        model="test-model",
        api_key="test-key",
        api_mode="responses",
    )

    assert findings == []
    assert any("已有评论" in item for item in limitations)


def test_analyze_chunks_uses_path_specific_comment_context(monkeypatch) -> None:
    chat = FakeChatCompletions(content='{"summary":"ok","findings":[]}')
    client = FakeClient(
        responses=FakeResponses(text='{"summary":"unused","findings":[]}'),
        chat=chat,
    )
    monkeypatch.setattr("ai_pr_review.llm._create_client", lambda **_: client)
    comment_context = build_comment_context(
        issue_comments=[],
        review_comments=[
            {
                "user": {"login": "Copilot"},
                "path": "src/app.py",
                "body": "app comment",
            },
            {
                "user": {"login": "Copilot"},
                "path": "src/db.py",
                "body": "db comment",
            },
        ],
        pull_reviews=[],
    )
    chunk = DiffChunk(
        path="src/app.py",
        patch="+return value",
        old_start=1,
        new_start=1,
        old_length=1,
        new_length=1,
        classification=FileClassification(path="src/app.py"),
    )

    findings, limitations = analyze_chunks(
        [chunk],
        pr_summary="summary",
        context=RetrievedContext(),
        comments_summary=comment_context.as_prompt_text(),
        comment_context=comment_context,
        model="test-model",
        api_key="test-key",
        api_mode="chat",
    )

    prompt = chat.calls[0]["messages"][1]["content"]
    assert findings == []
    assert limitations == []
    assert "app comment" in prompt
    assert "db comment" not in prompt


def test_analyze_chunks_reports_schema_errors_without_pydantic_details(monkeypatch) -> None:
    client = FakeClient(
        responses=FakeResponses(
            text="""
{
  "summary": "invalid",
  "findings": [
    {
      "path": null,
      "line": 2,
      "severity": "medium",
      "category": "logic",
      "confidence": 0.7,
      "evidence": ["+return value"],
      "problem": "路径类型错误",
      "suggestion": "修复路径类型",
      "blocking": false
    }
  ]
}
"""
        ),
        chat=FakeChatCompletions(content='{"summary":"unused","findings":[]}'),
    )
    monkeypatch.setattr("ai_pr_review.llm._create_client", lambda **_: client)
    chunk = DiffChunk(
        path="src/app.py",
        patch="+return value",
        old_start=1,
        new_start=1,
        old_length=1,
        new_length=1,
        classification=FileClassification(path="src/app.py"),
    )

    findings, limitations = analyze_chunks(
        [chunk],
        pr_summary="summary",
        context=RetrievedContext(),
        comments_summary="",
        model="test-model",
        api_key="test-key",
        api_mode="responses",
    )

    assert findings == []
    assert limitations == ["LLM 返回结构不符合 schema，已跳过该 chunk"]
    assert "pydantic" not in limitations[0].lower()


def test_verify_high_risk_preserves_rule_findings_when_verifier_omits_them(monkeypatch) -> None:
    client = FakeClient(
        responses=FakeResponses(text='{"summary":"verified","findings":[]}'),
        chat=FakeChatCompletions(content='{"summary":"verified","findings":[]}'),
    )
    monkeypatch.setattr("ai_pr_review.llm._create_client", lambda **_: client)
    rule_finding = Finding(
        path="src/app/main.py",
        line=7,
        severity="high",
        category="security",
        confidence=0.82,
        evidence=["-from .auth import require_admin"],
        problem="鉴权检查被删除",
        suggestion="恢复权限校验",
        blocking=True,
        source="rule",
        rule_id="auth_check_removed",
    )

    findings, limitations = verify_high_risk_findings(
        [rule_finding],
        context=RetrievedContext(),
        model="test-model",
        api_key="test-key",
        api_mode="responses",
    )

    assert findings == [rule_finding]
    assert limitations == []


def test_verify_high_risk_can_be_disabled() -> None:
    rule_finding = Finding(
        path="src/app/main.py",
        line=7,
        severity="high",
        category="security",
        confidence=0.82,
        evidence=["-from .auth import require_admin"],
        problem="鉴权检查被删除",
        suggestion="恢复权限校验",
        blocking=True,
        source="rule",
        rule_id="auth_check_removed",
    )

    findings, limitations = verify_high_risk_findings(
        [rule_finding],
        context=RetrievedContext(),
        model="test-model",
        api_key="test-key",
        enabled=False,
    )

    assert findings == [rule_finding]
    assert limitations == []
