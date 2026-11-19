"""migrate_workspace_root copies mur/ between roots and repoints its hrefs."""
import datetime
import importlib.util
import io
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "migrate_workspace_root", REPO / "utils" / "migrate_workspace_root.py")
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)

from mur_maap.workspace import WorkspacePath   # noqa: E402

OLD = "s3://maap-ops-workspace/jleach_jpl"
NEW = "s3://team-mur-data"
T0 = datetime.datetime(2026, 11, 1, tzinfo=datetime.timezone.utc)
T1 = datetime.datetime(2026, 11, 2, tzinfo=datetime.timezone.utc)


class FakeS3:
    """Just enough S3: objects are {(bucket, key): (bytes, modified)}."""

    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.copies = []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        fake = self

        class Paginator:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [
                    {"Key": key, "Size": len(body), "LastModified": modified}
                    for (bucket, key), (body, modified)
                    in sorted(fake.objects.items())
                    if bucket == Bucket and key.startswith(Prefix)]}
        return Paginator()

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)][0])}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[(Bucket, Key)] = (Body, T1)

    def copy(self, source, bucket, key):
        self.copies.append(key)
        body, _ = self.objects[(source["Bucket"], source["Key"])]
        self.objects[(bucket, key)] = (body, T1)


class FakeWorkspace:
    def __init__(self, s3, org=WorkspacePath("team-mur-data", "")):
        self._s3, self._org = s3, org

    def s3(self):
        return self._s3

    def path(self):
        return WorkspacePath("maap-ops-workspace", "jleach_jpl")

    def org_path(self, match=None):
        self.matched = match
        return self._org


def item(root):
    return json.dumps({"assets": {
        "data": {"href": f"{root}/mur/l4/2026/315nrt/a.nc"},
        "dps": {"href": f"{OLD}/dps_output/mur-mrva_1756/2.0.20/a.nc"},
    }}).encode()


def populated():
    src = "maap-ops-workspace"
    return FakeS3({
        (src, "jleach_jpl/mur/l4/2026/315nrt/a.nc"): (b"x" * 10, T0),
        (src, "jleach_jpl/mur/stac/items/2026/315nrt.json"): (item(OLD), T0),
        (src, "jleach_jpl/dps_output/mur-mrva_1756/2.0.20/a.nc"): (b"y", T0),
        (src, "jleach_jpl/mur-old/keep.nc"): (b"z", T0),
    })


def test_rewrite_repoints_only_hrefs_under_the_tree():
    text = f'"{OLD}/mur/l4/a.nc" "{OLD}/dps_output/a.nc" "{OLD}/mur-old/b"'
    assert migrate.rewrite_text(text, OLD, NEW) == (
        f'"{NEW}/mur/l4/a.nc" "{OLD}/dps_output/a.nc" "{OLD}/mur-old/b"')


def test_rewrite_tolerates_trailing_slashes_on_the_roots():
    assert migrate.rewrite_text(f"{OLD}/mur/x", OLD + "/", NEW + "/") == \
        f"{NEW}/mur/x"


def test_dry_run_copies_nothing(capsys):
    s3 = populated()
    before = dict(s3.objects)
    assert migrate.main([], workspace=FakeWorkspace(s3)) == 0
    assert s3.objects == before
    assert "Dry run" in capsys.readouterr().out


def test_copy_moves_the_tree_to_a_bucket_root_and_repoints_json():
    s3 = populated()
    assert migrate.main(["--copy"], workspace=FakeWorkspace(s3)) == 0
    dest = {k for b, k in s3.objects if b == "team-mur-data"}
    # Only mur/: not dps_output, not a sibling that merely starts with "mur".
    assert dest == {"mur/l4/2026/315nrt/a.nc", "mur/stac/items/2026/315nrt.json"}
    copied = json.loads(
        s3.objects[("team-mur-data", "mur/stac/items/2026/315nrt.json")][0])
    assert copied["assets"]["data"]["href"] == f"{NEW}/mur/l4/2026/315nrt/a.nc"
    assert copied["assets"]["dps"]["href"].startswith(f"{OLD}/dps_output/")


def test_copy_leaves_the_source_untouched():
    s3 = populated()
    before = {k: v for k, v in s3.objects.items() if k[0] == "maap-ops-workspace"}
    migrate.main(["--copy"], workspace=FakeWorkspace(s3))
    assert {k: v for k, v in s3.objects.items()
            if k[0] == "maap-ops-workspace"} == before


def test_second_run_has_nothing_to_do(capsys):
    s3 = populated()
    migrate.main(["--copy"], workspace=FakeWorkspace(s3))
    s3.copies.clear()
    assert migrate.main(["--copy"], workspace=FakeWorkspace(s3)) == 0
    assert s3.copies == []
    assert "Nothing to do" in capsys.readouterr().out


def test_a_truncated_destination_object_is_copied_again():
    s3 = populated()
    s3.objects[("team-mur-data", "mur/l4/2026/315nrt/a.nc")] = (b"x", T1)
    migrate.main(["--copy"], workspace=FakeWorkspace(s3))
    assert s3.objects[("team-mur-data", "mur/l4/2026/315nrt/a.nc")][0] == b"x" * 10


def test_json_changed_at_the_source_since_the_copy_is_rewritten_again():
    source = {"mur/stac/a.json": {"Size": 5, "LastModified": T1}}
    stale = {"mur/stac/a.json": {"Size": 5, "LastModified": T0}}
    assert migrate.plan(source, stale)[0][0] == migrate.REWRITE
    assert migrate.plan(source, source)[0][0] == migrate.SKIP


def test_only_limits_the_copy():
    s3 = populated()
    migrate.main(["--copy", "--only", "mur/l4/*"], workspace=FakeWorkspace(s3))
    assert {k for b, k in s3.objects if b == "team-mur-data"} == {
        "mur/l4/2026/315nrt/a.nc"}


def test_verify_reports_missing_then_passes_after_the_copy(capsys):
    s3 = populated()
    assert migrate.main(["--verify"], workspace=FakeWorkspace(s3)) == 1
    assert "missing    mur/l4/2026/315nrt/a.nc" in capsys.readouterr().out
    migrate.main(["--copy"], workspace=FakeWorkspace(s3))
    assert migrate.main(["--verify"], workspace=FakeWorkspace(s3)) == 0


def test_destination_with_a_prefix():
    s3 = populated()
    migrate.main(["--copy", "--dest", "s3://team/maap/"],
                 workspace=FakeWorkspace(s3))
    assert ("team", "maap/mur/l4/2026/315nrt/a.nc") in s3.objects


def test_no_team_bucket_and_no_dest_is_an_error():
    with pytest.raises(SystemExit, match="--dest"):
        migrate.main([], workspace=FakeWorkspace(populated(), org=None))


def test_same_source_and_destination_is_refused():
    with pytest.raises(SystemExit, match="both"):
        migrate.main(["--dest", OLD], workspace=FakeWorkspace(populated()))


def test_the_team_bucket_is_searched_for_by_name():
    ws = FakeWorkspace(populated())
    migrate.main([], workspace=ws)
    assert ws.matched == "mur"
    migrate.main(["--match", "sst"], workspace=ws)
    assert ws.matched == "sst"
