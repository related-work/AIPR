from __future__ import annotations

from ai_pr_review.context import RetrievedContext
from ai_pr_review.diff_parser import DiffChunk


REVIEW_SYSTEM_PROMPT = """你是严谨的代码评审助手。只基于提供的 PR diff 和上下文判断。
不要报告纯风格问题，除非它会造成可维护性或行为风险。
没有明确证据时，不要生成 finding。
如果问题不确定，降低 confidence，并把 blocking 设为 false。
低置信度问题不能阻塞合并。
每个 finding 必须包含 path、line、severity、category、confidence、evidence、problem、suggestion、blocking。
优先识别逻辑错误、安全风险、性能问题、并发/事务问题、API 兼容性、测试缺失、边界条件遗漏。
不要臆测没有提供的仓库事实。"""


VERIFY_SYSTEM_PROMPT = """你是代码评审问题复核器。你的任务是删除不可靠 finding，而不是制造更多问题。
保留的问题必须有具体位置或文件级定位、明确证据、可信失败路径和可执行建议。
删除无证据、重复、纯风格、纯猜测或已被上下文否定的问题。
低置信度问题不能阻塞合并。"""


def build_chunk_prompt(
    *,
    pr_summary: str,
    chunk: DiffChunk,
    context: RetrievedContext,
    comments_summary: str,
) -> str:
    return f"""PR 信息：
{pr_summary}

文件：
{chunk.path}

Diff：
```diff
{chunk.patch}
```

相关上下文：
{context.as_prompt_text()}

已有评论摘要：
{comments_summary or "无"}

请输出结构化 JSON。只报告有证据、对 Review 有实际价值的问题。"""


def build_verify_prompt(candidate_findings_json: str, context: RetrievedContext) -> str:
    return f"""以下是候选问题。请只做复核：
1. 判断证据是否充分。
2. 判断问题是否真实可能发生。
3. 判断 severity、confidence、blocking 是否过高。
4. 删除纯猜测、重复、风格类或已被上下文否定的问题。

候选问题：
{candidate_findings_json}

补充上下文：
{context.as_prompt_text()}"""


CHUNK_ANALYSIS_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "findings"],
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "path",
                    "line",
                    "severity",
                    "category",
                    "confidence",
                    "evidence",
                    "problem",
                    "suggestion",
                    "blocking",
                ],
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": ["integer", "null"]},
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low"],
                    },
                    "category": {
                        "type": "string",
                        "enum": [
                            "logic",
                            "security",
                            "performance",
                            "concurrency",
                            "compatibility",
                            "test",
                            "maintainability",
                            "edge_case",
                        ],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "problem": {"type": "string"},
                    "suggestion": {"type": "string"},
                    "blocking": {"type": "boolean"},
                },
            },
        },
    },
}
