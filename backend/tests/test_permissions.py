"""Tests for the layered permission model (deerflow.permissions)."""

from deerflow.permissions.mode import PermissionMode
from deerflow.permissions.policy import PermissionOutcome, PermissionPolicy
from deerflow.permissions.prompter import AutoAllowPrompter, AutoDenyPrompter


class TestPermissionMode:
    def test_ordering(self):
        assert PermissionMode.READ_ONLY < PermissionMode.WORKSPACE_WRITE
        assert PermissionMode.WORKSPACE_WRITE < PermissionMode.DANGER_FULL_ACCESS
        assert PermissionMode.DANGER_FULL_ACCESS < PermissionMode.PROMPT
        assert PermissionMode.PROMPT < PermissionMode.ALLOW

    def test_all_five_levels(self):
        assert len(PermissionMode) == 5


class TestPermissionPolicy:
    def test_allow_mode_permits_everything(self):
        policy = PermissionPolicy(active_mode=PermissionMode.ALLOW)
        assert policy.authorize("bash").allowed
        assert policy.authorize("unknown_tool").allowed

    def test_read_only_permits_read_tools(self):
        policy = PermissionPolicy(
            active_mode=PermissionMode.READ_ONLY,
            tool_requirements={"read_file": PermissionMode.READ_ONLY},
        )
        assert policy.authorize("read_file").allowed

    def test_read_only_blocks_dangerous_tools(self):
        policy = PermissionPolicy(
            active_mode=PermissionMode.READ_ONLY,
            tool_requirements={"bash": PermissionMode.DANGER_FULL_ACCESS},
        )
        outcome = policy.authorize("bash")
        assert outcome.is_denied()
        assert "bash" in outcome.reason

    def test_unknown_tool_defaults_to_danger(self):
        policy = PermissionPolicy(active_mode=PermissionMode.READ_ONLY)
        assert policy.required_mode_for("unknown") == PermissionMode.DANGER_FULL_ACCESS
        assert policy.authorize("unknown").is_denied()

    def test_prompt_mode_with_auto_allow(self):
        policy = PermissionPolicy(
            active_mode=PermissionMode.PROMPT,
            tool_requirements={"bash": PermissionMode.DANGER_FULL_ACCESS},
        )
        outcome = policy.authorize("bash", prompter=AutoAllowPrompter())
        assert outcome.allowed

    def test_prompt_mode_with_auto_deny(self):
        policy = PermissionPolicy(
            active_mode=PermissionMode.PROMPT,
            tool_requirements={"nuke": PermissionMode.ALLOW},
        )
        outcome = policy.authorize("nuke", prompter=AutoDenyPrompter())
        assert outcome.is_denied()

    def test_prompt_mode_auto_allows_lower_requirement(self):
        policy = PermissionPolicy(
            active_mode=PermissionMode.PROMPT,
            tool_requirements={"read_file": PermissionMode.READ_ONLY},
        )
        assert policy.authorize("read_file").allowed

    def test_with_tool_requirement_immutability(self):
        base = PermissionPolicy(active_mode=PermissionMode.ALLOW)
        extended = base.with_tool_requirement("new_tool", PermissionMode.WORKSPACE_WRITE)
        assert "new_tool" in extended.tool_requirements
        assert "new_tool" not in base.tool_requirements

    def test_permission_outcome_factories(self):
        allow = PermissionOutcome.allow()
        assert allow.allowed
        deny = PermissionOutcome.deny("nope")
        assert deny.is_denied()
        assert deny.reason == "nope"
