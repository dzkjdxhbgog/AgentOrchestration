"""Report export helpers."""

import csv
import io
import json
from typing import Any, Dict, Iterable, List, Optional, Sequence


FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def escape_csv_formula(value: Any) -> Any:
    """Neutralize spreadsheet formulas in string values written to CSV."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def _csv_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return escape_csv_formula(value)


def export_report_csv(
    rows: Iterable[Dict[str, Any]],
    fieldnames: Optional[Sequence[str]] = None,
) -> str:
    """Export report rows for spreadsheet-oriented CSV downloads.

    CSV output neutralizes string values that spreadsheet tools may interpret
    as formulas. Use ``export_report_json`` for structured exports that must
    preserve the original values exactly.
    """
    materialized_rows: List[Dict[str, Any]] = list(rows)
    if fieldnames is None:
        fieldnames = _infer_fieldnames(materialized_rows)

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=list(fieldnames),
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in materialized_rows:
        writer.writerow(
            {name: _csv_cell(row.get(name)) for name in fieldnames}
        )
    return output.getvalue()


def export_report_json(rows: Iterable[Dict[str, Any]]) -> str:
    """Export report rows as structured JSON without CSV-specific escaping."""
    return json.dumps(list(rows), ensure_ascii=False, separators=(",", ":"))


def _infer_fieldnames(rows: Sequence[Dict[str, Any]]) -> List[str]:
    fieldnames: List[str] = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fieldnames.append(key)
                seen.add(key)
    return fieldnames
