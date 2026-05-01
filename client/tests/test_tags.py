import pytest

from llm_client.client import _validate_tags, TagValidationError


def test_valid_tags_pass():
    tags = ["feature:summarization", "prompt:summarize-v3"]
    assert _validate_tags(tags) == tags


def test_optional_tags_allowed():
    tags = ["feature:x", "prompt:y", "customer:acme", "experiment:b"]
    assert _validate_tags(tags) == tags


def test_missing_required_raises():
    with pytest.raises(TagValidationError):
        _validate_tags(["feature:x"])


def test_unknown_key_raises():
    with pytest.raises(TagValidationError):
        _validate_tags(["feature:x", "prompt:y", "env:prod"])


def test_malformed_raises():
    with pytest.raises(TagValidationError):
        _validate_tags(["feature", "prompt:y"])
