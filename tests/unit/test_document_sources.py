"""번들 문서의 구조·표기용 출처·수정 지점과 실제 키 재생을 검증한다."""

# Standard library imports
import copy
import json
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
def test_bundled_source_attribution_and_full_license_are_available(
    mission_id: str,
) -> None:
    source = get_document_mission(mission_id).source
    assert source.project and source.title and source.url and source.revision
    assert ROOT.joinpath(*source.source_path.split("/")).is_file()
    assert read_document_license(source.id) == ROOT.joinpath(
        *source.license_path.split("/")
    ).read_text(encoding="utf-8")


def test_document_practice_uses_authored_goal_without_reading_source_or_license(
    corpus_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = corpus_copy / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    mission = data["missions"][0]
    source = mission["source"]
    (corpus_copy / source["source_path"]).unlink()
    (corpus_copy / source["license_path"]).write_bytes(b"Local license text.\r\n")
    mission["goal_lines"][0] = "# An authored practice document"
    source.update(
        url="https://example.org/current-document",
        raw_url="https://example.org/raw-document",
        revision="main",
        license_id="Project-specific license",
        license_url="https://example.org/license",
        license_raw_url="https://example.org/raw-license",
        retrieved_on="not recorded",
    )
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    report = load_document_catalog(corpus_copy)
    assert not report.issues and len(report.missions) == 16
    assert report.missions[0].goal_lines == tuple(mission["goal_lines"])
    monkeypatch.setattr(
        "vim_key_trainer.content.document_missions._bundled_catalog", lambda: report
    )
    monkeypatch.setattr(
        "vim_key_trainer.content.document_missions._resource_root", lambda: corpus_copy
    )
    assert read_document_license(source["id"]) == "Local license text.\n"
    (corpus_copy / source["license_path"]).unlink()
    assert not load_document_catalog(corpus_copy).issues


def test_crlf_bundled_documents_remain_available(corpus_copy: Path) -> None:
    for path in corpus_copy.rglob("*.txt"):
        path.write_bytes(
            path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        )
    report = load_document_catalog(corpus_copy)
    assert not report.issues and len(report.missions) == 16


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
    ["goal", "few_repairs", "duplicate_rows", "path", "language", "excerpt"],
)
def test_bad_mission_is_excluded_with_file_and_field_issue_while_others_remain(
    corpus_copy: Path,
    failure: str,
) -> None:
    manifest_path = corpus_copy / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    mission = data["missions"][0]
    if failure == "goal":
        mission["repairs"][0]["correct"] = "not the target text"
    elif failure == "few_repairs":
        mission["repairs"] = mission["repairs"][:1]
    elif failure == "duplicate_rows":
        mission["repairs"][1] = copy.deepcopy(mission["repairs"][0])
    elif failure == "path":
        mission["source"]["source_path"] = "../../outside.txt"
    elif failure == "language":
        mission["source"]["language"] = "json"
    else:
        mission["source"]["excerpt_end"] = mission["source"]["excerpt_start"] - 1
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


@pytest.mark.parametrize("field", ["source_path", "license_path"])
@pytest.mark.parametrize(
    "filename",
    [
        "",
        ".",
        "/outside.txt",
        "../outside.txt",
        r"..\..\outside.txt",
        r"D:\outside.txt",
    ],
)
def test_unsafe_or_empty_package_paths_are_rejected(
    corpus_copy: Path, field: str, filename: str
) -> None:
    manifest_path = corpus_copy / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    mission = data["missions"][0]
    source = mission["source"]
    source[field] = filename
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    report = load_document_catalog(corpus_copy)

    assert len(report.missions) == 15
    assert mission["id"] not in {valid.id for valid in report.missions}
    assert len(report.issues) == 1
    assert field in report.issues[0] and "경로" in report.issues[0]


@pytest.mark.parametrize(
    "data",
    [[], {}, {"collections": []}, {"collections": {}, "missions": []}],
)
def test_document_catalog_requires_collection_and_mission_lists(
    corpus_copy: Path, data: object
) -> None:
    (corpus_copy / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    report = load_document_catalog(corpus_copy)
    assert not report.missions
    assert "collections/missions" in report.issues[0]


def test_package_paths_may_use_shared_folders_and_nested_subfolders(
    corpus_copy: Path,
) -> None:
    manifest_path = corpus_copy / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = data["missions"][0]["source"]
    source.update(source_path="shared/archive/source.txt", license_path="LICENSE.txt")
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    report = load_document_catalog(corpus_copy)
    assert not report.issues and len(report.missions) == 16


def test_multiple_missions_can_share_source_id_with_different_attribution(
    corpus_copy: Path,
) -> None:
    manifest_path = corpus_copy / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    repeated = copy.deepcopy(data["missions"][0])
    repeated["id"] = "mission_flask_second_excerpt"
    repeated["source"].update(
        project="Another project name",
        revision="edited locally",
        source_path=f"{repeated['source']['id']}/alternate.txt",
        language="text",
    )
    repeated["goal_lines"][0] = "# Another authored practice document"
    data["missions"].append(repeated)
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    report = load_document_catalog(corpus_copy)
    assert not report.issues
    assert len(report.missions) == 17
    assert report.missions[-1].source.id == report.missions[0].source.id
    assert report.missions[-1].goal_lines != report.missions[0].goal_lines
