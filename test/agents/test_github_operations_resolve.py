"""github-operations の resolve-project.sh を偽の gh で検査する.

gh の出力の形は推定 (実 API 未検証) なので、想定外の形は失敗になることを確かめる。
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "home/dot_claude/skills/github-operations/scripts/executable_resolve-project.sh"

pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("jq") is None or shutil.which("bash") is None,
    reason="Unix 専用 (偽 gh は sh スクリプト) / jq・bash が必要",
)

PROJECT = {"id": "PVT_1", "number": 3}
SELECT = {
    "id": "PVTSSF_1",
    "name": "Status",
    "type": "ProjectV2SingleSelectField",
    "options": [{"id": "o1", "name": "Todo"}, {"id": "o2", "name": "Done"}],
}
ITER = {
    "id": "PVTIF_1",
    "name": "Sprint",
    "type": "ProjectV2IterationField",
    "configuration": {
        "iterations": [{"id": "i1", "title": "S1", "startDate": "2026-01-01", "duration": 14}]
    },
}
TEXT = {"id": "PVTF_1", "name": "Note", "type": "ProjectV2Field"}


def good():
    return {"fields": [SELECT, ITER, TEXT], "totalCount": 3}


def run(tmp_path, fields=None, project=PROJECT, fail=None):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (tmp_path / "view.json").write_text(json.dumps(project))
    (tmp_path / "fields.json").write_text(json.dumps(fields))
    gh = bindir / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        f'if [ "$2" = "{fail}" ]; then echo boom >&2; exit 1; fi\n'
        'case "$2" in\n'
        f'  view) cat "{tmp_path}/view.json" ;;\n'
        f'  field-list) cat "{tmp_path}/fields.json" ;;\n'
        "esac\n"
    )
    gh.chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run(
        ["bash", str(SCRIPT), "me", "3"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )


def test_success(tmp_path):
    r = run(tmp_path, good())
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["project_id"] == "PVT_1"
    assert out["fields"]["Status"]["options"] == {"Todo": "o1", "Done": "o2"}
    assert out["fields"]["Sprint"]["iterations"][0]["duration"] == 14
    assert out["fields"]["Note"] == {"id": "PVTF_1", "type": "ProjectV2Field"}


CASES = {
    "truncated": {"fields": [SELECT], "totalCount": 3},
    "totalCount missing": {"fields": [SELECT]},
    "totalCount not number": {"fields": [SELECT], "totalCount": "1"},
    "fields not array": {"fields": {"a": 1}, "totalCount": 0},
    "fields missing": {"totalCount": 0},
    "iteration info missing": {
        "fields": [{k: v for k, v in ITER.items() if k != "configuration"}],
        "totalCount": 1,
    },
    "iteration shape odd": {
        "fields": [{**ITER, "configuration": {"iterations": [{"id": "i"}]}}],
        "totalCount": 1,
    },
    "field id missing": {
        "fields": [{"name": "X", "type": "ProjectV2Field"}],
        "totalCount": 1,
    },
    "field name missing": {
        "fields": [{"id": "x", "type": "ProjectV2Field"}],
        "totalCount": 1,
    },
    "options odd": {"fields": [{**SELECT, "options": [{"id": "o"}]}], "totalCount": 1},
    "select without options": {
        "fields": [{k: v for k, v in SELECT.items() if k != "options"}],
        "totalCount": 1,
    },
    "totalCount negative": {"fields": [SELECT], "totalCount": -1},
    "totalCount fractional": {"fields": [SELECT], "totalCount": 0.5},
    "option id empty": {
        "fields": [{**SELECT, "options": [{"id": "", "name": "Todo"}]}],
        "totalCount": 1,
    },
    "iteration id empty": {
        "fields": [
            {
                **ITER,
                "configuration": {
                    "iterations": [
                        {"id": "", "title": "S1", "startDate": "2026-01-01", "duration": 14}
                    ]
                },
            }
        ],
        "totalCount": 1,
    },
    "field id empty": {
        "fields": [{"id": "", "name": "X", "type": "ProjectV2Field"}],
        "totalCount": 1,
    },
    "duplicate field names": {"fields": [TEXT, {**TEXT, "id": "PVTF_2"}], "totalCount": 2},
    "duplicate option names": {
        "fields": [
            {
                **SELECT,
                "options": [{"id": "o1", "name": "Todo"}, {"id": "o2", "name": "Todo"}],
            }
        ],
        "totalCount": 1,
    },
    "not an object": [],
}


@pytest.mark.parametrize("name", list(CASES))
def test_unexpected_shape_fails(tmp_path, name):
    r = run(tmp_path, CASES[name])
    assert r.returncode != 0, r.stdout
    assert r.stdout == ""
    assert "resolve-project" in r.stderr


def test_project_id_missing(tmp_path):
    r = run(tmp_path, good(), project={"number": 3})
    assert r.returncode != 0
    assert r.stdout == ""
    assert "resolve-project" in r.stderr


@pytest.mark.parametrize("cmd", ["view", "field-list"])
def test_gh_failure(tmp_path, cmd):
    r = run(tmp_path, good(), fail=cmd)
    assert r.returncode != 0
    assert r.stdout == ""
    assert "failed" in r.stderr
