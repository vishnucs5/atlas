"""CLI session management and history persistence."""

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class SessionManager:
    """Manages CLI interactive session history, resumption, and export."""

    def __init__(self, sessions_dir: Path | None = None) -> None:
        if sessions_dir is not None:
            self.sessions_dir = sessions_dir
        else:
            atlas_home = os.environ.get("ATLAS_HOME")
            if atlas_home:
                base = Path(atlas_home) / ".atlas"
            elif Path(".atlas").exists():
                base = Path(".atlas")
            else:
                base = Path.home() / ".atlas"
            self.sessions_dir = base / "sessions"

        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, objective: str, task_id: str | None = None) -> dict[str, Any]:
        """Create and initialize a new CLI session record."""
        session_id = f"cli_sess_{int(time.time())}_{os.urandom(3).hex()}"
        now = datetime.now(UTC).isoformat()
        session_data: dict[str, Any] = {
            "session_id": session_id,
            "created_at": now,
            "updated_at": now,
            "objective": objective,
            "status": "ACTIVE",
            "task_id": task_id,
            "history": [],
            "deliverables": {},
        }
        self.save_session(session_id, session_data)
        return session_data

    def save_session(self, session_id: str, data: dict[str, Any]) -> None:
        """Persist session data to disk."""
        data["updated_at"] = datetime.now(UTC).isoformat()
        path = self.sessions_dir / f"{session_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Load session data by ID."""
        path = self.sessions_dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        """List all saved sessions in reverse chronological order."""
        sessions = []
        for file in self.sessions_dir.glob("*.json"):
            try:
                with open(file, encoding="utf-8") as f:
                    sessions.append(json.load(f))
            except Exception:
                continue
        sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
        return sessions[:limit]

    def export_session(
        self, session_id: str, output_path: Path | None = None, fmt: str = "json"
    ) -> Path:
        """Export session trace to file."""
        data = self.get_session(session_id)
        if not data:
            raise FileNotFoundError(f"Session '{session_id}' not found.")

        out = output_path or (self.sessions_dir / f"{session_id}_export.{fmt}")
        with open(out, "w", encoding="utf-8") as f:
            if fmt == "json":
                json.dump(data, f, indent=2)
            else:
                f.write(f"# ATLAS Session: {session_id}\n\n")
                f.write(f"- **Objective**: {data.get('objective')}\n")
                f.write(f"- **Status**: {data.get('status')}\n")
                f.write(f"- **Created At**: {data.get('created_at')}\n\n")
                f.write("## Deliverables\n\n")
                f.write(f"```json\n{json.dumps(data.get('deliverables', {}), indent=2)}\n```\n")
        return out
