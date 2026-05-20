"""Hold-aware artifact retention cleanup."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class ArtifactRetentionRecord:
    artifact_id: str
    retention_expires_at: datetime
    legal_hold: bool = False
    investigation_hold: bool = False
    legal_hold_reason: Optional[str] = None
    investigation_hold_reason: Optional[str] = None

    @property
    def has_active_hold(self) -> bool:
        return self.legal_hold or self.investigation_hold


@dataclass(frozen=True)
class HeldArtifactReportEntry:
    artifact_id: str
    retention_expires_at: datetime
    hold_type: str
    hold_reasons: Sequence[str]


@dataclass(frozen=True)
class RetentionCleanupPlan:
    artifact_ids_to_delete: Sequence[str]
    held_expired_artifacts: Sequence[HeldArtifactReportEntry]


class RetentionCleanupService:
    def plan_cleanup(
        self,
        artifacts: Iterable[ArtifactRetentionRecord],
        now: Optional[datetime] = None,
    ) -> RetentionCleanupPlan:
        cutoff = now or datetime.now(timezone.utc)
        artifact_ids_to_delete: List[str] = []
        held_expired_artifacts: List[HeldArtifactReportEntry] = []

        for artifact in artifacts:
            if artifact.retention_expires_at >= cutoff:
                continue

            if artifact.has_active_hold:
                held_expired_artifacts.append(self._held_report_entry(artifact))
                continue

            artifact_ids_to_delete.append(artifact.artifact_id)

        return RetentionCleanupPlan(
            artifact_ids_to_delete=artifact_ids_to_delete,
            held_expired_artifacts=held_expired_artifacts,
        )

    def _held_report_entry(
        self,
        artifact: ArtifactRetentionRecord,
    ) -> HeldArtifactReportEntry:
        hold_types: List[str] = []
        hold_reasons: List[str] = []

        if artifact.legal_hold:
            hold_types.append("legal")
            if artifact.legal_hold_reason:
                hold_reasons.append(artifact.legal_hold_reason)
        if artifact.investigation_hold:
            hold_types.append("investigation")
            if artifact.investigation_hold_reason:
                hold_reasons.append(artifact.investigation_hold_reason)

        return HeldArtifactReportEntry(
            artifact_id=artifact.artifact_id,
            retention_expires_at=artifact.retention_expires_at,
            hold_type="+".join(hold_types),
            hold_reasons=tuple(hold_reasons),
        )
