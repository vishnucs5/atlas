"""Unit tests verifying Skill SDK contracts, lifecycle hooks, sandboxing, and built-in skills."""

import asyncio
from typing import Any

import pytest
from atlas_skills.base import (
    BaseSkill,
    SkillContext,
)
from atlas_skills.builtins import (
    CodeLinterSkill,
    DataAnalysisSkill,
    TextSummarizerSkill,
)
from atlas_skills.models import (
    SkillManifest,
)


@pytest.mark.asyncio
async def test_code_linter_skill():
    """Verify CodeLinterSkill successfully parses valid Python and flags syntax errors."""
    skill = CodeLinterSkill()
    ctx = SkillContext(task_id="t_lint_1")

    # 1. Valid code
    res_valid = await skill.run(ctx, source_code="def add(a, b):\n    return a + b\n")
    assert res_valid.success is True
    assert res_valid.output["is_valid"] is True
    assert res_valid.output["ast_nodes"] > 0
    assert len(res_valid.output["syntax_errors"]) == 0

    # 2. Syntax error
    res_invalid = await skill.run(ctx, source_code="def broken_syntax(:\n    pass\n")
    assert res_invalid.success is True
    assert res_invalid.output["is_valid"] is False
    assert len(res_invalid.output["syntax_errors"]) == 1
    assert "Line 1" in res_invalid.output["syntax_errors"][0]


@pytest.mark.asyncio
async def test_data_analysis_skill():
    """Verify DataAnalysisSkill computes summary statistics correctly."""
    skill = DataAnalysisSkill()
    ctx = SkillContext(task_id="t_data_1")

    res = await skill.run(ctx, data=[10, 20, 30, 40, 50])
    assert res.success is True
    assert res.output["count"] == 5
    assert res.output["sum"] == 150.0
    assert res.output["mean"] == 30.0
    assert res.output["min"] == 10.0
    assert res.output["max"] == 50.0


@pytest.mark.asyncio
async def test_text_summarizer_skill():
    """Verify TextSummarizerSkill extracts summary and word count."""
    skill = TextSummarizerSkill()
    ctx = SkillContext(task_id="t_sum_1")

    text = "ATLAS is an autonomous system. It manages complex lifecycles. It enforces policy guardrails."
    res = await skill.run(ctx, text=text, max_sentences=2)
    assert res.success is True
    assert res.output["word_count"] > 10
    assert "ATLAS is an autonomous system" in res.output["summary"]


@pytest.mark.asyncio
async def test_skill_input_validation_failure():
    """Verify missing required input results in failed SkillResult."""
    skill = CodeLinterSkill()
    ctx = SkillContext(task_id="t_val_1")

    # Missing "source_code" parameter
    res = await skill.run(ctx)
    assert res.success is False
    assert "Missing required parameter 'source_code'" in res.error


@pytest.mark.asyncio
async def test_skill_cancellation():
    """Verify cancelled context aborts execution cleanly."""
    skill = CodeLinterSkill()
    ctx = SkillContext(task_id="t_cancel_1")
    ctx.cancel()  # Abort before execution

    res = await skill.run(ctx, source_code="x = 1")
    assert res.success is False
    assert "cancelled" in res.error.lower()


@pytest.mark.asyncio
async def test_skill_timeout():
    """Verify execution exceeding manifest timeout is terminated."""

    class SlowSkill(BaseSkill):
        def __init__(self) -> None:
            manifest = SkillManifest(
                skill_id="com.atlas.skill.slow",
                name="Slow Skill",
                timeout_seconds=0.05,  # 50ms timeout
            )
            super().__init__(manifest)

        async def execute(self, context: SkillContext, **inputs: Any) -> dict[str, Any]:
            await asyncio.sleep(0.2)  # Exceeds 50ms
            return {"status": "done"}

    slow = SlowSkill()
    ctx = SkillContext(task_id="t_timeout_1")
    res = await slow.run(ctx)

    assert res.success is False
    assert "timed out" in res.error.lower()
