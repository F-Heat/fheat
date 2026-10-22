"""Configuration of the XWaermeplan export.

Kept apart from :class:`fheat_core.config.FHeatConfig`, which holds only
calculation parameters: everything here is input F|Heat does not compute,
the plan metadata of WP_Plan and the codes the municipality decides.
"""
from __future__ import annotations

import dataclasses
import datetime
import uuid
from dataclasses import dataclass
from typing import Any, ClassVar, Optional

from fheat_core.config import FHeatConfig
from fheat_core.export.xwp import mapping


@dataclass
class XWPExportConfig:
    """What the XWaermeplan export writes beyond the F|Heat results.

    ``mode="plan"`` writes a complete WP_Plan with one WP_Bereich and needs
    every mandatory plan attribute, the decision date included (XWaermeplan
    0.9.6). ``mode="fragment"`` writes only the WP_Bereich and the map
    features, for merging into the municipality's plan ``plan_id``; that is
    the way for a draft that has no decision date yet. Without ``plan_id``
    the area refers to an id derived from the Regionalschlüssel, which the
    municipality replaces when merging.
    """

    # --- WP_Plan -----------------------------------------------------------
    plan_name: str = ""                          # WP_Plan.name, e.g. "Wärmeplan Steinfurt"
    municipality_name: str = ""                  # WP_Gemeinde.name of the responsible body
    municipality_key: Optional[str] = None       # AGS (8 digits); the RS is derived from it
    regional_key: Optional[str] = None           # RS (12 digits); overrides the derived one
    procedure: str = "1000"                      # WP_VerfahrenArt, 1000 Regelverfahren
    legal_basis: str = "1000"                    # WP_GesetzlicheGrundlage, 1000 WPG
    target_year: int = 2045                      # WP_Plan.zieljahr
    base_year: Optional[int] = None              # WP_Plan.basisJahrDatenerfassung
    decision_date: Optional[datetime.date] = None  # WP_Plan.beschlussDatum

    # --- what is written --------------------------------------------------
    mode: str = "plan"                           # "plan" | "fragment"
    plan_id: Optional[str] = None                # fragment: UUID of the municipality's WP_Plan, optional
    area_number: int = 0                         # WP_Bereich.nummer
    area_name: str = "F|Heat"                    # WP_Bereich.name

    # --- WP_Waermenetz ----------------------------------------------------
    network_status: str = "3000"                 # WP_Status, 3000 potenziell
    network_medium: str = "1000"                 # WP_Transportmedium, 1000 Wasser
    # m around every edge of a network (route, house and source connections);
    # None = buffer_distance of the default FHeatConfig. Pass the calculation's
    # own buffer_distance when it differs.
    network_buffer: Optional[float] = None
    # WP_Energietraeger of the heat source. Set, eeNachEnergietraeger gets the
    # heat fed into the network (demand + losses). The schema describes the
    # attribute for existing networks; None = not written.
    source_energy_carrier: Optional[str] = None

    # --- supply areas (from the suitability polygons) ---------------------
    supply_type: str = "40001"                   # WP_WaermeversorgungsgebietTyp, 40001 Prüfgebiet Wärmenetz
    supply_year: str = "zieljahr"                # "zieljahr" or the interim year "2030", "2035", "2040"
    # Lower bounds of the eignungWaermenetz stages 1000/2000/3000 for the heat
    # demand density [MWh/(ha·a)], descending; below the last: 4000, e.g.
    # (415, 175, 70) after the KEA-BW guideline. None = no eignungWaermenetz:
    # the suitability polygons are buffered and dissolved parcels, so their
    # density is not the block density the guideline thresholds refer to
    # (Burgsteinfurt: the whole network area gets 132 MWh/(ha·a)).
    suitability_thresholds: Optional[tuple[float, float, float]] = None

    _MODES: ClassVar[frozenset] = frozenset({"plan", "fragment"})

    def __post_init__(self) -> None:
        if self.mode not in self._MODES:
            raise ValueError(f"mode {self.mode!r} is not allowed. Allowed values: {sorted(self._MODES)}")
        self.procedure = mapping.check_code("WP_VerfahrenArt", self.procedure)
        self.legal_basis = mapping.check_code("WP_GesetzlicheGrundlage", self.legal_basis)
        self.network_status = mapping.check_code("WP_Status", self.network_status)
        self.network_medium = mapping.check_code("WP_Transportmedium", self.network_medium)
        self.supply_type = mapping.check_code("WP_WaermeversorgungsgebietTyp", self.supply_type)
        if self.source_energy_carrier is not None:
            self.source_energy_carrier = mapping.check_code("WP_Energietraeger", self.source_energy_carrier)
        self.supply_year = str(self.supply_year).lower()
        if self.supply_year not in mapping.SUPPLY_AREA_CLASS:
            raise ValueError(
                f"supply_year {self.supply_year!r} is not allowed. Allowed values: {list(mapping.SUPPLY_AREA_CLASS)}"
            )
        if self.suitability_thresholds is not None:
            bounds = tuple(float(b) for b in self.suitability_thresholds)
            if len(bounds) != 3 or not bounds[0] > bounds[1] > bounds[2] >= 0:
                raise ValueError(f"suitability_thresholds needs three descending bounds >= 0, got {bounds}.")
            self.suitability_thresholds = bounds
        if self.network_buffer is not None and not self.network_buffer > 0:
            raise ValueError("network_buffer must be > 0.")
        if isinstance(self.decision_date, str):
            self.decision_date = datetime.date.fromisoformat(self.decision_date)
        if self.regional_key is not None:
            self.regional_key = str(self.regional_key).strip()
            if len(self.regional_key) != 12 or not self.regional_key.isdigit():
                raise ValueError(f"regional_key {self.regional_key!r} is not a 12-digit Regionalschlüssel.")
        elif self.municipality_key is not None:
            mapping.regional_key(self.municipality_key)  # raises for a malformed AGS
        if self.resolved_regional_key is None:
            raise ValueError(
                "The export needs municipality_key (AGS) or regional_key (RS); the feature ids derive from it."
            )
        if self.mode == "plan":
            missing = [name for name in ("plan_name", "municipality_name", "base_year", "decision_date")
                       if getattr(self, name) in (None, "")]
            if missing:
                raise ValueError(
                    f"mode 'plan' needs {', '.join(missing)} (mandatory in WP_Plan); "
                    "without a decision date use mode 'fragment'."
                )
        elif self.plan_id not in (None, ""):
            try:
                self.plan_id = str(uuid.UUID(str(self.plan_id)))
            except ValueError:
                raise ValueError(f"plan_id {self.plan_id!r} is not a UUID.") from None
        else:
            self.plan_id = None

    @property
    def resolved_regional_key(self) -> Optional[str]:
        """The RS of the responsible municipality: ``regional_key`` or derived from the AGS."""
        if self.regional_key is not None:
            return self.regional_key
        if self.municipality_key is not None:
            return mapping.regional_key(self.municipality_key)
        return None

    @property
    def resolved_network_buffer(self) -> float:
        """``network_buffer``, else ``buffer_distance`` of the default FHeatConfig."""
        return self.network_buffer if self.network_buffer is not None else FHeatConfig().buffer_distance

    @property
    def supply_area_class(self) -> str:
        return mapping.SUPPLY_AREA_CLASS[self.supply_year]

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible values (dates as ISO strings, tuples as lists)."""
        out = dataclasses.asdict(self)
        out["decision_date"] = self.decision_date.isoformat() if self.decision_date else None
        if self.suitability_thresholds is not None:
            out["suitability_thresholds"] = list(self.suitability_thresholds)
        return out

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "XWPExportConfig":
        """Inverse of :meth:`to_dict`; unknown keys raise."""
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(f"unknown XWPExportConfig fields: {', '.join(unknown)}")
        return cls(**values)
