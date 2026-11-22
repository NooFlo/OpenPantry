"""Import hygiene rules: fragments merge, entities decode, dupes sum."""

from app import import_rules


def test_fragments_merge_into_the_previous_row():
    rows = [
        {"raw": "2 cups flour", "amount": 2.0, "item_id": "flour", "unit": "cup"},
        {"raw": "2 cups flour", "amount": 1.0, "item_id": None, "unit": "cup"},
    ]
    clean, notes = import_rules.sanitize(rows)
    # the fragment's amount sums into the row it continues
    assert len(clean) == 1
    assert clean[0]["amount"] == 3.0
    assert len(notes) == 1


def test_untouched_rows_pass_through():
    rows = [
        {"raw": "2 cups flour", "amount": 2.0, "item_id": "flour", "unit": "cup"},
        {"raw": "2 EL Olivenöl", "amount": 2.0, "item_id": "oil", "unit": "el"},
    ]
    clean, notes = import_rules.sanitize(rows)
    assert clean == rows
    assert notes == []


def test_entities_decode_and_emptied_rows_drop():
    rows = [
        {"raw": "1&nbsp;kg Mehl", "amount": 1.0, "item_id": "m", "unit": "kg"},
        {"raw": "<br>", "amount": None, "item_id": None, "unit": None},
    ]
    clean, _ = import_rules.sanitize(rows)
    assert clean[0]["raw"] == "1 kg Mehl"
    assert len(clean) == 1
