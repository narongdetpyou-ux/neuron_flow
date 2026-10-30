"""Check maintained English documentation and qualified operational claims."""

import json
from pathlib import Path
import re

PROJECT = Path(__file__).resolve().parents[1]
THAI = re.compile("[\u0e00-\u0e7f]")


def check(root=PROJECT):
    root = Path(root)
    problems = []
    for name in ("CONTRIBUTING.md", "GOVERNANCE.md", "SECURITY.md", "SUPPORT.md"):
        text = (root / name).read_text(encoding="utf-8")
        if re.search(r"(?:currently private|this private repository)", text, re.I):
            problems.append(f"{name}: stale private-repository claim")
    overview = (root / "README.md").read_text(encoding="utf-8")
    if "No actual GitHub Actions run has been observed in this round" in overview:
        problems.append("README.md: stale no-CI-run claim")
    for target in ("docs/RESEARCH_IMPLEMENTATION.md", "docs/DATA_AND_MARKET_FIT.md", "docs/README.md"):
        if target not in overview:
            problems.append(f"README.md: missing guide link {target}")

    # Raw sources, locked fixtures, approval quotations and archived machine
    # evidence retain their original bytes. These checks cover maintained text.
    documents = list(root.glob("*.md")) + list((root / "docs").rglob("*.md"))
    documents += [root / "acceptance/README.md"]
    documents += list((root / "examples").rglob("*.md"))
    forms = list((root / ".github/ISSUE_TEMPLATE").glob("*.yml"))
    for path in documents + forms:
        text = path.read_text(encoding="utf-8")
        name = path.relative_to(root).as_posix()
        if THAI.search(text):
            problems.append(f"{name}: untranslated maintained text")
        if "_TH.md" in text or path.name.endswith("_TH.md"):
            problems.append(f"{name}: stale maintained language-specific path")
        if path in documents:
            for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
                target = link.split("#", 1)[0]
                if target and not re.match(r"(?:[a-zA-Z][a-zA-Z0-9+.-]*:|/)", target):
                    if not (path.parent / target).exists():
                        problems.append(f"{name}: broken relative link {target}")

    notebook = json.loads((root / "START_COLAB.ipynb").read_text(encoding="utf-8"))
    for index, cell in enumerate(notebook["cells"]):
        if THAI.search("".join(cell["source"])):
            problems.append(f"START_COLAB.ipynb cell {index}: untranslated text")
    if problems:
        raise ValueError("\n".join(problems))
    return "English documentation, notebook and relative links passed (static checks; no live API verification)."


if __name__ == "__main__":
    print(check())
