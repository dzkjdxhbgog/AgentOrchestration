from src.common.reporting_cache import ReportAuthContext, ReportResultCache


def test_role_downgrade_does_not_reuse_cached_report():
    cache = ReportResultCache()
    admin = ReportAuthContext.from_values(
        user_id="user-1",
        workspace_id="workspace-1",
        roles=("admin",),
        scopes=("reports:read",),
        access_version=1,
    )
    viewer = ReportAuthContext.from_values(
        user_id="user-1",
        workspace_id="workspace-1",
        roles=("viewer",),
        scopes=("reports:read",),
        access_version=2,
    )

    cache.set("revenue", {"month": "2026-05"}, admin, {"rows": ["secret"]})

    assert cache.get("revenue", {"month": "2026-05"}, viewer) is None


def test_workspace_removal_revalidates_before_cached_hit():
    active_workspaces = {"workspace-1"}

    def validator(context):
        return context.workspace_id in active_workspaces

    cache = ReportResultCache(access_validator=validator)
    context = ReportAuthContext.from_values(
        user_id="user-1",
        workspace_id="workspace-1",
        roles=("viewer",),
        scopes=("reports:read",),
        access_version=1,
    )

    cache.set("pipeline", {"team": "sales"}, context, {"rows": [1]})
    active_workspaces.clear()

    assert cache.get("pipeline", {"team": "sales"}, context) is None


def test_cache_key_separates_workspace_context():
    cache = ReportResultCache()
    workspace_one = ReportAuthContext.from_values(
        user_id="user-1",
        workspace_id="workspace-1",
        roles=("viewer",),
        scopes=("reports:read",),
    )
    workspace_two = ReportAuthContext.from_values(
        user_id="user-1",
        workspace_id="workspace-2",
        roles=("viewer",),
        scopes=("reports:read",),
    )

    cache.set("usage", {"limit": 10}, workspace_one, {"rows": ["one"]})
    cache.set("usage", {"limit": 10}, workspace_two, {"rows": ["two"]})

    assert cache.get("usage", {"limit": 10}, workspace_one) == {
        "rows": ["one"],
    }
    assert cache.get("usage", {"limit": 10}, workspace_two) == {
        "rows": ["two"],
    }


def test_cache_key_separates_scope_context():
    cache = ReportResultCache()
    scoped = ReportAuthContext.from_values(
        user_id="user-1",
        workspace_id="workspace-1",
        roles=("viewer",),
        scopes=("reports:read", "finance:read"),
    )
    reduced = ReportAuthContext.from_values(
        user_id="user-1",
        workspace_id="workspace-1",
        roles=("viewer",),
        scopes=("reports:read",),
    )

    cache.set("finance", {"month": "2026-05"}, scoped, {"rows": ["gross"]})

    assert cache.get("finance", {"month": "2026-05"}, reduced) is None


def test_cached_payload_is_isolated_from_callers():
    cache = ReportResultCache()
    context = ReportAuthContext.from_values(
        user_id="user-1",
        workspace_id="workspace-1",
        roles=("viewer",),
        scopes=("reports:read",),
    )
    value = {"rows": [{"name": "alpha"}]}

    cache.set("usage", {}, context, value)
    value["rows"][0]["name"] = "mutated"
    cached = cache.get("usage", {}, context)
    cached["rows"][0]["name"] = "caller-mutated"

    assert cache.get("usage", {}, context) == {
        "rows": [{"name": "alpha"}],
    }
