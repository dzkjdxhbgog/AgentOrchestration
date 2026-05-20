from pathlib import Path

from scripts.validate_action_refs import mutable_action_refs


def _write_workflow(root: Path, body: str) -> None:
    workflow_dir = root / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(body, encoding="utf-8")


def test_flags_mutable_external_action_refs(tmp_path: Path):
    _write_workflow(
        tmp_path,
        """
name: test
jobs:
  test:
    steps:
      - uses: actions/checkout@v4
      - uses: org/reusable/.github/workflows/test.yml@main
      - uses: ./.github/actions/local-action
""",
    )

    problems = mutable_action_refs(tmp_path)

    assert [problem[2] for problem in problems] == [
        "actions/checkout@v4",
        "org/reusable/.github/workflows/test.yml@main",
    ]


def test_accepts_pinned_external_actions_and_local_refs(tmp_path: Path):
    _write_workflow(
        tmp_path,
        """
name: test
jobs:
  test:
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
      - uses: "./.github/actions/local-action"
      - uses: docker://alpine:3.20
""",
    )

    assert mutable_action_refs(tmp_path) == []
