"""Tests for fheat_core.algorithms.civil_cost.cost_multiplier."""
from __future__ import annotations

import numpy as np
import pytest

from fheat_core.algorithms.civil_cost import cost_multiplier


@pytest.mark.parametrize("factor", [0.5, 1.0, 1.15, 3.0])
def test_zero_share_ignores_the_factor(factor):
    assert cost_multiplier(factor, 0.0) == pytest.approx(1.0)


@pytest.mark.parametrize("factor", [0.5, 1.0, 1.15, 3.0])
def test_full_share_is_the_factor(factor):
    assert cost_multiplier(factor, 1.0) == pytest.approx(factor)


@pytest.mark.parametrize("share", [0.0, 0.3, 0.6, 1.0])
def test_neutral_factor_gives_one(share):
    assert cost_multiplier(1.0, share) == pytest.approx(1.0)


def test_example_value():
    assert cost_multiplier(1.15, 0.6) == pytest.approx(1.09)


def test_scalar_in_scalar_out_and_array_in_array_out():
    assert isinstance(cost_multiplier(1.2, 0.5), float)
    out = cost_multiplier(np.array([1.0, 2.0]), 0.5)
    assert isinstance(out, np.ndarray)
    assert out.tolist() == pytest.approx([1.0, 1.5])
