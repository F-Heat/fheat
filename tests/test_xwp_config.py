"""XWPExportConfig and the Regionalschlüssel rule; no xplan-tools needed."""
from __future__ import annotations

import datetime

import pytest

from fheat_core.export.xwp import XWPExportConfig, regional_key

PLAN_ID = "6a2f41a3-c54c-4ce8-92d2-0324e1c32e22"


def plan_config(**overrides) -> XWPExportConfig:
    values = dict(
        plan_name="Wärmeplan Steinfurt",
        municipality_name="Steinfurt",
        municipality_key="05566084",
        base_year=2022,
        decision_date=datetime.date(2026, 6, 30),
    )
    values.update(overrides)
    return XWPExportConfig(**values)


class TestRegionalKey:
    @pytest.mark.parametrize("ags, rs", [
        ("05566084", "055660084084"),   # Steinfurt, kreisangehörig
        ("5566084", "055660084084"),    # cities.csv drops the leading zero
        (5566084, "055660084084"),
        ("05515000", "055150000000"),   # Münster, kreisfrei
        ("05962008", "059620008008"),   # Balve
    ])
    def test_verbandsfreie_gemeinde_repeats_its_code(self, ags, rs):
        assert regional_key(ags) == rs

    @pytest.mark.parametrize("ags", ["", "0556608x", "055660840"])
    def test_malformed_ags_raises(self, ags):
        with pytest.raises(ValueError):
            regional_key(ags)


class TestPlanMode:
    def test_defaults(self):
        config = plan_config()
        assert config.resolved_regional_key == "055660084084"
        assert (config.procedure, config.legal_basis, config.target_year) == ("1000", "1000", 2045)
        assert (config.network_status, config.network_medium, config.supply_type) == ("3000", "1000", "40001")
        assert config.supply_area_class == "WP_WaermeversorgungsgebietZieljahr"

    def test_regional_key_overrides_the_derived_one(self):
        assert plan_config(regional_key="073355003022").resolved_regional_key == "073355003022"

    @pytest.mark.parametrize("missing", ["plan_name", "municipality_name", "base_year", "decision_date"])
    def test_mandatory_plan_attributes(self, missing):
        with pytest.raises(ValueError, match=missing):
            plan_config(**{missing: None})

    def test_needs_a_municipality_key(self):
        with pytest.raises(ValueError, match="municipality_key"):
            plan_config(municipality_key=None)

    def test_decision_date_as_iso_string(self):
        assert plan_config(decision_date="2026-06-30").decision_date == datetime.date(2026, 6, 30)

    @pytest.mark.parametrize("field, code", [
        ("procedure", "9999"), ("legal_basis", "4000"), ("network_status", "4000"),
        ("network_medium", "5000"), ("supply_type", "9999"), ("source_energy_carrier", "1"),
    ])
    def test_unknown_codes_raise(self, field, code):
        with pytest.raises(ValueError, match="is not a code of"):
            plan_config(**{field: code})

    def test_codes_as_numbers(self):
        assert plan_config(supply_type=1000, source_energy_carrier=72002).supply_type == "1000"

    @pytest.mark.parametrize("year, cls", [
        ("zieljahr", "WP_WaermeversorgungsgebietZieljahr"),
        ("2035", "WP_WaermeversorgungsgebietStuetzjahr"),
        (2040, "WP_WaermeversorgungsgebietStuetzjahr"),
    ])
    def test_supply_year_picks_the_class(self, year, cls):
        assert plan_config(supply_year=year).supply_area_class == cls

    @pytest.mark.parametrize("year", ["2045", "2025", ""])
    def test_unknown_supply_year_raises(self, year):
        with pytest.raises(ValueError, match="supply_year"):
            plan_config(supply_year=year)

    @pytest.mark.parametrize("bounds", [(70, 175, 415), (415, 175), (415, 175, -1)])
    def test_thresholds_must_descend(self, bounds):
        with pytest.raises(ValueError, match="suitability_thresholds"):
            plan_config(suitability_thresholds=bounds)

    def test_no_suitability_proposal_by_default(self):
        assert plan_config().suitability_thresholds is None
        assert plan_config(suitability_thresholds=[415, 175, 70]).suitability_thresholds == (415.0, 175.0, 70.0)

    @pytest.mark.parametrize("overrides", [{}, {"source_energy_carrier": "72002", "supply_year": "2030",
                                                "suitability_thresholds": (415, 175, 70)}])
    def test_round_trip_through_dict(self, overrides):
        config = plan_config(**overrides)
        assert XWPExportConfig.from_dict(config.to_dict()) == config

    def test_unknown_dict_keys_raise(self):
        with pytest.raises(ValueError, match="unknown"):
            XWPExportConfig.from_dict({**plan_config().to_dict(), "gemeinde": "x"})


class TestFragmentMode:
    def test_needs_no_plan_attributes(self):
        config = XWPExportConfig(mode="fragment", plan_id=PLAN_ID.upper(), municipality_key="05566084")
        assert config.plan_id == PLAN_ID

    @pytest.mark.parametrize("plan_id", [None, ""])
    def test_plan_id_is_optional(self, plan_id):
        assert XWPExportConfig(mode="fragment", plan_id=plan_id, municipality_key="05566084").plan_id is None

    def test_plan_id_must_be_a_uuid(self):
        with pytest.raises(ValueError, match="not a UUID"):
            XWPExportConfig(mode="fragment", plan_id="plan-1", municipality_key="05566084")


def test_network_buffer_defaults_to_the_calculation():
    from fheat_core.config import FHeatConfig

    assert plan_config().resolved_network_buffer == FHeatConfig().buffer_distance
    assert plan_config(network_buffer=10.0).resolved_network_buffer == 10.0
    with pytest.raises(ValueError, match="network_buffer"):
        plan_config(network_buffer=0)


def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="mode"):
        plan_config(mode="draft")


def test_nrw_adapter_gives_the_municipality_key_without_download():
    from fheat_nrw.adapter.data_adapter import NRWDataAdapter

    adapter = NRWDataAdapter(city_name="Burgsteinfurt")
    assert adapter.municipality_key == "05566084"
    assert regional_key(adapter.municipality_key) == "055660084084"
