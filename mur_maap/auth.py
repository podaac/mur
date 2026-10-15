"""Find the MAAP token, from the environment or ~/.maap-token.

WHY A FILE AT ALL
    Inside a MAAP workspace, authentication is ambient and none of this runs.
    Anywhere else maap-py needs MAAP_PGT, and the orchestrator passes the same
    value into each job so the container can mint its own DAAC credentials
    (run_mur_maap.py, l2p_args["maap_token"]). So one missing variable fails
    both halves, and "Unauthorized" is all you get.

    utils/cron_mur_maap.sh reads the file in bash, because it has to fail
    before launching Python. This is the same contract for everything else:
    one token on disk, found identically by the cron run, an interactive
    backfill, and a bare run_mur_maap.py.

THE FILE FORMAT
    The raw token value and nothing else -- no `export`, no quoting -- so that
    bash, tcsh and Python all read it the same way. The older
    `export MAAP_PGT=...` form is still parsed, since that is what the guide
    said to write first.

    Whitespace is stripped. A trailing newline or a space from a copy-paste is
    invisible and the API's only answer is "Invalid session or insufficient
    permissions"; a JWT contains no whitespace, so nothing legitimate is lost.

NEVER RETURN OR LOG THE VALUE
    load() reports only where the token came from. Callers want to print
    provenance when a run fails, and a function that hands back the secret
    gets its result logged sooner or later.
"""
import os
import re

DEFAULT_TOKEN_FILE = "~/.maap-token"

# No format check lives here, on purpose. A workspace session ticket is
# `jwt:` followed by a JWT, but a token generated at
# console.maap-project.org is not, and asserting the first shape rejected a
# valid instance of the second. Only an authenticated call can tell a good
# token from a bad one -- utils/upload_static_resources.py --check is that
# call, and the cron wrapper runs it before submitting anything.

_EXPORT = re.compile(r"""^\s*export\s+MAAP_PGT=['"]?(.*?)['"]?\s*$""", re.M)


def read_token_file(path):
    """The token in `path`, or "" if it has none. Accepts either file format."""
    try:
        with open(os.path.expanduser(path)) as fh:
            raw = fh.read()
    except OSError:
        return ""
    match = _EXPORT.search(raw)
    if match:
        raw = match.group(1)
    return "".join(raw.split())


def load(path=None, *, warn=None):
    """Ensure MAAP_PGT is set. Returns where it came from, never the value.

    One of "environment", "file:<path>", or "" when no token was found. An
    already-set variable wins, so a one-off `setenv MAAP_PGT ...` still
    overrides the file without editing it.
    """
    path = path or os.environ.get("MUR_TOKEN_FILE") or DEFAULT_TOKEN_FILE
    source = ""

    if os.environ.get("MAAP_PGT", "").strip():
        # Strip in place: the variable may have been exported with a stray
        # newline, which fails exactly as the file version does.
        os.environ["MAAP_PGT"] = "".join(os.environ["MAAP_PGT"].split())
        source = "environment"
    else:
        token = read_token_file(path)
        if token:
            os.environ["MAAP_PGT"] = token
            source = f"file:{path}"

    if warn and not source:
        warn("MAAP_PGT is not set and %s has no token, so MAAP calls will "
             "fail with Unauthorized. Get one from "
             "https://console.maap-project.org/profile/tokens" % path)
    return source
