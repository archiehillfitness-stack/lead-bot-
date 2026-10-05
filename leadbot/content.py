import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Question:
    key: str
    text: str
    options: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Content:
    keywords: list[str]
    links: dict[str, str]
    public_comment_reply: str
    messages: dict[str, str]
    questions: list[Question]

    @classmethod
    def load(cls, path: str | Path) -> "Content":
        raw = yaml.safe_load(Path(path).read_text())
        questions = [
            Question(key=q["key"], text=q["text"], options=list(q.get("options") or []))
            for q in raw.get("questions") or []
        ]
        for q in questions:
            if len(q.options) > 13:
                raise ValueError(f"Question {q.key!r} has more than 13 options")
            for opt in q.options:
                if len(opt) > 20:
                    raise ValueError(f"Option {opt!r} is longer than 20 characters")
        return cls(
            keywords=[normalize(k) for k in raw.get("keywords") or []],
            links=dict(raw.get("links") or {}),
            public_comment_reply=(raw.get("public_comment_reply") or "").strip(),
            messages=dict(raw.get("messages") or {}),
            questions=questions,
        )

    def message(self, name: str, username: str | None = None) -> str:
        template = self.messages[name]
        values = {"name": username or "there", **self.links}
        return template.format_map(_Defaulting(values))

    def matches_keyword(self, text: str | None) -> bool:
        if not text:
            return False
        words = set(normalize(text).split())
        return any(k in words for k in self.keywords)


class _Defaulting(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text).split()).lower()
