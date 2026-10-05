import pytest

from app.services.chunking import split_text


def test_split_text_creates_overlapping_chunks():
    chunks = split_text("alpha beta gamma delta epsilon zeta", chunk_size=18, overlap=5)
    assert len(chunks) > 1
    assert chunks[0].split()[-1] in chunks[1].split()[:2]


def test_split_text_handles_empty_input():
    assert split_text(" \n ", chunk_size=100, overlap=10) == []


def test_split_text_rejects_invalid_overlap():
    with pytest.raises(ValueError):
        split_text("text", chunk_size=10, overlap=10)
