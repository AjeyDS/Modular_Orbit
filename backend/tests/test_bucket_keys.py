from app.lifecycle.bucket_keys import ALLOWED_KEYS_LINE, KNOWN_BUCKET_KEYS, normalize_bucket_key


def test_normalize_maps_display_names_and_rejects_invented() -> None:
    assert normalize_bucket_key("Aspirations") == "aspirations"
    assert normalize_bucket_key("Who Am I") == "who_am_i"
    assert normalize_bucket_key("career") == "career"
    assert normalize_bucket_key("employment_authorization_document") is None
    assert normalize_bucket_key(None) is None


def test_goals_is_not_a_bucket_key() -> None:
    assert "goals" not in KNOWN_BUCKET_KEYS
    assert len(KNOWN_BUCKET_KEYS) == 7
    assert normalize_bucket_key("goals") is None
    assert normalize_bucket_key("Career") == "career"


def test_allowed_keys_line_lists_all_keys() -> None:
    for key in KNOWN_BUCKET_KEYS:
        assert key in ALLOWED_KEYS_LINE
