import re
from typing import Iterable, Protocol, Sequence

class ModelProvider(Protocol):
    def stream(self, history: Sequence[dict]) -> Iterable[str]:
        """Yield text fragments for a chronological conversation."""

class MockProvider:
    def stream(self, history: Sequence[dict]) -> Iterable[str]:
        latest = history[-1]["content"]
        turn = sum(message["role"] == "user" for message in history)
        excerpt = " ".join(latest.split())[:220]
        output = (
            f'Mock reply for turn {turn}: I received "{excerpt}".\n\n'
            "A practical next step is to identify the goal, list the available inputs, "
            "and choose one small action you can verify. Tell me which part to explore next."
        )
        words = re.findall(r"\S+\s*|\s+", output)
        for start in range(0, len(words), 3):
            yield "".join(words[start:start + 3])
