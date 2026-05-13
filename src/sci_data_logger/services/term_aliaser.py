from __future__ import annotations

import json

from sci_data_logger.config import Settings, get_settings


class TermAliaser:
    """Load group-specific term aliases and normalize step types / methods."""

    def __init__(self, settings: Settings | None = None, group_id: str | None = None) -> None:
        self.settings = settings or get_settings()
        self.group_id = group_id
        self.term_aliases: dict[str, str] = {}
        self.common_step_types: set[str] = set()
        self._load()

    def _load(self) -> None:
        path = self.settings.group_template
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        for group in data.get("groups", []):
            if self.group_id and group.get("group_id") != self.group_id:
                continue
            self.term_aliases.update(group.get("term_aliases", {}))
            self.common_step_types.update(group.get("common_step_types", []))
            if self.group_id:
                break

    def canonical_step_type(self, raw: str | None) -> str:
        if not raw:
            return "other"
        raw_str = str(raw).strip()
        if raw_str.lower() in self.common_step_types:
            return raw_str.lower()
        mapped = self.term_aliases.get(raw_str)
        if mapped:
            return mapped
        for cn, en in self.term_aliases.items():
            if cn in raw_str:
                return en
        return raw_str.lower() if raw_str else "other"
