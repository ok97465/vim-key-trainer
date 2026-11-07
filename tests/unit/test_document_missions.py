"""다운로드 원문·라이선스·고정된 여러 수정 지점과 실제 키 재생을 검증한다."""

# Standard library imports
import copy
import hashlib
import json
import re
import shutil
from importlib.resources import files
from itertools import pairwise
from pathlib import Path

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.document_missions import (
    create_document_lesson,
    document_catalog_issues,
    extract_source_lines,
    get_document_mission,
    list_document_collections,
    list_document_missions,
    load_document_catalog,
    read_document_license,
)
from vim_key_trainer.domain.editing import EditMode
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.edit_session import EditingSession

ROOT = files("vim_key_trainer").joinpath("resources", "documents")
MISSION_IDS = tuple(mission.id for mission in list_document_missions())


@pytest.fixture
def corpus_copy(tmp_path: Path) -> Path:
    directory = tmp_path / "documents"
    shutil.copytree(str(ROOT), directory)
    return directory


def test_bundled_corpus_has_many_real_projects_and_themed_missions() -> None:
    missions = list_document_missions()
    collections = list_document_collections()
    assert not document_catalog_issues()
    assert len(missions) == 16
    assert len({mission.source.project for mission in missions}) == 14
    assert len(collections) == 4
    for collection in collections:
        selected = list_document_missions(collection.id)
        assert len(selected) >= 4
        assert all(mission.collection_id == collection.id for mission in selected)
    assert {mission.language for mission in missions} == {
        "text",
        "markdown",
        "python",
        "cpp",
    }
    assert len({mission.initial_lines for mission in missions}) == len(missions)
    with pytest.raises(ValueError, match="컬렉션"):
        list_document_missions("missing")
    with pytest.raises(ValueError, match="문서 미션"):
        get_document_mission("missing")
    with pytest.raises(ValueError, match="출처"):
        read_document_license("../../outside")


@pytest.mark.parametrize("mission_id", MISSION_IDS)
def test_pinned_source_and_license_hashes_match_the_actual_bundled_text(
    mission_id: str,
) -> None:
    mission = get_document_mission(mission_id)
    source = mission.source
    assert re.fullmatch(r"[a-f0-9]{40}", source.revision)
    assert source.revision in source.url and source.revision in source.raw_url
    assert source.revision in source.license_url
    assert source.revision[:12] in source.id
    raw = ROOT.joinpath(*source.source_path.split("/")).read_bytes()
    license_data = ROOT.joinpath(*source.license_path.split("/")).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == source.sha256
    assert hashlib.sha256(license_data).hexdigest() == source.license_sha256
    assert read_document_license(source.id) == license_data.decode("utf-8")
    assert "Copyright" in read_document_license(source.id)
    assert source.license_id in {"MIT", "BSD-3-Clause"}
    assert (
        extract_source_lines(
            raw.decode("utf-8"),
            source.excerpt_start,
            source.excerpt_end,
            source.language,
        )
        == mission.goal_lines
    )
    assert source.transformation


@pytest.mark.parametrize("mission_id", MISSION_IDS)
@pytest.mark.parametrize("mode", ["guided", "free"])
def test_authored_missions_need_several_repairs_and_complete_in_both_modes(
    mission_id: str,
    mode: EditMode,
) -> None:
    mission = get_document_mission(mission_id)
    assert 4 <= mission.repair_count <= 6
    assert len({repair.row for repair in mission.repairs}) == mission.repair_count
    assert all(
        second.row - first.row >= 2 for first, second in pairwise(mission.repairs)
    )
    assert 24 <= len(mission.goal_lines) <= 60
    lesson = create_document_lesson(mission_id)
    assert lesson.initial.lines == mission.initial_lines
    assert lesson.goal_lines == mission.goal_lines
    assert lesson.initial.lines != lesson.goal_lines
    assert (
        sum(
            first != second
            for first, second in zip(
                lesson.initial.lines, lesson.goal_lines, strict=True
            )
        )
        == mission.repair_count
    )
    session = EditingSession(lesson, mode)
    for index, key in enumerate(lesson.baseline):
        assert session.state != SessionState.COMPLETED
        session.submit(key)
        if index < len(lesson.baseline) - 1:
            assert session.result is None
    assert session.state == SessionState.COMPLETED
    assert session.result is not None and session.result.stars == 3
    assert session.key_count == lesson.baseline_keys
    assert session.engine.state.lines == mission.goal_lines
    assert session.engine.state.mode == "normal" and not session.engine.state.pending


