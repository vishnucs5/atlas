"""Standard built-in specialist skills for the ATLAS ecosystem."""

import ast
from typing import Any

from atlas_skills.base import BaseSkill, SkillContext
from atlas_skills.models import SkillCapability, SkillManifest, SkillParameter


class CodeLinterSkill(BaseSkill):
    """Specialist skill that audits Python source code for AST syntax correctness and structure."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="com.atlas.skill.code-linter",
            name="Python Code Linter",
            version="1.0.0",
            description="Inspects Python code for syntax correctness, complexity, and AST structure.",
            capabilities=[SkillCapability.CODE, SkillCapability.QUALITY_ASSURANCE],
            inputs={
                "source_code": SkillParameter(
                    name="source_code",
                    type_name="string",
                    description="Python source code to lint",
                    required=True,
                ),
                "filename": SkillParameter(
                    name="filename",
                    type_name="string",
                    description="Filename being analyzed",
                    required=False,
                    default_value="<string>",
                ),
            },
            outputs={
                "is_valid": SkillParameter(name="is_valid", type_name="boolean"),
                "syntax_errors": SkillParameter(name="syntax_errors", type_name="list"),
                "ast_nodes": SkillParameter(name="ast_nodes", type_name="integer"),
            },
        )
        super().__init__(manifest)

    async def execute(self, context: SkillContext, **inputs: Any) -> dict[str, Any]:
        source = inputs["source_code"]
        filename = inputs.get("filename", "<string>")
        context.logger.info(
            "Linting source code for '%s' (length: %d chars)", filename, len(source)
        )

        syntax_errors: list[str] = []
        node_count = 0

        try:
            tree = ast.parse(source, filename=filename)
            node_count = sum(1 for _ in ast.walk(tree))
            context.logger.info("AST parsed successfully with %d nodes.", node_count)
        except SyntaxError as syn_err:
            context.logger.error(
                "Syntax error detected: %s (line %d)", syn_err.msg, syn_err.lineno or 0
            )
            syntax_errors.append(f"Line {syn_err.lineno}: {syn_err.msg}")

        return {
            "is_valid": len(syntax_errors) == 0,
            "syntax_errors": syntax_errors,
            "ast_nodes": node_count,
        }


class DataAnalysisSkill(BaseSkill):
    """Specialist skill that computes statistical metrics over numerical datasets."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="com.atlas.skill.data-analysis",
            name="Statistical Data Analysis",
            version="1.0.0",
            description="Computes summary statistics including sum, mean, min, and max.",
            capabilities=[SkillCapability.DATA_ANALYSIS],
            inputs={
                "data": SkillParameter(
                    name="data",
                    type_name="list",
                    description="Numerical dataset",
                    required=True,
                )
            },
            outputs={
                "count": SkillParameter(name="count", type_name="integer"),
                "sum": SkillParameter(name="sum", type_name="float"),
                "mean": SkillParameter(name="mean", type_name="float"),
                "min": SkillParameter(name="min", type_name="float"),
                "max": SkillParameter(name="max", type_name="float"),
            },
        )
        super().__init__(manifest)

    async def execute(self, context: SkillContext, **inputs: Any) -> dict[str, Any]:
        data = inputs["data"]
        context.logger.info("Analyzing dataset of %d items", len(data))

        if not data:
            return {"count": 0, "sum": 0.0, "mean": 0.0, "min": 0.0, "max": 0.0}

        num_list = [float(x) for x in data]
        total = sum(num_list)
        return {
            "count": len(num_list),
            "sum": total,
            "mean": total / len(num_list),
            "min": min(num_list),
            "max": max(num_list),
        }


class TextSummarizerSkill(BaseSkill):
    """Specialist skill that analyzes unstructured text documents."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="com.atlas.skill.text-summarizer",
            name="Text Summarizer",
            version="1.0.0",
            description="Extracts key summary lines, word counts, and structural statistics.",
            capabilities=[SkillCapability.TEXT_PROCESSING, SkillCapability.RESEARCH],
            inputs={
                "text": SkillParameter(
                    name="text",
                    type_name="string",
                    description="Source text to summarize",
                    required=True,
                ),
                "max_sentences": SkillParameter(
                    name="max_sentences",
                    type_name="integer",
                    description="Maximum sentences to extract",
                    required=False,
                    default_value=3,
                ),
            },
            outputs={
                "word_count": SkillParameter(name="word_count", type_name="integer"),
                "summary": SkillParameter(name="summary", type_name="string"),
            },
        )
        super().__init__(manifest)

    async def execute(self, context: SkillContext, **inputs: Any) -> dict[str, Any]:
        text = inputs["text"]
        max_sentences = inputs.get("max_sentences", 3)
        context.logger.info("Summarizing text (%d words)", len(text.split()))

        sentences = [s.strip() for s in text.split(".") if s.strip()]
        selected = sentences[:max_sentences]
        summary = ". ".join(selected) + ("." if selected else "")

        return {
            "word_count": len(text.split()),
            "summary": summary,
        }
