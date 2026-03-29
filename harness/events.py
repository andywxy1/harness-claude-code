"""Event bus for streaming structured events to UI and console."""

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


class EventBus:
    """Thread-safe event emitter that bridges sync orchestrator → async web UI."""

    def __init__(self):
        self._subscribers: list = []
        self._lock = threading.Lock()
        self._history: list[dict] = []
        self._audit_log_path: Path | None = None
        self._state = {
            "phase": "idle",
            "sprint_current": 0,
            "sprint_total": 0,
            "sprint_name": "",
            "agent": None,
            "negotiation_round": 0,
            "impl_cycle": 0,
            "status": "idle",
        }

    @property
    def state(self) -> dict:
        return dict(self._state)

    @property
    def history(self) -> list[dict]:
        return list(self._history)

    def subscribe(self, callback):
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback):
        with self._lock:
            self._subscribers.remove(callback)

    def set_audit_log(self, path: Path):
        self._audit_log_path = path

    def emit(self, event_type: str, **data):
        event = {
            "type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            "epoch": time.time(),
            **data,
        }

        # Update internal state based on event type
        self._update_state(event)

        # Store in history (skip high-frequency streaming events)
        if event_type not in ("agent_chunk", "agent_tool"):
            self._history.append(event)

        # Console output (skip chunks and tool events — they'd flood the terminal)
        if event_type not in ("agent_chunk", "agent_tool"):
            self._print_event(event)

        # Notify subscribers
        with self._lock:
            for cb in self._subscribers:
                try:
                    cb(event)
                except Exception:
                    pass

        # Append to audit log
        if self._audit_log_path:
            try:
                with open(self._audit_log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, default=str) + "\n")
            except OSError:
                pass

    def _update_state(self, event):
        t = event["type"]
        if t == "phase_change":
            self._state["phase"] = event.get("phase", "")
            self._state["status"] = "active"
        elif t == "sprint_start":
            self._state["sprint_current"] = event.get("sprint", 0)
            self._state["sprint_total"] = event.get("total", 0)
            self._state["sprint_name"] = event.get("name", "")
            self._state["negotiation_round"] = 0
            self._state["impl_cycle"] = 0
        elif t == "agent_start":
            self._state["agent"] = event.get("agent", "")
        elif t == "agent_done":
            self._state["agent"] = None
        elif t == "negotiation_round":
            self._state["negotiation_round"] = event.get("round", 0)
        elif t == "impl_cycle":
            self._state["impl_cycle"] = event.get("cycle", 0)
        elif t == "project_complete":
            self._state["phase"] = "complete"
            self._state["status"] = "complete"
            self._state["agent"] = None

    def _print_event(self, event):
        t = event["type"]
        ts = event["ts"][11:19]

        if t == "log":
            prefix = event.get("source", "")
            print(f"[{ts}] [{prefix}] {event.get('message', '')}")
        elif t == "phase_change":
            print(f"[{ts}] ━━━ Phase: {event.get('phase', '').upper()} ━━━")
        elif t == "sprint_start":
            n = event.get("sprint", "?")
            name = event.get("name", "")
            total = event.get("total", "?")
            print(f"[{ts}] ═══ Sprint {n}/{total}: {name} ═══")
        elif t == "agent_start":
            print(f"[{ts}] ▶ {event.get('agent', '')} started")
        elif t == "agent_done":
            print(f"[{ts}] ■ {event.get('agent', '')} finished")
        elif t == "agent_output":
            agent = event.get("agent", "")
            text = event.get("text", "")
            preview = text[:120].replace("\n", " ")
            print(f"[{ts}] [{agent}] {preview}{'...' if len(text) > 120 else ''}")
        elif t == "negotiation_round":
            r = event.get("round", "?")
            speaker = event.get("speaker", "")
            agreed = event.get("agreed", False)
            status = "AGREED" if agreed else "proposing"
            print(f"[{ts}] Negotiation round {r} — {speaker} {status}")
        elif t == "contract_agreed":
            print(f"[{ts}] ✓ Contract agreed")
        elif t == "impl_cycle":
            c = event.get("cycle", "?")
            stage = event.get("stage", "")
            print(f"[{ts}] Impl cycle {c} — {stage}")
        elif t == "eval_result":
            status = event.get("status", "?")
            reason = event.get("reason", "")
            print(f"[{ts}] Eval: {status} — {reason}")
        elif t == "rollback":
            print(f"[{ts}] ⚠ ROLLBACK — renegotiating contract")
        elif t == "done_signal_missing":
            print(f"[{ts}] ⚠ Generator did not signal done")
        elif t == "sprint_complete":
            print(f"[{ts}] ✓ Sprint {event.get('sprint', '?')} complete")
        elif t == "project_complete":
            print(f"[{ts}] ═══ PROJECT COMPLETE ═══")
        elif t == "error":
            print(f"[{ts}] ✗ ERROR: {event.get('message', '')}")


# Global singleton
bus = EventBus()


def make_stream_callback(agent: str):
    """Create an on_chunk callback that emits agent_chunk events."""
    def on_chunk(text: str):
        bus.emit("agent_chunk", agent=agent, text=text)
    return on_chunk


def make_tool_callback(agent: str):
    """Create an on_tool_use callback that emits agent_tool events."""
    def on_tool_use(info: dict):
        bus.emit("agent_tool", agent=agent, **info)
    return on_tool_use


def handle_streaming_result(result, agent: str) -> str:
    """Process the return value from a streaming call_claude call.

    When streaming was used (result is dict), the chunks already delivered
    the content via agent_chunk events — so we only emit usage, NOT
    agent_output (which would create a duplicate bubble).

    When not streaming (result is str), we emit agent_output.
    """
    if isinstance(result, dict):
        text = result.get("text", "")
        usage = result.get("usage")
        if usage:
            bus.emit("usage", agent=agent, **{k: v for k, v in usage.items() if v is not None})
        # Do NOT emit agent_output here — streaming chunks already showed the content.
        # The frontend's finishAgentBubble() (triggered by agent_done) archives it.
        return text
    else:
        bus.emit("agent_output", agent=agent, text=result)
        return result
