"""Configuration for Harness Claude — model assignments and timeouts."""

import json
from pathlib import Path

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
        "evaluation": 900,
        "review": 900,
    },
    "max_negotiation_rounds": 50,
}


class Config:
    """Runtime configuration, settable via web UI."""

    def __init__(self):
        self._data = json.loads(json.dumps(DEFAULT_CONFIG))

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
            self._data["timeouts"][phase] = timeout

    def get_max_negotiation_rounds(self) -> int:
        return self._data.get("max_negotiation_rounds", 50)

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


# Global singleton
config = Config()
