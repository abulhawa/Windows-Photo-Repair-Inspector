import json
from pathlib import Path

from photo_repair.core import (
    MediaRecord,
    WRITABLE_TAKEN_EXTENSIONS,
    derive_proposed_taken,
    detect_issues,
    extract_date_from_filename,
    extract_fb_epoch_from_filename,
)
from photo_repair.ui import REPAIR_METHODS, _selection_range


CONTRACT_PATH = Path(__file__).parents[1] / "spec" / "behavior-contract.json"


def load_contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_constants_match_python_reference():
    contract = load_contract()
    assert set(contract["writable_taken_extensions"]) == WRITABLE_TAKEN_EXTENSIONS
    assert [
        {"label": label, "target": target, "source": source}
        for label, (target, source) in REPAIR_METHODS.items()
    ] == contract["repair_methods"]


def test_contract_filename_parsing_cases_match_python_reference():
    contract = load_contract()
    for case in contract["filename_parsing_cases"]:
        assert extract_date_from_filename(case["filename"]) == case["expected"], case["name"]


def test_contract_epoch_cases_match_python_reference():
    contract = load_contract()
    for case in contract["epoch_filename_cases"]:
        result = extract_fb_epoch_from_filename(case["filename"])
        assert result is not None, case["name"]
        token, timestamp = result
        assert token == case["expected_token"], case["name"]
        # Keep this deliberately timezone-insensitive beyond the local calendar year,
        # matching the existing Python behavior contract.
        from datetime import datetime

        assert datetime.fromtimestamp(timestamp).year == case["expected_local_year"], case["name"]


def test_contract_proposed_taken_cases_match_python_reference():
    contract = load_contract()
    for case in contract["proposed_taken_cases"]:
        actual = derive_proposed_taken(
            case["created"],
            case["filename_date"],
            case["taken"],
        )
        assert actual == case["expected"], case["name"]


def test_contract_issue_detection_cases_match_python_reference():
    contract = load_contract()
    for case in contract["issue_detection_cases"]:
        record = MediaRecord(
            name=Path(case["path"]).name,
            size_bytes=100,
            created="",
            modified="",
            taken=case["taken"],
            filename_date="",
            path=case["path"],
            media_type=case["media_type"],
            created_ts=case["created_ts"],
            modified_ts=case["modified_ts"],
            taken_ts=case["taken_ts"],
            filename_ts=None,
        )
        assert list(detect_issues(record)) == case["expected_issues"], case["name"]


def test_contract_selection_range_cases_match_python_reference():
    contract = load_contract()
    for case in contract["selection_range_cases"]:
        actual = _selection_range(
            tuple(case["items"]),
            case["anchor"],
            case["target"],
        )
        assert list(actual) == case["expected"], case["name"]