def test_catalog_and_lesson_creation_never_need_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("연습 중에는 네트워크를 사용하면 안 됩니다.")

    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    for mission in list_document_missions():
        assert create_document_lesson(mission.id).id == mission.id


@pytest.mark.parametrize(
    "failure",
    [
        "source_hash",
        "license_hash",
        "goal",
        "few_repairs",
        "duplicate_rows",
        "path",
        "url",
    ],
)
def test_bad_mission_is_excluded_with_file_and_field_issue_while_others_remain(
    corpus_copy: Path,
    failure: str,
) -> None:
    manifest_path = corpus_copy / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    mission = data["missions"][0]
    if failure == "source_hash":
        source_file = corpus_copy / mission["source"]["source_path"]
        source_file.write_text("corrupted", encoding="utf-8")
    elif failure == "license_hash":
        mission["source"]["license_sha256"] = "0" * 64
    elif failure == "goal":
        mission["goal_lines"][0] = "invented text without a matching source"
    elif failure == "few_repairs":
        mission["repairs"] = mission["repairs"][:1]
    elif failure == "duplicate_rows":
        mission["repairs"][1] = copy.deepcopy(mission["repairs"][0])
    elif failure == "path":
        mission["source"]["source_path"] = "../../outside.txt"
    else:
        mission["source"]["url"] = "https://example.org/fake"
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    report = load_document_catalog(corpus_copy)
    assert len(report.missions) == 15
    assert report.issues
    assert all(
        "manifest.json" in issue and "missions.0" in issue for issue in report.issues
    )
    assert mission["id"] not in {valid.id for valid in report.missions}


def test_invalid_collection_and_duplicate_ids_are_isolated(corpus_copy: Path) -> None:
    manifest_path = corpus_copy / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["missions"][0]["collection_id"] = "missing"
    data["missions"].append(copy.deepcopy(data["missions"][1]))
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    report = load_document_catalog(corpus_copy)
    assert len(report.missions) == 15
    assert any("collection_id" in issue for issue in report.issues)
    assert any("중복" in issue for issue in report.issues)


@pytest.mark.parametrize("field", ["url", "license_url", "raw_url", "license_raw_url"])
def test_revision_in_a_filename_does_not_pin_a_branch_url(
    corpus_copy: Path, field: str
) -> None:
    manifest_path = corpus_copy / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    mission = data["missions"][0]
    source = mission["source"]
    revision = source["revision"]
    source[field] = source[field].replace(f"/{revision}/", f"/main/{revision}/")
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    report = load_document_catalog(corpus_copy)
    assert mission["id"] not in {item.id for item in report.missions}
    assert any(field in issue and "commit" in issue for issue in report.issues)


@pytest.mark.parametrize("field", ["source_path", "license_path"])
@pytest.mark.parametrize("filename", [r"..\..\outside.txt", r"D:\outside.txt"])
def test_windows_path_syntax_is_rejected_before_reading_corpus_files(
    corpus_copy: Path, field: str, filename: str
) -> None:
    manifest_path = corpus_copy / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    mission = data["missions"][0]
    source = mission["source"]
    source[field] = f"{source['id']}/{filename}"
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    report = load_document_catalog(corpus_copy)

    assert len(report.missions) == 15
    assert mission["id"] not in {valid.id for valid in report.missions}
    assert len(report.issues) == 1
    assert field in report.issues[0] and "경로" in report.issues[0]


