"""Configuration for Harness Claude — model assignments, timeouts, and selections."""

import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".claude" / "harness-claude-config.json"

# Default model configuration
DEFAULT_CONFIG = {
    "models": {
        "planner": "opus",
        "negotiation_generator": "opus",
        "negotiation_evaluator": "opus",
        "implementation_generator": "opus",
        "implementation_evaluator": "opus",
        "reviewer": "opus",
    },
    "timeouts": {
        "planner": 900,
        "negotiation": 600,
        "implementation": 1800,
        "implementation_onepass": 18000,  # 5 hours for one-pass mode
        "evaluation": 900,
        "review": 900,
    },
    "max_negotiation_rounds": 50,
    "selected_skills": [],
    "selected_agents": [],
    "onboarded": False,
}


class Config:
    """Runtime configuration, settable via web UI. Persists to disk."""

    def __init__(self):
        self._data = json.loads(json.dumps(DEFAULT_CONFIG))
        self._load_from_disk()

    def _load_from_disk(self):
        if CONFIG_PATH.exists():
            try:
                saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                self.from_dict(saved)
            except (json.JSONDecodeError, OSError):
                pass

    def save_to_disk(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(self._data, indent=2), encoding="utf-8"
        )

    @property
    def models(self) -> dict:
        return self._data["models"]

    @property
    def timeouts(self) -> dict:
        return self._data["timeouts"]

    def get_model(self, role: str) -> str:
        return self._data["models"].get(role, "opus")

    def get_timeout(self, phase: str) -> int:
        return self._data["timeouts"].get(phase, 600)

    def update_model(self, role: str, model: str):
        if role in self._data["models"]:
            self._data["models"][role] = model

    def update_timeout(self, phase: str, timeout: int):
        if phase in self._data["timeouts"]:
            self._data["timeouts"][phase] = int(timeout)

    def get_max_negotiation_rounds(self) -> int:
        return self._data.get("max_negotiation_rounds", 50)

    # ── Skill/Agent selections ──

    def get_selected_skills(self) -> list[str]:
        return self._data.get("selected_skills", [])

    def set_selected_skills(self, skill_ids: list[str]):
        self._data["selected_skills"] = skill_ids

    def get_selected_agents(self) -> list[str]:
        return self._data.get("selected_agents", [])

    def set_selected_agents(self, agent_ids: list[str]):
        self._data["selected_agents"] = agent_ids

    def is_onboarded(self) -> bool:
        return self._data.get("onboarded", False)

    def set_onboarded(self, value: bool):
        self._data["onboarded"] = value

    # ── Serialization ──

    def to_dict(self) -> dict:
        return json.loads(json.dumps(self._data))

    def from_dict(self, data: dict):
        if "models" in data:
            for k, v in data["models"].items():
                if k in self._data["models"]:
                    self._data["models"][k] = v
        if "timeouts" in data:
            for k, v in data["timeouts"].items():
                if k in self._data["timeouts"]:
                    self._data["timeouts"][k] = int(v)
        if "max_negotiation_rounds" in data:
            self._data["max_negotiation_rounds"] = int(data["max_negotiation_rounds"])
        if "selected_skills" in data:
            self._data["selected_skills"] = data["selected_skills"]
        if "selected_agents" in data:
            self._data["selected_agents"] = data["selected_agents"]
        if "onboarded" in data:
            self._data["onboarded"] = data["onboarded"]


# Global singleton
config = Config()
