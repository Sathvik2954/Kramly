"""
test_self_critique.py
---------------------
Tests for Phase 6 — Self-Critique Agent.

Coverage
~~~~~~~~
✓ Valid path passes all checks
✓ Duplicate skill detection
✓ Prerequisite ordering violation detection
✓ Missing prerequisite suggestions
✓ Unreachable target warning
✓ Empty path warning (target unknown)
✓ Empty path passes (target already known)
✓ Multiple violations aggregated
✓ Warnings vs. suggestions distinction
✓ Critique never modifies the path

Design decisions
~~~~~~~~~~~~~~~~
- Uses the same WebDev graph topology from ``conftest.py`` for consistency.
- Each test class focuses on one validation check.
- ``TestCritiqueContract`` verifies the agent's fundamental constraints:
  it only evaluates, never modifies.
"""

import pytest

from agent.models import SelfCritiqueResult
from agent.self_critique import review_learning_path


# ---------------------------------------------------------------------------
# Shared mock prerequisites — matches conftest.py WebDev graph
# ---------------------------------------------------------------------------

PREREQS: dict[str, list[dict]] = {
    "web01": [],
    "web02": [{"id": "web01"}],
    "web03": [{"id": "web02"}],
    "web04": [{"id": "web03"}],
    "web05": [{"id": "web03"}],
    "web07": [{"id": "web02"}],
    "web08": [{"id": "web04"}, {"id": "web05"}, {"id": "web07"}],
    "web09": [{"id": "web08"}],
}


def _fetch_prereqs(skill_id: str) -> list[dict]:
    return PREREQS.get(skill_id, [])


# ===================================================================
# VALID PATH TESTS
# ===================================================================


class TestValidPath:
    """A correctly ordered path should pass all checks."""

    def test_valid_path_passes(self):
        """Standard valid path should produce passed=True, no warnings."""
        result = review_learning_path(
            path=["web03", "web04", "web05", "web07", "web08"],
            target_skill="web08",
            known_skills=["web01", "web02"],
            fetch_prerequisites=_fetch_prereqs,
        )
        assert result.passed is True, "Valid path should pass"
        assert result.warnings == [], "No warnings for valid path"

    def test_single_skill_path(self):
        """A path with just the target should pass if it has no missing prereqs."""
        result = review_learning_path(
            path=["web01"],
            target_skill="web01",
            known_skills=[],
            fetch_prerequisites=_fetch_prereqs,
        )
        assert result.passed is True, "Single root skill should pass"

    def test_empty_path_with_known_target(self):
        """Empty path is valid when the learner already knows the target."""
        result = review_learning_path(
            path=[],
            target_skill="web08",
            known_skills=["web08"],
            fetch_prerequisites=_fetch_prereqs,
        )
        assert result.passed is True
        assert result.warnings == []


# ===================================================================
# DUPLICATE DETECTION TESTS
# ===================================================================


class TestDuplicateDetection:
    """Tests for detecting duplicate skill IDs in the path."""

    def test_duplicate_skill_produces_warning(self):
        """A duplicated skill should generate a warning."""
        result = review_learning_path(
            path=["web03", "web03", "web04", "web08"],
            target_skill="web08",
            known_skills=["web01", "web02"],
            fetch_prerequisites=_fetch_prereqs,
        )
        assert result.passed is False, "Duplicates should fail"
        assert any("Duplicate" in w for w in result.warnings), (
            "Should contain 'Duplicate' warning"
        )

    def test_duplicate_warning_mentions_skill_id(self):
        """The warning message should include the duplicated skill ID."""
        result = review_learning_path(
            path=["web04", "web04"],
            target_skill="web04",
            known_skills=["web01", "web02", "web03"],
            fetch_prerequisites=_fetch_prereqs,
        )
        assert any("web04" in w for w in result.warnings)

    def test_multiple_duplicates_produce_multiple_warnings(self):
        """Each duplicate occurrence should produce its own warning."""
        result = review_learning_path(
            path=["web03", "web03", "web04", "web04"],
            target_skill="web04",
            known_skills=["web01", "web02"],
            fetch_prerequisites=_fetch_prereqs,
        )
        duplicate_warnings = [w for w in result.warnings if "Duplicate" in w]
        assert len(duplicate_warnings) == 2, (
            "Two duplicated skills → two warnings"
        )


