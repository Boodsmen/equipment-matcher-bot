"""Tests for services/matcher.py — deduplication, matching, comparison."""

import pytest

from services.matcher import (
    _parse_version_priority,
    calculate_match_percentage,
    categorize_matches,
    compare_spec_values,
    compare_text_values,
    deduplicate_models,
    extract_number,
    extract_number_with_operator,
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


# ════════════════════════════════════════════════════════════════
# extract_number_with_operator
# ════════════════════════════════════════════════════════════════


class TestExtractNumberWithOperator:
    def test_ge_unicode(self):
        num, op = extract_number_with_operator("≥ 24")
        assert num == 24.0
        assert op == ">="

    def test_le_unicode(self):
        num, op = extract_number_with_operator("≤ 100")
        assert num == 100.0
        assert op == "<="

    def test_ge_ascii(self):
        num, op = extract_number_with_operator(">=24")
        assert num == 24.0
        assert op == ">="

    def test_le_ascii(self):
        num, op = extract_number_with_operator("<=100")
        assert num == 100.0
        assert op == "<="

    def test_gt(self):
        num, op = extract_number_with_operator("> 5")
        assert num == 5.0
        assert op == ">"

    def test_lt(self):
        num, op = extract_number_with_operator("< 50")
        assert num == 50.0
        assert op == "<"

    def test_eq(self):
        num, op = extract_number_with_operator("= 10")
        assert num == 10.0
        assert op == "="

    def test_ne(self):
        num, op = extract_number_with_operator("!= 0")
        assert num == 0.0
        assert op == "!="

    def test_plain_number_default_ge(self):
        num, op = extract_number_with_operator("24")
        assert num == 24.0
        assert op == ">="

    def test_integer_default_ge(self):
        num, op = extract_number_with_operator(24)
        assert num == 24.0
        assert op == ">="

    def test_float_default_ge(self):
        num, op = extract_number_with_operator(10.5)
        assert num == 10.5
        assert op == ">="

    def test_none_returns_none(self):
        num, op = extract_number_with_operator(None)
        assert num is None
        assert op == ">="

    def test_bool_returns_none(self):
        num, op = extract_number_with_operator(True)
        assert num is None

    def test_text_prefix_ne_menee(self):
        num, op = extract_number_with_operator("не менее 500")
        assert num == 500.0
        assert op == ">="

    def test_text_prefix_ne_bolee(self):
        num, op = extract_number_with_operator("не более 100")
        assert num == 100.0
        assert op == "<="

    def test_text_prefix_do(self):
        num, op = extract_number_with_operator("до 1000")
        assert num == 1000.0
        assert op == "<="

    def test_text_prefix_minimum(self):
        num, op = extract_number_with_operator("минимум 50")
        assert num == 50.0
        assert op == ">="

    def test_text_prefix_maximum(self):
        num, op = extract_number_with_operator("максимум 200")
        assert num == 200.0
        assert op == "<="


# ════════════════════════════════════════════════════════════════
# compare_spec_values with operators
# ════════════════════════════════════════════════════════════════


class TestCompareSpecValuesWithOperators:
    def test_le_operator_model_below(self):
        # ≤ 100: модель с 80 → True
        assert compare_spec_values("<=100", 80, "power_watt") is True

    def test_le_operator_model_equal(self):
        # ≤ 100: модель с 100 → True
        assert compare_spec_values("<=100", 100, "power_watt") is True

    def test_le_operator_model_above(self):
        # ≤ 100: модель с 120 → False
        assert compare_spec_values("<=100", 120, "power_watt") is False

    def test_ge_operator_model_above(self):
        # >= 24: модель с 48 → True
        assert compare_spec_values(">=24", 48, "ports_1g") is True

    def test_ge_operator_model_below(self):
        # >= 24: модель с 12 → False
        assert compare_spec_values(">=24", 12, "ports_1g") is False

    def test_eq_operator_match(self):
        assert compare_spec_values("=10", 10, "vlan_count") is True

    def test_eq_operator_mismatch(self):
        assert compare_spec_values("=10", 11, "vlan_count") is False

    def test_gt_operator(self):
        assert compare_spec_values(">5", 6, "x") is True
        assert compare_spec_values(">5", 5, "x") is False

    def test_lt_operator(self):
        assert compare_spec_values("<50", 49, "x") is True
        assert compare_spec_values("<50", 50, "x") is False

    def test_le_allow_lower_tolerance(self):
        # ≤ 100 with allow_lower: 105% = 105, model 104 → True
        assert compare_spec_values("<=100", 104, "power_watt", allow_lower=True) is True

    def test_le_allow_lower_too_high(self):
        # ≤ 100 with allow_lower: 105% = 105, model 110 → False
        assert compare_spec_values("<=100", 110, "power_watt", allow_lower=True) is False

    def test_backward_compat_plain_number(self):
        # Без оператора — дефолт >=, как и раньше
        assert compare_spec_values(24, 24, "ports") is True
        assert compare_spec_values(24, 48, "ports") is True
        assert compare_spec_values(24, 12, "ports") is False

    def test_unicode_le_string(self):
        # Unicode ≤ в строке
        assert compare_spec_values("≤100", 80, "power") is True
        assert compare_spec_values("≤100", 120, "power") is False

    def test_unicode_ge_string(self):
        assert compare_spec_values("≥24", 24, "ports") is True
        assert compare_spec_values("≥24", 12, "ports") is False


# ════════════════════════════════════════════════════════════════
# compare_text_values
# ════════════════════════════════════════════════════════════════


class TestCompareTextValues:
    def test_exact_match(self):
        assert compare_text_values("Layer 3", "Layer 3") is True

    def test_case_insensitive(self):
        assert compare_text_values("Layer 3", "layer 3") is True

    def test_partial_match_req_in_model(self):
        # "Управляемый" ⊂ "Управляемый L3"
        assert compare_text_values("Управляемый", "Управляемый L3") is True

    def test_partial_match_model_in_req(self):
        # Requirement "Управляемый L3" should NOT match model "Управляемый" —
        # the model does not specify L3, so the requirement is not satisfied.
        assert compare_text_values("Управляемый L3", "Управляемый") is False

    def test_boolean_yes_synonyms(self):
        assert compare_text_values("Да", "Есть") is True
        assert compare_text_values("yes", "поддерживается") is True

    def test_boolean_no_synonyms(self):
        assert compare_text_values("Нет", "Отсутствует") is True
        assert compare_text_values("no", "не поддерживается") is True

    def test_boolean_yes_vs_no(self):
        assert compare_text_values("Да", "Нет") is False

    def test_comma_separated_intersection(self):
        assert compare_text_values("OSPF, BGP", "RIP, OSPF, IS-IS") is True

    def test_comma_separated_no_intersection(self):
        assert compare_text_values("OSPF, BGP", "RIP, IS-IS") is False

    def test_no_match(self):
        assert compare_text_values("Layer 3", "Layer 2") is False

    def test_whitespace_handling(self):
        assert compare_text_values("  AC  ", "AC") is True


# ════════════════════════════════════════════════════════════════
# compare_spec_values with text (integration)
# ════════════════════════════════════════════════════════════════


class TestCompareSpecValuesText:
    def test_partial_match_via_compare_spec(self):
        # "Управляемый" should match "Управляемый L3" through compare_text_values
        assert compare_spec_values("Управляемый", "Управляемый L3", "type") is True

    def test_boolean_synonym_via_compare_spec(self):
        assert compare_spec_values("Да", "Есть", "feature") is True

    def test_string_mismatch_still_fails(self):
        assert compare_spec_values("Layer 3", "Layer 2", "type") is False


# ════════════════════════════════════════════════════════════════
# calculate_match_percentage with unmapped_specs
# ════════════════════════════════════════════════════════════════


class TestCalculateMatchPercentageUnmapped:
    def test_unmapped_specs_field_exists(self):
        required = {"ports_1g": 24, "unknown_key": 42}
        model = {"ports_1g": 24}
        result = calculate_match_percentage(required, model)
        assert "unmapped_specs" in result
        assert "unknown_key" in result["unmapped_specs"]

    def test_missing_specs_backward_compat(self):
        required = {"ports_1g": 24, "unknown_key": 42}
        model = {"ports_1g": 24}
        result = calculate_match_percentage(required, model)
        # missing_specs is an alias for unmapped_specs
        assert result["missing_specs"] == result["unmapped_specs"]

    def test_empty_required_has_unmapped(self):
        result = calculate_match_percentage({}, {"a": 1})
        assert result["unmapped_specs"] == []

    def test_all_unmapped(self):
        required = {"a": 1, "b": 2}
        model = {}
        result = calculate_match_percentage(required, model)
        assert len(result["unmapped_specs"]) == 2
        assert result["different_specs"] == {}

    def test_unmapped_vs_different_separation(self):
        required = {"ports_1g": 24, "power_watt": 200, "missing_key": 42}
        model = {"ports_1g": 24, "power_watt": 100}
        result = calculate_match_percentage(required, model)
        assert "ports_1g" in result["matched_specs"]
        assert "missing_key" in result["unmapped_specs"]
        assert "power_watt" in result["different_specs"]
