import pytest

from src.common.feature_flags import (
    FeatureFlagSpec,
    FeatureFlagValidationError,
    load_rendered_feature_flags,
    validate_feature_flag_manifest,
    validate_rendered_feature_flags,
)


def test_missing_required_flags_block_rollout():
    manifest = [
        FeatureFlagSpec(
            name="task_retry_backoff_v2",
            default=False,
            owner="orchestrator-platform",
            description="Retry rollout guard.",
        )
    ]
    rendered = {
        "scheduler": {},
        "worker": {"task_retry_backoff_v2": False},
    }

    with pytest.raises(FeatureFlagValidationError) as exc:
        validate_rendered_feature_flags(rendered, manifest)

    assert "scheduler" in str(exc.value)
    assert "task_retry_backoff_v2" in str(exc.value)


def test_scheduler_worker_mismatch_does_not_print_flag_values():
    manifest = [
        FeatureFlagSpec(
            name="private_flag_seed",
            default="expected-secret-default",
            owner="release-platform",
            description="Sensitive rollout seed.",
        )
    ]
    rendered = {
        "scheduler": {"private_flag_seed": "scheduler-secret-value"},
        "worker": {"private_flag_seed": "worker-secret-value"},
    }

    with pytest.raises(FeatureFlagValidationError) as exc:
        validate_rendered_feature_flags(rendered, manifest)

    message = str(exc.value)
    assert "private_flag_seed" in message
    assert "scheduler-secret-value" not in message
    assert "worker-secret-value" not in message
    assert "expected-secret-default" not in message


def test_manifest_requires_documented_default_and_owner():
    with pytest.raises(FeatureFlagValidationError) as exc:
        validate_feature_flag_manifest(
            [
                {
                    "name": "strict_scheduler_worker_contract",
                    "description": "Contract rollout guard.",
                    "services": ["scheduler", "worker"],
                }
            ]
        )

    message = str(exc.value)
    assert "documented default" in message
    assert "owner" in message


def test_manifest_defaults_to_scheduler_and_worker_services():
    specs = validate_feature_flag_manifest(
        [
            {
                "name": "strict_scheduler_worker_contract",
                "default": True,
                "owner": "orchestrator-platform",
                "description": "Contract rollout guard.",
            }
        ]
    )

    assert specs[0].services == ("scheduler", "worker")


def test_valid_rendered_flags_pass():
    manifest = [
        FeatureFlagSpec(
            name="strict_scheduler_worker_contract",
            default=True,
            owner="orchestrator-platform",
            description="Contract rollout guard.",
        )
    ]
    rendered = {
        "scheduler": {"strict_scheduler_worker_contract": True},
        "worker": {"strict_scheduler_worker_contract": True},
    }

    validate_rendered_feature_flags(rendered, manifest)


def test_load_rendered_flags_accepts_services_shape(tmp_path):
    rendered_file = tmp_path / "rendered.json"
    rendered_file.write_text(
        """
        {
          "services": {
            "scheduler": {
              "feature_flags": {
                "strict_scheduler_worker_contract": true
              }
            },
            "worker": {
              "feature_flags": {
                "strict_scheduler_worker_contract": true
              }
            }
          }
        }
        """,
        encoding="utf-8",
    )

    rendered = load_rendered_feature_flags(rendered_file)

    assert rendered == {
        "scheduler": {"strict_scheduler_worker_contract": True},
        "worker": {"strict_scheduler_worker_contract": True},
    }