# ===================================================================
# PREREQUISITE ORDERING TESTS
# ===================================================================


class TestPrerequisiteOrdering:
    """Tests for detecting prerequisite ordering violations."""

    def test_prereq_after_dependent_produces_warning(self):
        """A prerequisite appearing after its dependent is a violation."""
        result = review_learning_path(
            path=["web05", "web03", "web04", "web07", "web08"],
            target_skill="web08",
            known_skills=["web01", "web02"],
            fetch_prerequisites=_fetch_prereqs,
        )
        assert result.passed is False
        assert any("web05" in w and "web03" in w for w in result.warnings), (
            "Should warn about web05 appearing before web03"
        )

    def test_warning_includes_positions(self):
        """The warning should mention the positions of both skills."""
        result = review_learning_path(
            path=["web04", "web03", "web08"],
            target_skill="web08",
            known_skills=["web01", "web02", "web05", "web07"],
            fetch_prerequisites=_fetch_prereqs,
        )
        ordering_warnings = [
            w for w in result.warnings
            if "position" in w.lower()
        ]
        assert len(ordering_warnings) > 0, "Should include position info"

    def test_correct_ordering_no_warning(self):
        """When all prerequisites come first, no ordering warning."""
        result = review_learning_path(
            path=["web03", "web04"],
            target_skill="web04",
            known_skills=["web01", "web02"],
            fetch_prerequisites=_fetch_prereqs,
        )
        ordering_warnings = [
            w for w in result.warnings if "before its prerequisite" in w
        ]
        assert ordering_warnings == [], "Correct order → no warning"


# ===================================================================
# MISSING PREREQUISITES TESTS
# ===================================================================


class TestMissingPrerequisites:
    """Tests for missing prerequisite suggestions."""

    def test_missing_prereq_generates_suggestion(self):
        """A prerequisite not in the path or known skills → suggestion."""
        result = review_learning_path(
            path=["web03", "web04", "web08"],
            target_skill="web08",
            known_skills=[],  # web02 not known
            fetch_prerequisites=_fetch_prereqs,
        )
        assert any("web02" in s for s in result.suggestions), (
            "Should suggest including web02 (prereq of web03)"
        )

    def test_known_prereq_not_suggested(self):
        """A prerequisite in known_skills should NOT be suggested."""
        result = review_learning_path(
            path=["web03", "web04", "web08"],
            target_skill="web08",
            known_skills=["web01", "web02", "web05", "web07"],
            fetch_prerequisites=_fetch_prereqs,
        )
        suggestions_about_web02 = [s for s in result.suggestions if "web02" in s]
        assert suggestions_about_web02 == [], (
            "web02 is known → should not be suggested"
        )

    def test_prereq_in_path_not_suggested(self):
        """A prerequisite already in the path should NOT be suggested."""
        result = review_learning_path(
            path=["web02", "web03", "web04"],
            target_skill="web04",
            known_skills=["web01"],
            fetch_prerequisites=_fetch_prereqs,
        )
        suggestions_about_web02 = [s for s in result.suggestions if "web02" in s]
        assert suggestions_about_web02 == [], (
            "web02 is in the path → should not be suggested"
        )

    def test_missing_prereqs_are_suggestions_not_warnings(self):
        """Missing prerequisites should produce suggestions, NOT warnings."""
        result = review_learning_path(
            path=["web03", "web04"],
            target_skill="web04",
            known_skills=[],
            fetch_prerequisites=_fetch_prereqs,
        )
        # web02 is missing but should be a suggestion, not a warning
        warning_text = " ".join(result.warnings)
        assert "web02" not in warning_text, (
            "Missing prereqs should be suggestions, not warnings"
        )


# ===================================================================
# UNREACHABLE TARGET TESTS
# ===================================================================


