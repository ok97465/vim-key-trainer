"""코드 원문의 검증·라이선스·프로젝트 선택과 연속 발췌를 검증한다."""

# Standard library imports
import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from random import Random
from typing import Any

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.code_corpus import (
    load_code_sources,
    normalize_code_lines,
    read_code_license,
)
from vim_key_trainer.domain.code_samples import CodeSource, choose_code_excerpt

RESOURCE_ROOT = (
    Path(__file__).resolve().parents[2] / "src/vim_key_trainer/resources/code_corpus"
)


@pytest.fixture
def corpus(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    manifest = json.loads((RESOURCE_ROOT / "manifest.json").read_text())
    manifest["sources"] = manifest["sources"][:1]
    entry = manifest["sources"][0]
    shutil.copytree(RESOURCE_ROOT / entry["id"], tmp_path / entry["id"])
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path, manifest


def test_unaltered_corpus_loads_and_full_license_is_available(
    corpus: tuple[Path, dict[str, Any]],
) -> None:
    root, _ = corpus
    source = load_code_sources(root)[0].source
    license_text = read_code_license(source.id)
    assert len(license_text) > 500
    assert "Copyright" in license_text
    with pytest.raises(ValueError, match="알 수 없는"):
        read_code_license("../LICENSE.txt")


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_path", "../source.txt"),
        ("license_path", r"project/..\outside.txt"),
        ("raw_url", "https://example.com/source.py"),
        ("revision", "main"),
        ("license_id", "unknown"),
        ("transformation", "execute_python"),
        ("retrieved_on", "2026-99-99"),
        ("excerpt_end", 99999),
        ("language", "json"),
    ],
)
def test_invalid_source_metadata_is_rejected(
    corpus: tuple[Path, dict[str, Any]], field: str, value: str | int
) -> None:
    root, manifest = corpus
    manifest["sources"][0][field] = value
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        load_code_sources(root)


@pytest.mark.parametrize("field", ["source_path", "license_path"])
def test_modified_bundled_bytes_fail_before_becoming_practice_content(
    corpus: tuple[Path, dict[str, Any]], field: str
) -> None:
    root, manifest = corpus
    entry = manifest["sources"][0]
    (root / entry[field]).write_text("tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        load_code_sources(root)


def test_duplicate_source_id_is_rejected(corpus: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = corpus
    manifest["sources"] *= 2
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="중복 코드 원문 ID"):
        load_code_sources(root)


def test_declared_license_must_match_bundled_license_text(
    corpus: tuple[Path, dict[str, Any]],
) -> None:
    root, manifest = corpus
    entry = manifest["sources"][0]
    data = b"Not a permission grant."
    (root / entry["license_path"]).write_bytes(data)
    entry["license_sha256"] = hashlib.sha256(data).hexdigest()
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="허용 라이선스"):
        load_code_sources(root)


def test_normalization_preserves_physical_lines_blanks_and_trailing_spaces() -> None:
    assert normalize_code_lines("\tname = 'café'  \r\n\r\n# 한글\n") == (
        "    name = 'cafe?'  ",
        "",
        "# ??????",
    )
    with pytest.raises(ValueError, match="제어 문자"):
        normalize_code_lines("safe\nunsafe\x00")


@pytest.mark.parametrize("version", [True, 1.0, "1", 2])
def test_manifest_version_requires_supported_integer(
    corpus: tuple[Path, dict[str, Any]], version: object
) -> None:
    root, manifest = corpus
    manifest["schema_version"] = version
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="schema_version"):
        load_code_sources(root)


@pytest.mark.parametrize("language", ["python", "cpp"])
def test_bundled_corpus_has_twelve_independent_projects_per_language(
    language: str,
) -> None:
    sources = load_code_sources()
    selected = [entry for entry in sources if entry.source.language == language]
    assert len({entry.source.project.casefold() for entry in selected}) >= 12
    assert all(len(entry.lines) >= 500 for entry in selected)
    assert all(
        char.isascii() and char.isprintable()
        for entry in selected
        for line in entry.lines
        for char in line
    )


@pytest.mark.parametrize("language", ["python", "cpp"])
@pytest.mark.parametrize("count", [300, 500])
def test_seeded_excerpts_are_contiguous_exact_windows_with_original_line_numbers(
    language: str, count: int
) -> None:
    sources = load_code_sources()
    lookup = {entry.source.id: entry for entry in sources}
    for seed in range(24):
        excerpt = choose_code_excerpt(sources, language, count, Random(seed))
        assert excerpt == choose_code_excerpt(sources, language, count, Random(seed))
        source = lookup[excerpt.source.id]
        start = excerpt.start_line - source.source.excerpt_start
        assert excerpt.lines == source.lines[start : start + count]
        assert len(excerpt.lines) == count
        assert excerpt.end_line == excerpt.start_line + count - 1
        assert excerpt.end_line <= source.source.excerpt_end


@pytest.mark.parametrize("language", ["python", "cpp"])
def test_seed_stream_reaches_every_project_and_varies_windows(language: str) -> None:
    sources = load_code_sources()
    excerpts = [
        choose_code_excerpt(sources, language, 300, Random(seed)) for seed in range(256)
    ]
    assert {item.source.project for item in excerpts} == {
        entry.source.project for entry in sources if entry.source.language == language
    }
    assert len({(item.source.id, item.start_line) for item in excerpts}) > 200


@pytest.mark.parametrize("count", [299, 501, True])
def test_invalid_excerpt_lengths_are_rejected(count: int) -> None:
    with pytest.raises(ValueError, match="발췌 길이"):
        choose_code_excerpt(load_code_sources(), "python", count, Random(0))


def test_unknown_language_and_missing_sources_are_rejected() -> None:
    with pytest.raises(ValueError, match="언어"):
        choose_code_excerpt(load_code_sources(), "json", 300, Random(0))
    with pytest.raises(ValueError, match="원문이 없습니다"):
        choose_code_excerpt((), "python", 300, Random(0))


def test_extra_files_do_not_give_one_project_more_chance() -> None:
    sources = [
        entry for entry in load_code_sources() if entry.source.language == "python"
    ]
    first, second = sources[:2]
    extra = CodeSource(
        replace(first.source, id=first.source.id + "_extra"), first.lines
    )
    minimal = (first, second)
    extended = (first, second, extra)
    for seed in range(64):
        assert (
            choose_code_excerpt(minimal, "python", 300, Random(seed)).source.project
            == choose_code_excerpt(extended, "python", 300, Random(seed)).source.project
        )
