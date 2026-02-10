"""Tests for services/matcher.py — deduplication, matching, comparison."""

import pytest

from services.matcher import (
    _parse_version_priority,
    calculate_match_percentage,
    categorize_matches,
    compare_spec_values,
    deduplicate_models,
)
from tests.conftest import make_model


# ════════════════════════════════════════════════════════════════
# _parse_version_priority
# ════════════════════════════════════════════════════════════════


class TestParseVersionPriority:
    def test_finalUPD_with_version(self):
        assert _parse_version_priority("ESR-3100_finalUPDv.1.2.csv") == 1002

    def test_finalUPD_v1_1(self):
        assert _parse_version_priority("ESR-3100_finalUPDv.1.1.csv") == 1001

    def test_finalUPD_without_version(self):
        assert _parse_version_priority("ESR-3100_finalUPD.csv") == 1000

    def test_v33(self):
        assert _parse_version_priority("ESR-3100_v33.csv") == 33

    def test_v21(self):
        assert _parse_version_priority("MES3710P_v21.csv") == 21

    def test_v20(self):
        assert _parse_version_priority("MES3710P_v20.csv") == 20

    def test_v21_1(self):
        # vNN.M — основной приоритет по NN
        assert _parse_version_priority("ESR-3100_v21.1.csv") == 21

    def test_new_suffix_bonus(self):
        assert _parse_version_priority("MES3710P_v20_new.csv") == 20.5

    def test_new_suffix_with_finalUPD(self):
        assert _parse_version_priority("ESR_finalUPD_new.csv") == 1000.5

    def test_no_version(self):
        assert _parse_version_priority("MES3710P.csv") == 0

    def test_empty_string(self):
        assert _parse_version_priority("") == 0

    def test_none_source(self):
        assert _parse_version_priority(None) == 0

    def test_ordering_finalUPD_gt_v21(self):
        assert _parse_version_priority("finalUPD.csv") > _parse_version_priority("v21.csv")

    def test_ordering_v21_gt_v20(self):
        assert _parse_version_priority("v21.csv") > _parse_version_priority("v20.csv")

    def test_ordering_v20_gt_no_version(self):
        assert _parse_version_priority("v20.csv") > _parse_version_priority("plain.csv")


# ════════════════════════════════════════════════════════════════
# deduplicate_models
# ════════════════════════════════════════════════════════════════


class TestDeduplicateModels:
    def test_removes_empty_specs(self):
        models = [
            make_model("A", specifications={"port": 24}, model_id=1),
            make_model("B", specifications={}, model_id=2),
        ]
        result = deduplicate_models(models)
        assert len(result) == 1
        assert result[0].model_name == "A"

    def test_keeps_single_model(self):
        models = [make_model("A", specifications={"port": 24})]
        result = deduplicate_models(models)
        assert len(result) == 1

    def test_dedup_by_name_picks_more_specs(self):
        models = [
            make_model("ESR-3100", source_file="v20.csv", specifications={"a": 1}, model_id=1),
            make_model("ESR-3100", source_file="v21.csv", specifications={"a": 1, "b": 2, "c": 3}, model_id=2),
        ]
        result = deduplicate_models(models)
        assert len(result) == 1
        assert result[0].id == 2  # more specs wins

    def test_dedup_by_name_same_specs_picks_newer_version(self):
        spec = {"a": 1, "b": 2}
        models = [
            make_model("ESR-3100", source_file="v20.csv", specifications=spec, model_id=1),
            make_model("ESR-3100", source_file="v21.csv", specifications=spec, model_id=2),
        ]
        result = deduplicate_models(models)
        assert len(result) == 1
        assert result[0].id == 2  # v21 > v20

    def test_dedup_finalUPD_wins(self):
        spec = {"a": 1}
        models = [
            make_model("X", source_file="v33.csv", specifications=spec, model_id=1),
            make_model("X", source_file="finalUPD.csv", specifications=spec, model_id=2),
        ]
        result = deduplicate_models(models)
        assert len(result) == 1
        assert result[0].id == 2

    def test_different_names_not_deduped(self):
        spec = {"a": 1}
        models = [
            make_model("ESR-3100", specifications=spec, model_id=1),
            make_model("MES3710P", specifications=spec, model_id=2),
        ]
        result = deduplicate_models(models)
        assert len(result) == 2

    def test_empty_list(self):
        assert deduplicate_models([]) == []

    def test_all_empty_specs(self):
        models = [
            make_model("A", specifications={}, model_id=1),
            make_model("B", specifications={}, model_id=2),
        ]
        result = deduplicate_models(models)
        assert len(result) == 0

    def test_ten_duplicates_reduced_to_one(self):
        """Simulates ESR models duplicated across 10 CSV versions."""
        models = [
            make_model(
                "ESR-3100",
                source_file=f"ESR-3100_v{i}.csv",
                specifications={"port": 24, "power": 100} if i > 15 else {"port": 24},
                model_id=i,
            )
            for i in range(15, 25)
        ]
        result = deduplicate_models(models)
        assert len(result) == 1
        # Should pick the one with more specs + higher version
        assert len(result[0].specifications) == 2


