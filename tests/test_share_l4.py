"""utils/share_l4.py: which granules it copies, and where it copies them."""
import importlib.util
import pathlib

from mur_maap.workspace import WorkspacePath

_spec = importlib.util.spec_from_file_location(
    "share_l4",
    pathlib.Path(__file__).resolve().parent.parent / "utils" / "share_l4.py")
share_l4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(share_l4)


class FakeS3:
    def __init__(self, objects):
        self.objects = objects            # {(bucket, key): size}

    def get_paginator(self, _name):
        return self

    def paginate(self, Bucket, Prefix):
        yield {"Contents": [{"Key": k, "Size": s}
                            for (b, k), s in self.objects.items()
                            if b == Bucket and k.startswith(Prefix)]}


class FakeWorkspace:
    def __init__(self, org):
        self.org, self.asked = org, []

    def org_path(self, match=None):
        self.asked.append(match)
        return self.org


S3 = FakeS3({
    ("personal", "me/mur/l4/1km/2026/a.nc"): 10,
    ("personal", "me/mur/l4/25km/2026/b.nc"): 20,
    ("personal", "me/mur/l4/1km/2026/a.nc.tmp"): 1,
    ("personal", "me/mur/bic/X/2026/c.bic.gz"): 5,
    ("team", "mur/l4/1km/2026/a.nc"): 10,
    ("team", "mur/l4/25km/2026/b.nc"): 19,     # a short, interrupted copy
})


def test_listing_is_relative_to_the_root_and_netcdf_only():
    assert share_l4.listing(S3, "s3://personal/me") == {
        "mur/l4/1km/2026/a.nc": 10, "mur/l4/25km/2026/b.nc": 20}
    # A bucket-root destination has no prefix to strip.
    assert set(share_l4.listing(S3, "s3://team")) == {
        "mur/l4/1km/2026/a.nc", "mur/l4/25km/2026/b.nc"}


def test_plan_copies_what_is_missing_or_a_different_size():
    src = share_l4.listing(S3, "s3://personal/me")
    assert share_l4.plan(src, share_l4.listing(S3, "s3://team")) == [
        "mur/l4/25km/2026/b.nc"]
    assert share_l4.plan(src, {}) == sorted(src)
    assert share_l4.plan(src, {}, only="*/1km/*") == ["mur/l4/1km/2026/a.nc"]


def test_destination_is_searched_for_unless_given():
    ws = FakeWorkspace(WorkspacePath("team", ""))
    assert share_l4.resolve_dest({}, ws) == "s3://team"
    assert ws.asked == ["mur"]
    assert share_l4.resolve_dest({"maap": {"team_bucket": "s3://x/y"}}, ws) == "s3://x/y"
    assert share_l4.resolve_dest({}, ws, "s3://override/") == "s3://override"
    assert share_l4.resolve_dest({"maap": {"team_bucket": False}}, ws) is None
    assert share_l4.resolve_dest({}, FakeWorkspace(None)) is None
