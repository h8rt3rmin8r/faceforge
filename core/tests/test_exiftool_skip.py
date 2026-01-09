from __future__ import annotations

from faceforge_core.ingest.exiftool import should_skip_exiftool


def test_should_skip_exiftool_new_text_formats() -> None:
    assert should_skip_exiftool("data.csv") is True
    assert should_skip_exiftool("report.tsv") is True
    assert should_skip_exiftool("doc.html") is True
    assert should_skip_exiftool("doc.htm") is True
    assert should_skip_exiftool("metadata.json") is True
    assert should_skip_exiftool("feed.xml") is True


def test_should_skip_exiftool_non_matching_file() -> None:
    assert should_skip_exiftool("image.jpg") is False
