"""Optional export of the non-geographic result tables (CSV or Excel).

Used by :meth:`FHeatOrchestrator.save_outputs` when ``FHeatConfig.table_format``
is set. With ``translate`` the columns get the German display labels, exactly
like the geodata export.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from fheat_core import columns as cols
from fheat_core.state import PipelineState

logger = logging.getLogger(__name__)

XLSX_FILENAME = "fheat-ergebnisse.xlsx"
XLSX_KEY = "ergebnisse_xlsx"

# (file stem / key, Excel sheet name) in output order
_TABLES = (
    ("ergebnisuebersicht", "Übersicht"),
    ("rohrmengen", "Rohre"),
    ("gebaeude_lastprofil", "Statistiken"),
    ("lastprofil", "Lastprofil"),
)

# Sheets that get a bold total row in the workbook, like the QGIS plugin's
# "Gesamt" line. CSV files stay without it so they remain plain data.
_TOTAL_ROW_TABLES = frozenset({"rohrmengen", "gebaeude_lastprofil"})

_EXCEL_HINT = 'table_format="xlsx" requires openpyxl. Install it with: pip install "fheat[excel]"'


def collect_tables(state: PipelineState, translate: bool) -> dict[str, pd.DataFrame]:
    """Result tables that exist in ``state``, keyed by file stem."""
    tables: dict[str, pd.DataFrame] = {}
    if state.result_summary is not None:
        labels = cols.SUMMARY_LABELS_DE if translate else {}
        key_column, value_column = ("Kennzahl", "Wert") if translate else ("key", "value")
        tables["ergebnisuebersicht"] = pd.DataFrame(
            [(labels.get(key, key), value) for key, value in state.result_summary.items()],
            columns=[key_column, value_column],
        )
    if state.pipe_summary_df is not None:
        tables["rohrmengen"] = state.pipe_summary_df
    if state.building_summary_df is not None:
        tables["gebaeude_lastprofil"] = state.building_summary_df
    if state.load_profile_df is not None:
        tables["lastprofil"] = state.load_profile_df.rename_axis("Zeit" if translate else "time").reset_index()

    if translate:
        tables = {name: cols.to_display(frame) for name, frame in tables.items()}
    return tables


def _excel_safe(frame: pd.DataFrame) -> pd.DataFrame:
    """Excel cannot store timezone-aware datetimes."""
    result = frame.copy()
    for column in result.columns:
        if isinstance(result[column].dtype, pd.DatetimeTZDtype):
            result[column] = result[column].dt.tz_localize(None)
    return result


def with_total_row(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    """Append a row with ``label`` in the first column and the column sums.

    Only numeric columns are summed; other columns stay empty.
    """
    first, *rest = frame.columns
    totals = {column: frame[column].sum() for column in rest if pd.api.types.is_numeric_dtype(frame[column])}
    total = pd.DataFrame([{first: label, **totals}], columns=frame.columns)
    return pd.concat([frame.astype({first: object}), total], ignore_index=True)


def write_tables(
    state: PipelineState,
    out_dir: str | Path,
    table_format: str | None,
    translate: bool,
) -> dict[str, str]:
    """Write the result tables and return ``{key: path}`` of the written files.

    ``table_format=None`` writes nothing. ``"csv"`` writes one UTF-8 file per
    table, ``"xlsx"`` one workbook with a sheet per table; the pipe and
    building sheets end with a bold total row. Tables not yet in the state
    (before the RESULTS step) are skipped.
    """
    if table_format is None:
        return {}
    tables = collect_tables(state, translate)
    if not tables:
        return {}
    out_dir = Path(out_dir)

    if table_format == "csv":
        saved = {}
        for name, _ in _TABLES:
            if name in tables:
                path = out_dir / f"{name}.csv"
                tables[name].to_csv(path, index=False, encoding="utf-8")
                saved[name] = str(path)
                logger.info("Saved %s → %s", name, path)
        return saved

    if table_format == "xlsx":
        try:
            from openpyxl.styles import Font
        except ImportError as exc:
            raise ImportError(_EXCEL_HINT) from exc
        total_label = "Gesamt" if translate else "total"
        path = out_dir / XLSX_FILENAME
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            for name, sheet in _TABLES:
                if name not in tables:
                    continue
                frame = _excel_safe(tables[name])
                if name in _TOTAL_ROW_TABLES:
                    frame = with_total_row(frame, total_label)
                frame.to_excel(writer, sheet_name=sheet, index=False)
                if name in _TOTAL_ROW_TABLES:
                    worksheet = writer.sheets[sheet]
                    for cell in worksheet[worksheet.max_row]:
                        cell.font = Font(bold=True)
        logger.info("Saved result tables → %s", path)
        return {XLSX_KEY: str(path)}

    raise ValueError(f"table_format '{table_format}' is not allowed. Allowed values: None, 'csv', 'xlsx'")