# ════════════════════════════════════════════════════════════════
# compare_spec_values
# ════════════════════════════════════════════════════════════════


class TestCompareSpecValues:
    # Boolean tests
    def test_bool_true_match(self):
        assert compare_spec_values(True, True, "support_ospf") is True

    def test_bool_false_match(self):
        assert compare_spec_values(False, False, "support_ospf") is True

    def test_bool_mismatch(self):
        assert compare_spec_values(True, False, "support_ospf") is False

    def test_bool_truthy_int(self):
        assert compare_spec_values(True, 1, "support_ospf") is True

    # Numeric tests
    def test_numeric_equal(self):
        assert compare_spec_values(24, 24, "ports_1g") is True

    def test_numeric_model_higher(self):
        assert compare_spec_values(24, 48, "ports_1g") is True

    def test_numeric_model_lower_strict(self):
        assert compare_spec_values(24, 20, "ports_1g") is False

    def test_numeric_allow_lower_within_threshold(self):
        # 95% of 100 = 95, so 96 should pass
        assert compare_spec_values(100, 96, "power_watt", allow_lower=True) is True

    def test_numeric_allow_lower_below_threshold(self):
        # 95% of 100 = 95, so 90 should fail
        assert compare_spec_values(100, 90, "power_watt", allow_lower=True) is False

    def test_numeric_float(self):
        assert compare_spec_values(10.5, 10.5, "weight") is True

    def test_numeric_float_higher(self):
        assert compare_spec_values(10.0, 12.5, "weight") is True

    # String tests
    def test_string_exact_match(self):
        assert compare_spec_values("Layer 3", "Layer 3", "type") is True

    def test_string_case_insensitive(self):
        assert compare_spec_values("Layer 3", "layer 3", "type") is True

    def test_string_whitespace(self):
        assert compare_spec_values("Layer 3", "  Layer 3  ", "type") is True

    def test_string_mismatch(self):
        assert compare_spec_values("Layer 3", "Layer 2", "type") is False

    # None / missing
    def test_model_value_none(self):
        assert compare_spec_values(24, None, "ports") is False

    def test_both_none(self):
        # required_value is not None check is not done, model_value=None → False
        assert compare_spec_values(None, None, "x") is False

    # Mixed types
    def test_fallback_equality(self):
        assert compare_spec_values([1, 2], [1, 2], "list_field") is True

    def test_fallback_inequality(self):
        assert compare_spec_values([1, 2], [1, 3], "list_field") is False


# ════════════════════════════════════════════════════════════════
# calculate_match_percentage
# ════════════════════════════════════════════════════════════════


