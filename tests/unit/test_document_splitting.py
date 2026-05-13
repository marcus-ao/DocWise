from __future__ import annotations

import logging

import pytest

from src.document.parser import LARGE_DOCUMENT_THRESHOLD_BYTES, ParsedBlock, ParsedDocument, split_large_document


def _make_parsed_document(blocks: list[ParsedBlock], *, byte_size: int) -> ParsedDocument:
    return ParsedDocument(
        title="Guide",
        file_name="guide.md",
        content_type="text/markdown",
        parser_name="markdown_parser",
        parser_version="1.0",
        byte_size=byte_size,
        blocks=blocks,
        metadata={},
    )


def test_split_large_document_skips_small_inputs() -> None:
    parsed = _make_parsed_document(
        [
            ParsedBlock(text="Overview", block_type="heading", heading_level=1, section_path="Overview"),
            ParsedBlock(text="small body", section_path="Overview"),
            ParsedBlock(text="Details", block_type="heading", heading_level=1, section_path="Details"),
            ParsedBlock(text="more body", section_path="Details"),
        ],
        byte_size=LARGE_DOCUMENT_THRESHOLD_BYTES - 1,
    )

    result = split_large_document(parsed)

    assert result == [parsed]


def test_split_large_document_warns_when_no_h1(caplog: pytest.LogCaptureFixture) -> None:
    parsed = _make_parsed_document(
        [
            ParsedBlock(text="intro", section_path="guide"),
            ParsedBlock(text="body", section_path="guide"),
        ],
        byte_size=LARGE_DOCUMENT_THRESHOLD_BYTES + 1,
    )

    with caplog.at_level(logging.WARNING):
        result = split_large_document(parsed)

    assert result == [parsed]
    assert "was not split" in caplog.text


def test_split_large_document_creates_children_for_multiple_h1_sections() -> None:
    parsed = _make_parsed_document(
        [
            ParsedBlock(text="preamble", section_path=None),
            ParsedBlock(text="Overview", block_type="heading", heading_level=1, section_path="Overview"),
            ParsedBlock(text="overview body", section_path="Overview"),
            ParsedBlock(text="Deep Dive", block_type="heading", heading_level=1, section_path="Deep Dive"),
            ParsedBlock(text="deep body", section_path="Deep Dive"),
        ],
        byte_size=LARGE_DOCUMENT_THRESHOLD_BYTES + 1,
    )

    result = split_large_document(parsed)

    assert len(result) == 2
    assert result[0].title == "Guide — Overview"
    assert result[0].file_name == "guide.md#overview"
    assert result[0].metadata["h1_slug"] == "overview"
    assert result[0].blocks[0].text == "preamble"
    assert result[1].title == "Guide — Deep Dive"
    assert result[1].file_name == "guide.md#deep-dive"


def test_split_large_document_disambiguates_duplicate_h1_slugs() -> None:
    parsed = _make_parsed_document(
        [
            ParsedBlock(text="Intro", block_type="heading", heading_level=1, section_path="Intro"),
            ParsedBlock(text="one", section_path="Intro"),
            ParsedBlock(text="Intro", block_type="heading", heading_level=1, section_path="Intro"),
            ParsedBlock(text="two", section_path="Intro"),
            ParsedBlock(text="Intro", block_type="heading", heading_level=1, section_path="Intro"),
            ParsedBlock(text="three", section_path="Intro"),
        ],
        byte_size=LARGE_DOCUMENT_THRESHOLD_BYTES + 1,
    )

    result = split_large_document(parsed)

    assert [item.metadata["h1_slug"] for item in result] == ["intro", "intro-2", "intro-3"]
    assert [item.file_name for item in result] == ["guide.md#intro", "guide.md#intro-2", "guide.md#intro-3"]
