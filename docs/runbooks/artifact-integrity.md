# Artifact Integrity Alert Runbook

## Trigger

An artifact read raises `manifest_digest_mismatch` when the downloaded blob digest does not match the artifact manifest digest.

## Immediate Response

1. Treat the alert as potential storage corruption, not a transient download failure.
2. Keep the affected blob quarantined so it cannot be reused from cache.
3. Stop promoting or restoring artifacts from the same blob key until the source is verified.

## Investigation

1. Compare the manifest digest with the blob digest reported in the integrity alert.
2. Check recent artifact upload, replication, cache eviction, and object-store write logs for the artifact id and blob key.
3. Verify whether other artifacts in the same storage prefix or replication batch also fail digest validation.

## Recovery

1. Re-fetch or rebuild the artifact from a trusted source.
2. Replace the corrupted blob only after the rebuilt content digest matches the manifest.
3. Remove the quarantine entry after the replacement has been verified and logged.
4. Keep the alert attached to the incident record for audit and later trend analysis.
