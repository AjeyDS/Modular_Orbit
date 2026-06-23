from __future__ import annotations

from app.user_model import (
    StoryBucketUpdate,
    current_woven_doc,
    list_story_bucket_items,
    seed_woven_user_model,
    update_story_bucket_item,
)


def _empty_all_buckets() -> None:
    """Reset every active bucket to header-only (the empty/seed baseline)."""
    for bucket in list_story_bucket_items():
        body = f"# {bucket.display_name}\n\n"
        update_story_bucket_item(bucket.id, StoryBucketUpdate(content=body))


def _set_bucket_content(text: str) -> None:
    """Empty all buckets, then give the first one real content via the real update path."""
    _empty_all_buckets()
    items = list_story_bucket_items()
    assert items, "expected seeded active story buckets"
    bucket = items[0]
    body = f"# {bucket.display_name}\n\n{text}\n"
    update_story_bucket_item(bucket.id, StoryBucketUpdate(content=body))


def test_seed_creates_v1_doc_from_bucket_content() -> None:
    _set_bucket_content("Family runs Ajey Pavers in Trichy.")

    result = seed_woven_user_model()

    assert result is not None
    doc = current_woven_doc()
    assert doc is not None
    assert doc["version"] == 1
    assert "Ajey Pavers" in doc["content"]


def test_seed_is_idempotent() -> None:
    _set_bucket_content("Family runs Ajey Pavers in Trichy.")
    first = seed_woven_user_model()
    assert first is not None

    second = seed_woven_user_model()
    assert second is None

    doc = current_woven_doc()
    assert doc is not None
    assert doc["version"] == 1


def test_seed_noop_when_all_buckets_empty() -> None:
    _empty_all_buckets()

    result = seed_woven_user_model()

    assert result is None
    assert current_woven_doc() is None
