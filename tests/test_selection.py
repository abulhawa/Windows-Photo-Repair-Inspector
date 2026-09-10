from photo_repair.app import _selection_range


def test_selection_range_forward_uses_original_anchor():
    items = ("row1", "row2", "row3", "row4", "row5")
    assert _selection_range(items, "row2", "row5") == (
        "row2",
        "row3",
        "row4",
        "row5",
    )


def test_selection_range_backward_is_inclusive():
    items = ("row1", "row2", "row3", "row4", "row5")
    assert _selection_range(items, "row5", "row2") == (
        "row2",
        "row3",
        "row4",
        "row5",
    )
