"""A complete XWaermeplan plan as a set of features, and checks across features."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Iterator

from fheat_core.xwp.model.base import (
    ERROR,
    REF,
    Issue,
    Ref,
    XwpDataType,
    XwpFeature,
    XwpObject,
    validate,
    values,
)


class XwpValidationError(ValueError):
    """A plan document has errors; ``issues`` lists them."""

    def __init__(self, issues: list[Issue]):
        self.issues = issues
        lines = "\n".join(f"  {i.path}: {i.message}" for i in issues[:20])
        more = f"\n  … und {len(issues) - 20} weitere" if len(issues) > 20 else ""
        super().__init__(f"XWärmeplan-Dokument hat {len(issues)} Fehler:\n{lines}{more}")


@dataclass
class XwpPlanDocument:
    """All features of one plan file: the plan, its areas and all plan contents.

    ``id`` is the UUID of the file itself (gml:id of the FeatureCollection).
    """

    features: list[XwpFeature] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def add(self, *features: XwpFeature) -> None:
        self.features.extend(features)

    def __iter__(self) -> Iterator[XwpFeature]:
        return iter(self.features)

    def by_id(self) -> dict[str, XwpFeature]:
        return {f.id: f for f in self.features}

    def of_type(self, name: str) -> list[XwpFeature]:
        return [f for f in self.features if type(f).__xwp__.is_a(name)]

    def ordered(self) -> list[XwpFeature]:
        """Plan, areas, features without geometry, then the others grouped by type (kodierung.md)."""

        def rank(item: tuple[int, XwpFeature]) -> tuple:
            i, f = item
            info = type(f).__xwp__
            if info.is_a("WP_Plan"):
                group = 0
            elif info.is_a("WP_Bereich"):
                group = 1
            elif info.geometry_attr is None:
                group = 2
            else:
                group = 3
            return (group, info.name if group >= 2 else "", i)

        return [f for _, f in sorted(enumerate(self.features), key=rank)]

    def link_reverse(self) -> None:
        """Add the missing reverse references (e.g. ``WP_Plan.bereich`` for ``WP_Bereich.gehoertZuPlan``)."""
        index = self.by_id()
        for f in self.features:
            for attr in type(f).__xwp__.attrs:
                if attr.kind != REF or not attr.reverse:
                    continue
                for v in values(f, attr):
                    target = index.get(v.id)
                    if target is None:
                        continue
                    back = type(target).__xwp__.attr(attr.reverse)
                    existing = {r.id for r in values(target, back)}
                    if f.id in existing:
                        continue
                    if back.many:
                        current = getattr(target, back.name)
                        if current is None:
                            setattr(target, back.name, [Ref.to(f)])
                        else:
                            current.append(Ref.to(f))
                    elif getattr(target, back.name) is None:
                        setattr(target, back.name, Ref.to(f))

    def validate(self) -> list[Issue]:
        """Check every feature and the references between them."""
        issues: list[Issue] = []
        index: dict[str, XwpFeature] = {}
        for f in self.features:
            if f.id in index:
                issues.append(Issue(f"{type(f).__name__}[{f.id}]", "id", f"id {f.id} kommt mehrfach vor."))
            index[f.id] = f
        if not self.of_type("WP_Plan"):
            issues.append(Issue("Dokument", "missing", "Das Dokument enthält keinen WP_Plan."))
        for f in self.features:
            path = f"{type(f).__name__}[{f.id}]"
            issues.extend(validate(f, path))
            issues.extend(self._check_refs(f, path, index))
        return issues

    def errors(self) -> list[Issue]:
        return [i for i in self.validate() if i.severity == ERROR]

    def check(self) -> None:
        """Raise :class:`XwpValidationError` if the document has errors."""
        errors = self.errors()
        if errors:
            raise XwpValidationError(errors)

    def _check_refs(self, obj: XwpObject, path: str, index: dict[str, XwpFeature]) -> list[Issue]:
        issues: list[Issue] = []
        for attr in type(obj).__xwp__.attrs:
            p = f"{path}.{attr.name}"
            for v in values(obj, attr):
                if isinstance(v, XwpDataType):
                    issues.extend(self._check_refs(v, p, index))
                if attr.kind != REF or not isinstance(v, (Ref, XwpFeature)):
                    continue
                target = index.get(v.id)
                if target is None:
                    issues.append(Issue(p, "ref", f"Verweis {attr.name} auf {v.id} zeigt auf kein Objekt im Dokument."))
                    continue
                tinfo = type(target).__xwp__
                if not tinfo.is_a(attr.type):
                    issues.append(Issue(p, "ref", f"{attr.name} muss auf {attr.type} verweisen, {v.id} ist {tinfo.name}."))
                    continue
                if attr.reverse and isinstance(obj, XwpFeature):
                    back = tinfo.attr(attr.reverse)
                    if obj.id not in {r.id for r in values(target, back)}:
                        issues.append(Issue(
                            p, "ref",
                            f"Gegenrichtung fehlt: {tinfo.name}.{back.name} verweist nicht auf {obj.id}.",
                        ))
        return issues