def test_unknown_manifest_schema_does_not_attempt_to_read_source_files(
    corpus_copy: Path,
) -> None:
    (corpus_copy / "manifest.json").write_text(
        '{"schema_version": 2}', encoding="utf-8"
    )
    report = load_document_catalog(corpus_copy)
    assert not report.missions
    assert "schema_version" in report.issues[0]


@pytest.mark.parametrize("schema_version", [True, False, 1.0, "1", None])
def test_manifest_schema_requires_integer_one(
    corpus_copy: Path,
    schema_version: object,
) -> None:
    manifest_path = corpus_copy / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["schema_version"] = schema_version
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    report = load_document_catalog(corpus_copy)
    assert not report.missions
    assert "schema_version" in report.issues[0]


@pytest.mark.parametrize(
    "changed_metadata",
    ["language", "source_path", "sha256", "license_sha256"],
)
def test_source_id_cannot_identify_conflicting_physical_metadata(
    corpus_copy: Path,
    changed_metadata: str,
) -> None:
    manifest_path = corpus_copy / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    repeated = copy.deepcopy(data["missions"][0])
    repeated["id"] = "mission_flask_duplicate_source"
    source = repeated["source"]
    if changed_metadata == "language":
        # text와 markdown은 동일한 발췌 변환이므로 개별 미션 검증만으로 구별되지 않는다.
        source["language"] = "text"
    elif changed_metadata == "source_path":
        previous = corpus_copy / source["source_path"]
        source["source_path"] = f"{source['id']}/alternate.txt"
        (corpus_copy / source["source_path"]).write_bytes(previous.read_bytes())
    elif changed_metadata == "sha256":
        previous = corpus_copy / source["source_path"]
        raw = previous.read_bytes() + b"\n"
        source["source_path"] = f"{source['id']}/alternate.txt"
        source["sha256"] = hashlib.sha256(raw).hexdigest()
        (corpus_copy / source["source_path"]).write_bytes(raw)
    else:
        previous = corpus_copy / source["license_path"]
        raw = previous.read_bytes() + b"\n"
        source["license_path"] = f"{source['id']}/alternate-license.txt"
        source["license_sha256"] = hashlib.sha256(raw).hexdigest()
        (corpus_copy / source["license_path"]).write_bytes(raw)
    data["missions"].append(repeated)
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    report = load_document_catalog(corpus_copy)
    assert len(report.missions) == 16
    assert report.missions[0].source == get_document_mission("mission_flask").source
    assert repeated["id"] not in {mission.id for mission in report.missions}
    assert len(report.issues) == 1
    assert "manifest.json" in report.issues[0]
    assert "missions.16" in report.issues[0] and "source.id" in report.issues[0]


@pytest.mark.parametrize("different_excerpt", [False, True])
def test_same_physical_source_can_supply_multiple_valid_missions(
    corpus_copy: Path,
    different_excerpt: bool,
) -> None:
    manifest_path = corpus_copy / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    repeated = copy.deepcopy(data["missions"][0])
    repeated["id"] = "mission_flask_second_excerpt"
    source = repeated["source"]
    if different_excerpt:
        source["excerpt_end"] += 1
        source["transformation"] += " 원문 다음 행까지 포함한 추가 발췌."
        raw = (corpus_copy / source["source_path"]).read_text(encoding="utf-8")
        repeated["goal_lines"] = extract_source_lines(
            raw,
            source["excerpt_start"],
            source["excerpt_end"],
            source["language"],
        )
    data["missions"].append(repeated)
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    report = load_document_catalog(corpus_copy)
    assert not report.issues
    assert len(report.missions) == 17
    assert report.missions[-1].source.id == report.missions[0].source.id
    assert (
        report.missions[-1].goal_lines != report.missions[0].goal_lines
    ) is different_excerpt