class TestUnreachableTarget:
    """Tests for target skill not in the path."""

    def test_missing_target_produces_warning(self):
        """If the target is not in the path, emit a warning."""
        result = review_learning_path(
            path=["web03", "web04", "web05"],
            target_skill="web08",
            known_skills=["web01", "web02"],
            fetch_prerequisites=_fetch_prereqs,
        )
        assert result.passed is False
        assert any("not present" in w for w in result.warnings)

    def test_target_present_no_warning(self):
        """If the target is in the path, no unreachable warning."""
        result = review_learning_path(
            path=["web03", "web04", "web05", "web07", "web08"],
            target_skill="web08",
            known_skills=["web01", "web02"],
            fetch_prerequisites=_fetch_prereqs,
        )
        target_warnings = [w for w in result.warnings if "not present" in w]
        assert target_warnings == []


# ===================================================================
# EMPTY PATH TESTS
# ===================================================================


class TestEmptyPath:
    """Tests for empty learning path validation."""

    def test_empty_path_unknown_target_warns(self):
        """Empty path + unknown target → warning."""
        result = review_learning_path(
            path=[],
            target_skill="web08",
            known_skills=["web01"],
            fetch_prerequisites=_fetch_prereqs,
        )
        assert result.passed is False
        assert any("empty" in w.lower() for w in result.warnings)

    def test_empty_path_known_target_passes(self):
        """Empty path + known target → no warning (learner already knows it)."""
        result = review_learning_path(
            path=[],
            target_skill="web08",
            known_skills=["web08"],
            fetch_prerequisites=_fetch_prereqs,
        )
        assert result.passed is True


# ===================================================================
# AGGREGATION AND CONTRACT TESTS
# ===================================================================


class TestCritiqueAggregation:
    """Tests for multiple issues being aggregated correctly."""

    def test_multiple_issues_aggregated(self):
        """Multiple problems should all appear in a single result."""
        # Duplicate + ordering violation + missing target
        result = review_learning_path(
            path=["web05", "web03", "web03", "web04"],
            target_skill="web08",
            known_skills=["web01", "web02"],
            fetch_prerequisites=_fetch_prereqs,
        )
        assert result.passed is False
        assert len(result.warnings) >= 2, (
            "Should have at least: ordering violation + duplicate + missing target"
        )


class TestCritiqueContract:
    """Tests for the critique agent's fundamental contract."""

    def test_critique_returns_selfcritiqueresult(self):
        """Return type should always be SelfCritiqueResult."""
        result = review_learning_path(
            path=["web03"],
            target_skill="web03",
            known_skills=["web01", "web02"],
            fetch_prerequisites=_fetch_prereqs,
        )
        assert isinstance(result, SelfCritiqueResult)

    def test_critique_does_not_modify_path(self):
        """The input path list should not be mutated by the critique agent."""
        path = ["web03", "web04", "web05", "web07", "web08"]
        original_path = list(path)  # copy
        review_learning_path(
            path=path,
            target_skill="web08",
            known_skills=["web01", "web02"],
            fetch_prerequisites=_fetch_prereqs,
        )
        assert path == original_path, "Path must not be mutated"

    def test_passed_true_means_no_warnings(self):
        """passed=True must always mean warnings is empty."""
        result = review_learning_path(
            path=["web03", "web04", "web05", "web07", "web08"],
            target_skill="web08",
            known_skills=["web01", "web02"],
            fetch_prerequisites=_fetch_prereqs,
        )
        if result.passed:
            assert result.warnings == [], (
                "passed=True must imply zero warnings"
            )

    def test_passed_false_means_has_warnings(self):
        """passed=False must always mean at least one warning exists."""
        result = review_learning_path(
            path=["web05", "web03"],
            target_skill="web03",
            known_skills=["web01", "web02"],
            fetch_prerequisites=_fetch_prereqs,
        )
        if not result.passed:
            assert len(result.warnings) > 0, (
                "passed=False must imply at least one warning"
            )

    def test_default_known_skills_is_empty(self):
        """When known_skills is omitted, it should default to empty."""
        result = review_learning_path(
            path=["web01"],
            target_skill="web01",
            fetch_prerequisites=_fetch_prereqs,
        )
        assert isinstance(result, SelfCritiqueResult)
