"""Bounded in-memory draft storage for the local lab."""

from collections import OrderedDict

from trego_agent.v2.walk_chat import WalkDraft


class MemoryDrafts:
    def __init__(self) -> None:
        self._drafts: OrderedDict[str, WalkDraft] = OrderedDict()

    def get(self, session_id: str) -> WalkDraft | None:
        return self._drafts.get(session_id)

    def save(self, session_id: str, draft: WalkDraft) -> None:
        self._drafts[session_id] = draft
        self._drafts.move_to_end(session_id)
        if len(self._drafts) > 20:
            self._drafts.popitem(last=False)

    def clear(self) -> None:
        self._drafts.clear()
