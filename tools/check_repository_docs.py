"""Reject stale operational claims without confusing history with live evidence."""

from pathlib import Path
import re

PROJECT = Path(__file__).resolve().parents[1]


def check(root=PROJECT):
    problems = []
    for name in ("CONTRIBUTING.md", "GOVERNANCE.md", "SECURITY.md"):
        text = (root / name).read_text(encoding="utf-8")
        if re.search(r"(?:currently private|this private repository)", text, re.I):
            problems.append(f"{name}: stale private-repository claim")
    for name, stale in (
        ("README.md", "No actual GitHub Actions run has been observed in this round"),
        ("README_TH.md", "ยังไม่มีผลรัน GitHub Actions จริงในรอบนี้"),
    ):
        text = (root / name).read_text(encoding="utf-8")
        if stale in text:
            problems.append(f"{name}: stale no-CI-run claim")
        if "RESEARCH_IMPLEMENTATION_TH.md" not in text:
            problems.append(f"{name}: missing source/status qualification")
    if problems:
        raise ValueError("\n".join(problems))
    return "Repository documentation consistency passed (static claims only; no live API verification)."


if __name__ == "__main__":
    print(check())
