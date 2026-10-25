"""The version is a promise: the running app can be matched to a changelog entry.

Forgetting to bump it is easy and silent, which is exactly what a test is for.
"""

import re
from pathlib import Path

import volley

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def released_versions() -> list[str]:
    return re.findall(r"^## \[(\d+\.\d+\.\d+)\]", CHANGELOG.read_text(), flags=re.M)


def test_the_version_looks_like_one():
    assert re.fullmatch(r"\d+\.\d+\.\d+", volley.__version__)


def test_the_current_version_has_a_changelog_entry():
    versions = released_versions()
    assert volley.__version__ in versions, (
        f"v{volley.__version__} is not in CHANGELOG.md - add what changed, "
        "or the version was bumped without saying why."
    )


def test_the_changelog_is_newest_first():
    versions = [tuple(int(part) for part in v.split(".")) for v in released_versions()]
    assert versions == sorted(versions, reverse=True)


def test_the_newest_entry_is_the_version_that_runs():
    assert released_versions()[0] == volley.__version__
