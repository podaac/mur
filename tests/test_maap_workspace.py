"""WorkspaceBucket picks authorized paths by their type, not position."""
from mur_maap.workspace import WorkspaceBucket, WorkspacePath

# The shape workspace_bucket_credentials() returned for a MUR team member
# on 2026-10-29, credentials omitted.
AUTHORIZED = [
    {"access": "read_write", "bucket": "maap-ops-workspace",
     "prefix": "jleach_jpl", "type": "workspace",
     "uri": "s3://maap-ops-workspace/jleach_jpl"},
    {"access": "read_write", "bucket": "maap-ops-workspace",
     "prefix": "shared/jleach_jpl", "type": "shared",
     "uri": "s3://maap-ops-workspace/shared/jleach_jpl"},
    {"access": "read_write", "bucket": "mur-sst", "prefix": "",
     "type": "org", "uri": "s3://mur-sst"},
]


class FakeAws:
    def __init__(self, entries):
        self.entries = entries

    def workspace_bucket_credentials(self):
        return {"aws_access_key_id": "a", "aws_secret_access_key": "s",
                "aws_session_token": "t", "expires_at": "2099-01-01T00:00:00Z",
                "authorized_s3_paths": self.entries}


class FakeMaap:
    def __init__(self, entries):
        self.aws = FakeAws(entries)


def test_path_is_the_personal_workspace():
    bucket = WorkspaceBucket(FakeMaap(AUTHORIZED))
    assert bucket.path() == WorkspacePath("maap-ops-workspace", "jleach_jpl")


def test_path_is_found_by_type_even_when_not_first():
    bucket = WorkspaceBucket(FakeMaap(list(reversed(AUTHORIZED))))
    assert bucket.path().prefix == "jleach_jpl"


def test_org_path_is_the_team_bucket():
    org = WorkspaceBucket(FakeMaap(AUTHORIZED)).org_path()
    assert org == WorkspacePath("mur-sst", "")
    assert org.uri == "s3://mur-sst"
    assert org.s3_uri("mur/l4/x.nc") == "s3://mur-sst/mur/l4/x.nc"


def test_org_path_is_none_without_a_team_bucket():
    assert WorkspaceBucket(FakeMaap(AUTHORIZED[:2])).org_path() is None
