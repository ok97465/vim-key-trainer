"""프로젝트 다양성과 원문의 연속 구간·출처·재현성을 검증한다."""

# Standard library imports
from dataclasses import replace
from random import Random

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.code_corpus import load_code_sources
from vim_key_trainer.domain.code_samples import CodeSource, choose_code_excerpt


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
