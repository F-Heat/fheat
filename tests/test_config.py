"""Tests for fheat_core.config.FHeatConfig.

Covers:
- default values are sane
- supply > return temperature invariant is enforced
- output_format whitelist is enforced
- valid configurations construct successfully
"""
from __future__ import annotations

import pytest

from fheat_core.config import FHeatConfig


class TestDefaults:
    def test_default_construction_succeeds(self):
        cfg = FHeatConfig()
        assert cfg.supply_temperature == 80.0
        assert cfg.return_temperature == 50.0
        assert cfg.wld_threshold == 500.0
        assert cfg.buffer_distance == 50.0
        assert cfg.building_class == 3
        assert cfg.wind_class == 1
        assert cfg.year == 2022
        assert cfg.output_dir == "./output"
        assert cfg.output_format == "gpkg"

    def test_supply_strictly_greater_than_return(self):
        cfg = FHeatConfig()
        assert cfg.supply_temperature > cfg.return_temperature


class TestTemperatureInvariant:
    def test_supply_equal_return_raises(self):
        with pytest.raises(ValueError, match="supply_temperature"):
            FHeatConfig(supply_temperature=70.0, return_temperature=70.0)

    def test_supply_below_return_raises(self):
        with pytest.raises(ValueError, match="supply_temperature"):
            FHeatConfig(supply_temperature=40.0, return_temperature=60.0)

    def test_supply_just_above_return_succeeds(self):
        cfg = FHeatConfig(supply_temperature=60.001, return_temperature=60.0)
        assert cfg.supply_temperature > cfg.return_temperature


class TestOutputFormat:
    @pytest.mark.parametrize("fmt", ["gpkg", "fgb", "geojson", "gml"])
    def test_allowed_formats_succeed(self, fmt):
        cfg = FHeatConfig(output_format=fmt)
        assert cfg.output_format == fmt

    @pytest.mark.parametrize("fmt", ["shp", "csv", "GPKG", "", "json"])
    def test_disallowed_formats_raise(self, fmt):
        with pytest.raises(ValueError, match="output_format"):
            FHeatConfig(output_format=fmt)


class TestCustomConfig:
    def test_full_custom_config(self, tmp_path):
        cfg = FHeatConfig(
            supply_temperature=95.0,
            return_temperature=65.0,
            wld_threshold=750.0,
            buffer_distance=25.0,
            building_class=2,
            wind_class=0,
            year=2030,
            output_dir=str(tmp_path),
            output_format="geojson",
        )
        assert cfg.supply_temperature == 95.0
        assert cfg.year == 2030
        assert cfg.output_dir == str(tmp_path)