class TestCalculateMatchPercentage:
    def test_100_percent(self):
        required = {"ports_1g": 24, "power_watt": 200}
        model = {"ports_1g": 24, "power_watt": 200}
        result = calculate_match_percentage(required, model)
        assert result["match_percentage"] == 100.0
        assert len(result["matched_specs"]) == 2
        assert result["missing_specs"] == []
        assert result["different_specs"] == {}

    def test_50_percent(self):
        required = {"ports_1g": 24, "power_watt": 200}
        model = {"ports_1g": 24, "power_watt": 100}
        result = calculate_match_percentage(required, model)
        assert result["match_percentage"] == 50.0
        assert "ports_1g" in result["matched_specs"]
        assert "power_watt" in result["different_specs"]

    def test_0_percent_all_missing(self):
        required = {"ports_1g": 24, "power_watt": 200}
        model = {}
        result = calculate_match_percentage(required, model)
        assert result["match_percentage"] == 0.0
        assert len(result["missing_specs"]) == 2

    def test_0_percent_all_different(self):
        required = {"ports_1g": 24}
        model = {"ports_1g": 10}
        result = calculate_match_percentage(required, model)
        assert result["match_percentage"] == 0.0

    def test_empty_required(self):
        result = calculate_match_percentage({}, {"a": 1})
        assert result["match_percentage"] == 100.0

    def test_missing_spec(self):
        required = {"ports_1g": 24, "poe": True}
        model = {"ports_1g": 24}
        result = calculate_match_percentage(required, model)
        assert result["match_percentage"] == 50.0
        assert "poe" in result["missing_specs"]

    def test_different_spec_details(self):
        required = {"ports_1g": 24}
        model = {"ports_1g": 12}
        result = calculate_match_percentage(required, model)
        assert result["different_specs"]["ports_1g"] == (24, 12)

    def test_allow_lower(self):
        required = {"power_watt": 200}
        model = {"power_watt": 195}
        result = calculate_match_percentage(required, model, allow_lower=True)
        assert result["match_percentage"] == 100.0


# ════════════════════════════════════════════════════════════════
# categorize_matches
# ════════════════════════════════════════════════════════════════


class TestCategorizeMatches:
    def _match(self, name: str, pct: float) -> dict:
        return {"model_name": name, "match_percentage": pct}

    def test_ideal(self):
        matches = [self._match("A", 100.0)]
        result = categorize_matches(matches)
        assert len(result["ideal"]) == 1
        assert len(result["partial"]) == 0
        assert len(result["not_matched"]) == 0

    def test_partial(self):
        matches = [self._match("A", 85.0)]
        result = categorize_matches(matches)
        assert len(result["partial"]) == 1

    def test_not_matched(self):
        matches = [self._match("A", 50.0)]
        result = categorize_matches(matches)
        assert len(result["not_matched"]) == 1

    def test_boundary_70(self):
        matches = [self._match("A", 70.0)]
        result = categorize_matches(matches)
        assert len(result["partial"]) == 1

    def test_boundary_69(self):
        matches = [self._match("A", 69.9)]
        result = categorize_matches(matches)
        assert len(result["not_matched"]) == 1

    def test_custom_threshold(self):
        matches = [self._match("A", 50.0)]
        result = categorize_matches(matches, threshold=50)
        assert len(result["partial"]) == 1

    def test_sorting_partial(self):
        matches = [self._match("A", 75.0), self._match("B", 90.0)]
        result = categorize_matches(matches)
        assert result["partial"][0]["model_name"] == "B"

    def test_sorting_ideal_by_name(self):
        matches = [self._match("B", 100.0), self._match("A", 100.0)]
        result = categorize_matches(matches)
        assert result["ideal"][0]["model_name"] == "A"

    def test_empty_matches(self):
        result = categorize_matches([])
        assert result["ideal"] == []
        assert result["partial"] == []
        assert result["not_matched"] == []

    def test_mixed(self):
        matches = [
            self._match("A", 100.0),
            self._match("B", 85.0),
            self._match("C", 50.0),
        ]
        result = categorize_matches(matches)
        assert len(result["ideal"]) == 1
        assert len(result["partial"]) == 1
        assert len(result["not_matched"]) == 1
