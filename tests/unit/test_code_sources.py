"""코드 원문 읽기·라이선스 열람·프로젝트 선택과 연속 발췌를 검증한다."""

# Standard library imports
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
    manifest = json.loads((RESOURCE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    manifest["sources"] = manifest["sources"][:1]
    entry = manifest["sources"][0]
    shutil.copytree(RESOURCE_ROOT / entry["id"], tmp_path / entry["id"])
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
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
        ("excerpt_end", 99999),
        ("excerpt_end", 499),
        ("excerpt_start", 0),
        ("excerpt_start", 99999),
        ("revision", 123),
        ("language", "json"),
    ],
)
def test_invalid_source_metadata_is_rejected(
    corpus: tuple[Path, dict[str, Any]], field: str, value: str | int
) -> None:
    root, manifest = corpus
    manifest["sources"][0][field] = value
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        load_code_sources(root)


def test_crlf_source_and_unrestricted_attribution_do_not_block_practice(
    corpus: tuple[Path, dict[str, Any]],
) -> None:
    root, manifest = corpus
    entry = manifest["sources"][0]
    expected = load_code_sources(root)[0].lines
    source_file = root / entry["source_path"]
    raw = source_file.read_text(encoding="utf-8")
    source_file.write_bytes(raw.replace("\n", "\r\n").encode("utf-8"))
    (root / entry["license_path"]).unlink()
    entry.update(
        project="A local project",
        title="locally edited source",
        url="https://example.org/source",
        raw_url="https://example.org/raw",
        revision="main",
        license_id="Project-specific license",
        license_url="https://example.org/license",
        license_raw_url="https://example.org/raw-license",
        transformation="Displayed as ASCII",
        retrieved_on="not recorded",
    )
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert load_code_sources(root)[0].lines == expected
    source_file.write_text(raw.replace("Flask", "Local"), encoding="utf-8")
    assert (
        load_code_sources(root)[0].lines
        == normalize_code_lines(source_file.read_text(encoding="utf-8"))[
            entry["excerpt_start"] - 1 : entry["excerpt_end"]
        ]
    )


def test_license_is_read_only_when_requested_without_loading_code(
    corpus: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, manifest = corpus
    entry = manifest["sources"][0]
    (root / entry["source_path"]).unlink()
    (root / entry["license_path"]).write_bytes(b"Local license text.\r\n")
    monkeypatch.setattr(
        "vim_key_trainer.content.code_corpus._resource_root", lambda: root
    )
    assert read_code_license(entry["id"]) == "Local license text.\n"


def test_duplicate_source_id_is_rejected(corpus: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = corpus
    manifest["sources"] *= 2
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="중복 코드 원문 ID"):
        load_code_sources(root)


def test_same_upstream_attribution_can_identify_distinct_practice_sources(
    corpus: tuple[Path, dict[str, Any]],
) -> None:
    root, manifest = corpus
    original = manifest["sources"][0]
    repeated = dict(original, id=original["id"] + "_copy")
    for field in ("source_path", "license_path"):
        repeated[field] = repeated["id"] + "/" + Path(original[field]).name
    shutil.copytree(root / original["id"], root / repeated["id"])
    manifest["sources"].append(repeated)
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert len(load_code_sources(root)) == 2


def test_normalization_preserves_physical_lines_blanks_and_trailing_spaces() -> None:
    assert normalize_code_lines("\tname = 'café'  \r\n\r\n# 한글\n") == (
        "    name = 'cafe?'  ",
        "",
        "# ??????",
    )
    with pytest.raises(ValueError, match="제어 문자"):
        normalize_code_lines("safe\nunsafe\x00")


@pytest.mark.parametrize("data", [[], {}, {"sources": []}, {"sources": {}}])
def test_code_manifest_requires_source_records(
    corpus: tuple[Path, dict[str, Any]], data: object
) -> None:
    root, _ = corpus
    (root / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_code_sources(root)


def test_code_source_can_use_a_shared_nested_package_path(
    corpus: tuple[Path, dict[str, Any]],
) -> None:
    root, manifest = corpus
    entry = manifest["sources"][0]
    original = root / entry["source_path"]
    entry["source_path"] = "shared/archive/source.txt"
    entry["license_path"] = "LICENSE.txt"
    (root / entry["source_path"]).parent.mkdir(parents=True)
    original.rename(root / entry["source_path"])
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert len(load_code_sources(root)[0].lines) >= 500


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
