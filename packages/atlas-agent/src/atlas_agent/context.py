"""Context window management, DOM summarization, and prompt injection defense."""

from typing import Any

from atlas_core.contracts.model import ModelMessage
from atlas_core.contracts.observation import Observation
from atlas_core.contracts.task import Task
from pydantic import BaseModel, ConfigDict, Field


class DOMSummarizer:
    """Condenses verbose HTML/DOM structures into compact interactive element representations."""

    def summarize(
        self,
        dom: str | dict[str, Any] | None = None,
        interactive_elements: list[dict[str, Any]] | None = None,
        max_length: int = 4000,
    ) -> str:
        """Format visible interactive elements into compact, token-efficient markup."""
        if interactive_elements:
            lines = []
            for el in interactive_elements:
                role = el.get("role") or el.get("tag", "element")
                attrs = el.get("attributes", {})
                text = (el.get("text") or "").strip()
                el_id = attrs.get("id", "")
                id_str = f" #{el_id}" if el_id else ""

                if role in ("button", "link") or el.get("tag") in ("button", "a"):
                    if role == "link" or el.get("tag") == "a":
                        href = attrs.get("href", "")
                        lines.append(f"[link '{text}' href='{href}']")
                    else:
                        lines.append(f"[button{id_str} '{text}']")
                elif role in ("textbox", "combobox") or el.get("tag") in (
                    "input",
                    "textarea",
                    "select",
                ):
                    input_type = attrs.get("type", "text")
                    val = attrs.get("value", "")
                    lines.append(f"[{role}{id_str} type='{input_type}' value='{val}']")
                else:
                    lines.append(f"[{role}{id_str} '{text}']")
            return "\n".join(lines)[:max_length]

        if isinstance(dom, str):
            # Fallback simple string slice
            return dom[:max_length]
        return ""


def demarcate_untrusted_content(
    content: str,
    source: str = "web_page",
    origin: str | None = None,
) -> str:
    """Enclose external, untrusted content inside strict demarcated boundary tags."""
    origin_attr = f' origin="{origin}"' if origin else ""
    return (
        f'<untrusted_external_content source="{source}"{origin_attr}>\n'
        f"{content.strip()}\n"
        f"</untrusted_external_content>"
    )


class TaskMemory(BaseModel):
    """Structured memory store preserving intermediate notes, variables, and facts."""

    model_config = ConfigDict(validate_assignment=True)

    scratchpad: list[str] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)
    learned_facts: list[str] = Field(default_factory=list)
    schema_version: str = "1.0"

    def add_note(self, note: str) -> None:
        self.scratchpad.append(note)

    def set_variable(self, key: str, value: Any) -> None:
        self.variables[key] = value

    def get_variable(self, key: str, default: Any = None) -> Any:
        return self.variables.get(key, default)

    def add_fact(self, fact: str) -> None:
        self.learned_facts.append(fact)

    def format_memory(self) -> str:
        """Produce a formatted markdown block representing current memory."""
        sections = []
        if self.scratchpad:
            notes = "\n".join(f"- {n}" for n in self.scratchpad)
            sections.append(f"Notes:\n{notes}")
        if self.variables:
            vars_str = "\n".join(f"{k}: {v}" for k, v in self.variables.items())
            sections.append(f"Variables:\n{vars_str}")
        if self.learned_facts:
            facts = "\n".join(f"- {f}" for f in self.learned_facts)
            sections.append(f"Learned Facts:\n{facts}")
        return "\n\n".join(sections)


class ContextManager:
    """Manages conversational history, observation summarization, and prompt assembly."""

    def __init__(self, max_messages: int = 30) -> None:
        self.max_messages = max_messages
        self._history: list[ModelMessage] = []
        self._dom_summarizer = DOMSummarizer()

    def add_message(self, message: ModelMessage) -> None:
        """Append a message and trim to sliding window ceiling."""
        self._history.append(message)
        if len(self._history) > self.max_messages:
            self._history = self._history[-self.max_messages :]

    def get_messages(self) -> list[ModelMessage]:
        return list(self._history)

    def build_prompt_context(
        self,
        task: Task,
        current_observation: Observation | None = None,
        memory: TaskMemory | None = None,
    ) -> list[ModelMessage]:
        """Assemble structured context including task instructions, memory, and observations."""
        parts = [f"Goal / Task Objective: {task.objective}"]

        if memory:
            mem_str = memory.format_memory()
            if mem_str:
                parts.append(f"Task Memory & Scratchpad:\n{mem_str}")

        if current_observation:
            obs_lines = []
            url = getattr(current_observation, "url", None) or current_observation.metadata.get(
                "url"
            )
            title = current_observation.window_title or current_observation.metadata.get("title")
            interactive_elements = getattr(
                current_observation, "interactive_elements", None
            ) or current_observation.metadata.get("interactive_elements")

            if url:
                obs_lines.append(f"Current URL: {url}")
            if title:
                obs_lines.append(f"Page Title: {title}")

            dom_summary = self._dom_summarizer.summarize(
                dom=current_observation.dom_snapshot,
                interactive_elements=interactive_elements,
            )
            if dom_summary:
                demarcated = demarcate_untrusted_content(
                    dom_summary,
                    source="browser_dom",
                    origin=url,
                )
                obs_lines.append(f"Visible Interactive Elements:\n{demarcated}")

            parts.append("Current Environment State:\n" + "\n".join(obs_lines))

        user_content = "\n\n".join(parts)
        turn_message = ModelMessage(role="user", content=user_content)

        return [*self._history, turn_message]
