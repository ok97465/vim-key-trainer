"""코드 목록을 읽는 경계에서 해시·URL·경로·변환을 검증한다."""

# Standard library imports
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.code_corpus import (
    load_code_sources,
    normalize_code_lines,
    read_code_license,
)

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
