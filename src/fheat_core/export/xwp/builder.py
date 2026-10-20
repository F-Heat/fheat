"""Feature records -> xplan-tools models and their collection.

Thin wrapper around xplan-tools: sets the ids and the references between
plan, area and map features and lets xplan-tools check fields, code lists
and references. Imports xplan-tools only when called.
"""
from __future__ import annotations

import uuid
from typing import Sequence

import shapely

from fheat_core.export.xwp import mapping
from fheat_core.export.xwp.config import XWPExportConfig
from fheat_core.export.xwp.mappers import plan_key
from fheat_core.export.xwp.report import Issue

#: Namespace of the feature ids: uuid5(ID_NAMESPACE, "<RS>/<feature type>/<F|Heat key>")
ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/F-Heat/fheat/xwaermeplan")
COORDINATE_DECIMALS = 3  # mm


def feature_id(regional_key: str, featuretype: str, key: str) -> uuid.UUID:
    return uuid.uuid5(ID_NAMESPACE, f"{regional_key}/{featuretype}/{key}")


def appschema():
    from xplan_tools.model.base import Appschema

    return Appschema.from_prefix(*mapping.APPSCHEMA)


def build_collection(records: Sequence[dict], config: XWPExportConfig, srid: int):
    """``(collection, issues)``: the xplan-tools BaseCollection, or None with the reasons.

    Every record is validated on its own, so one run reports all invalid
    features. In mode "fragment" the area refers to the municipality's plan,
    which is not in the collection; xplan-tools' reference check would
    reject that, so the collection is assembled without it.
    """
    from pydantic import ValidationError
    from xplan_tools.model.base import BaseCollection

    schema = appschema()
    rs = config.resolved_regional_key
    plan_id = (
        feature_id(rs, "WP_Plan", plan_key(config)) if config.mode == "plan" else uuid.UUID(config.plan_id)
    )
    bereich = next(r for r in records if r["featuretype"] == "WP_Bereich")
    bereich_id = feature_id(rs, "WP_Bereich", bereich["key"])

    features, issues, seen = {}, [], set()
    for record in records:
        featuretype, key = record["featuretype"], record["key"]
        fid = feature_id(rs, featuretype, key)
        n = 1
        while fid in seen:  # e.g. two street segments with the same geometry
            n += 1
            fid = feature_id(rs, featuretype, f"{key}#{n}")
        seen.add(fid)
        data = {"id": fid, **record["properties"]}
        if record["geometry"] is not None:
            data[record["geometry_property"]] = {
                "srid": srid,
                "wkt": shapely.to_wkt(record["geometry"], rounding_precision=COORDINATE_DECIMALS, trim=True),
            }
        if featuretype == "WP_Plan":
            data["bereich"] = [bereich_id]
        elif featuretype == "WP_Bereich":
            data["gehoertZuPlan"] = plan_id
        else:
            data["gehoertZuBereich"] = bereich_id
        try:
            feature = schema.model_factory(featuretype).model_validate(data)
        except ValidationError as exc:
            issues.extend(
                Issue("structure", f"{featuretype} {key}", f"{'.'.join(map(str, err['loc']))}: {err['msg']}")
                for err in exc.errors()
            )
            continue
        features[feature.id] = feature
    if issues:
        return None, issues

    if config.mode == "fragment":
        return BaseCollection.model_construct(features=features, srid=srid, appschema=schema), []
    try:
        return BaseCollection.from_features(features, srid=srid, appschema=schema), []
    except ValueError as exc:
        return None, [Issue("structure", None, str(exc))]
