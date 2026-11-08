"""연습 어휘의 재현성과 긴 원문에서 검색 식별자의 충돌 방지를 검증한다."""

# Standard library imports
from random import Random

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.practice_words import (
    PRACTICE_WORDS,
    IdentifierPool,
    practice_word,
)


def test_practice_words_are_varied_ascii_and_exclusions_are_respected() -> None:
    assert len(PRACTICE_WORDS) == len(set(PRACTICE_WORDS)) >= 500
    assert all(
        word.isascii() and word.isalpha() and word.islower() for word in PRACTICE_WORDS
    )
    first = Random(42)
    same = Random(42)
    words = [practice_word(first) for _ in range(300)]
    assert words == [practice_word(same) for _ in range(300)]
    assert len(set(words)) > 200
    excluded = PRACTICE_WORDS[:-1]
    assert practice_word(Random(42), exclude=excluded) == PRACTICE_WORDS[-1]
    with pytest.raises(ValueError, match="연습 단어"):
        practice_word(Random(42), exclude=PRACTICE_WORDS)


@pytest.mark.parametrize("all_words_present", [False, True])
def test_identifier_pool_keeps_five_hundred_names_free_of_substring_collisions(
    all_words_present: bool,
) -> None:
    # 단어가 다른 식별자 안에 들어 있는 경우에도 원문과 충돌하면 안 된다.
    original = (
        " ".join(
            f"prefix_{word.upper() if index % 2 else word.title()}_suffix"
            for index, word in enumerate(PRACTICE_WORDS)
        )
        if all_words_present
        else "baseline = ORCHARD_Visitor + summerHouse"
    )
    pool = IdentifierPool(Random(42), (original,))
    same = IdentifierPool(Random(42), (original,))
    names = [pool.take() for _ in range(500)]
    assert names == [same.take() for _ in range(500)]
    assert len(set(names)) == 500
    assert all(name.casefold() not in original.casefold() for name in names)
    assert all(
        name.isascii()
        and name.isidentifier()
        and not any(char.isdigit() for char in name)
        for name in names
    )
    assert all(
        left.casefold() not in right.casefold()
        and right.casefold() not in left.casefold()
        for index, left in enumerate(names)
        for right in names[index + 1 :]
    )
    if not all_words_present:
        assert sum(name in PRACTICE_WORDS for name in names) > 100
    assert len({name[:3] for name in names}) > 100
