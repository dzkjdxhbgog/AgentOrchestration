import csv
import io
import json

from src.common.reports import export_report_csv, export_report_json


def parse_csv(text):
    return list(csv.DictReader(io.StringIO(text)))


def test_csv_escapes_common_formula_leading_characters():
    rows = [
        {"id": "1", "value": "=SUM(A1:A2)"},
        {"id": "2", "value": "+cmd"},
        {"id": "3", "value": "-10+20"},
        {"id": "4", "value": "@HYPERLINK"},
        {"id": "5", "value": "\t=1+1"},
        {"id": "6", "value": "\r=1+1"},
    ]

    exported = parse_csv(export_report_csv(rows, fieldnames=["id", "value"]))

    assert [row["value"] for row in exported] == [
        "'=SUM(A1:A2)",
        "'+cmd",
        "'-10+20",
        "'@HYPERLINK",
        "'\t=1+1",
        "'\r=1+1",
    ]


def test_csv_leaves_safe_values_and_numbers_unchanged():
    rows = [
        {"name": "normal text", "amount": 42, "empty": None},
        {
            "name": " leading space =not-a-leading-formula",
            "amount": 0,
            "empty": None,
        },
    ]

    exported = parse_csv(
        export_report_csv(rows, fieldnames=["name", "amount", "empty"])
    )

    assert exported == [
        {"name": "normal text", "amount": "42", "empty": ""},
        {
            "name": " leading space =not-a-leading-formula",
            "amount": "0",
            "empty": "",
        },
    ]


def test_csv_serializes_nested_values_before_spreadsheet_export():
    rows = [{"id": "row-1", "metadata": {"formula": "=kept-as-json-value"}}]

    exported = parse_csv(export_report_csv(rows))

    assert exported[0]["metadata"] == '{"formula": "=kept-as-json-value"}'


def test_json_export_preserves_original_formula_like_values():
    rows = [
        {"id": "1", "value": "=SUM(A1:A2)"},
        {"id": "2", "value": "+cmd"},
        {"id": "3", "value": "-10+20"},
        {"id": "4", "value": "@HYPERLINK"},
    ]

    exported = json.loads(export_report_json(rows))

    assert exported == rows
