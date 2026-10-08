"""Versioned prompt files.

Prompts live in services/llm/prompts/<name>_<version>.txt. ACTIVE_PROMPT_VERSIONS chooses which
version each agent uses; bump the version (new file) instead of editing a prompt in place so
agent_runs and eval results stay comparable.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).parent / "prompts"

ACTIVE_PROMPT_VERSIONS: dict[str, str] = {
    "research": "v1",
    "qualification": "v1",
    "outreach": "v2",
    "followup": "v1",
    "reply_analysis": "v2",
    "analytics": "v2",
    "email_intelligence": "v1",
    "support": "v1",
    "lifecycle": "v1",
}


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str

    @property
    def id(self) -> str:
        return f"{self.name}_{self.version}"


@lru_cache
def load_prompt(name: str, version: str | None = None) -> Prompt:
    version = version or ACTIVE_PROMPT_VERSIONS[name]
    path = PROMPT_DIR / f"{name}_{version}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path.name}")
    return Prompt(name=name, version=version, text=path.read_text(encoding="utf-8").strip())
