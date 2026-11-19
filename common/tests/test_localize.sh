#!/bin/bash
# Unit tests for common/bin/localize.sh's localize_input().
#
# Each case runs in a fresh bash subprocess, sources the helper, optionally
# defines a stub `aws` shell function (so no real credentials/network are
# needed), then calls localize_input directly.
# Usage: ./test_localize.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPER="$SCRIPT_DIR/../bin/localize.sh"

FAILURES=0

run_case() {
    local body="$1"
    bash -c "source '$HELPER'; $body"
}

assert_eq() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$expected" != "$actual" ]]; then
        echo "FAIL: $name — expected [$expected], got [$actual]"
        FAILURES=$((FAILURES + 1))
    else
        echo "PASS: $name"
    fi
}

assert_fails() {
    local name="$1"; shift
    if bash -c "source '$HELPER'; $*" >/dev/null 2>&1; then
        echo "FAIL: $name — expected non-zero exit, got 0"
        FAILURES=$((FAILURES + 1))
    else
        echo "PASS: $name"
    fi
}

# Stub `aws` -- mirrors `aws s3 cp SRC DEST`'s positional args ($1=s3 $2=cp $3=src $4=dest).
STUB_AWS_OK='aws() { if [[ "$1" == "s3" && "$2" == "cp" ]]; then mkdir -p "$(dirname "$4")"; echo "stub-fetched" > "$4"; return 0; fi; return 1; }'
STUB_AWS_FAIL='aws() { return 1; }'

# --- local path, exists -> passthrough, no aws call ---
scratch=$(mktemp -d)
touch "$scratch/local-file.gds"
out=$(run_case "localize_input name '$scratch/local-file.gds' '$scratch/out'")
assert_eq "local existing path passes through unchanged" "$scratch/local-file.gds" "$out"
rm -rf "$scratch"

# --- local path, does not exist -> still passthrough (existence check is caller's job) ---
out=$(run_case "localize_input name '/nonexistent/path.gds' '/tmp/scratch'")
assert_eq "local nonexistent path passes through unchanged" "/nonexistent/path.gds" "$out"

# --- s3:// path -> stubbed aws s3 cp invoked, returns scratch path ---
scratch=$(mktemp -d)
out=$(run_case "$STUB_AWS_OK; localize_input landmask_p01 s3://bucket/key/landmask.gds '$scratch'")
assert_eq "s3 path fetched to scratch dir, returns local path" "$scratch/landmask_p01" "$out"
if [[ -f "$scratch/landmask_p01" ]]; then
    echo "PASS: s3 fetch actually wrote a file"
else
    echo "FAIL: s3 fetch actually wrote a file — file missing"
    FAILURES=$((FAILURES + 1))
fi
rm -rf "$scratch"

# --- s3:// path, aws fails -> non-zero exit ---
scratch=$(mktemp -d)
assert_fails "s3 fetch failure returns non-zero" "$STUB_AWS_FAIL; localize_input landmask_p01 s3://bucket/key/landmask.gds '$scratch'"
rm -rf "$scratch"

# ============================================================
# localize_manifest -- these call the real `aws` on PATH (via subprocess.run
# from python3), so bash-function stubbing (as above) doesn't work here; use
# a real executable stub script prepended onto PATH instead.
# ============================================================

make_aws_stub() {
    local stub_dir="$1" mode="$2"  # mode: ok|fail
    mkdir -p "$stub_dir"
    if [[ "$mode" == "ok" ]]; then
        cat > "$stub_dir/aws" <<'EOF'
#!/bin/bash
if [[ "$1" == "s3" && "$2" == "cp" ]]; then
    mkdir -p "$(dirname "$4")"
    echo "stub-fetched" > "$4"
    exit 0
fi
exit 1
EOF
    else
        cat > "$stub_dir/aws" <<'EOF'
#!/bin/bash
exit 1
EOF
    fi
    chmod +x "$stub_dir/aws"
}

# --- localize_manifest: local-path entries symlinked with original basenames ---
scratch=$(mktemp -d)
src_dir=$(mktemp -d)
echo "content1" > "$src_dir/file1.nc"
echo "content2" > "$src_dir/file2.nc"
manifest="$scratch/manifest.json"
cat > "$manifest" <<EOF
{"files": [{"path": "$src_dir/file1.nc"}, {"path": "$src_dir/file2.nc"}]}
EOF
out=$(run_case "localize_manifest granules '$manifest' '$scratch'")
assert_eq "localize_manifest returns the materialized directory" "$scratch/granules" "$out"
if [[ -L "$scratch/granules/file1.nc" && "$(cat "$scratch/granules/file1.nc")" == "content1" \
      && -L "$scratch/granules/file2.nc" && "$(cat "$scratch/granules/file2.nc")" == "content2" ]]; then
    echo "PASS: local manifest entries symlinked with original basenames, content matches"
else
    echo "FAIL: local manifest entries symlinked with original basenames, content matches"
    FAILURES=$((FAILURES + 1))
fi
rm -rf "$scratch" "$src_dir"

# --- localize_manifest: relative_path entries preserve subdirectory structure ---
scratch=$(mktemp -d)
src_dir=$(mktemp -d)
touch "$src_dir/Global_AMSR2R_2026_088.bic.gz"
manifest="$scratch/manifest.json"
cat > "$manifest" <<EOF
{"files": [{"path": "$src_dir/Global_AMSR2R_2026_088.bic.gz", "sensor": "AMSR2R", "relative_path": "AMSR2R/2026/Global_AMSR2R_2026_088.bic.gz"}]}
EOF
run_case "localize_manifest sensors '$manifest' '$scratch'" >/dev/null
if [[ -L "$scratch/sensors/AMSR2R/2026/Global_AMSR2R_2026_088.bic.gz" ]]; then
    echo "PASS: relative_path entries preserve subdirectory structure"
else
    echo "FAIL: relative_path entries preserve subdirectory structure"
    FAILURES=$((FAILURES + 1))
fi
rm -rf "$scratch" "$src_dir"

# --- localize_manifest: s3:// entries fetched via stubbed aws (real executable, not a bash function) ---
scratch=$(mktemp -d)
stub_dir=$(mktemp -d)
make_aws_stub "$stub_dir" ok
manifest="$scratch/manifest.json"
cat > "$manifest" <<EOF
{"files": [{"path": "s3://bucket/key/file1.nc"}]}
EOF
PATH="$stub_dir:$PATH" run_case "localize_manifest granules '$manifest' '$scratch'" >/dev/null
if [[ -f "$scratch/granules/file1.nc" && ! -L "$scratch/granules/file1.nc" ]]; then
    echo "PASS: s3 manifest entries fetched via aws s3 cp"
else
    echo "FAIL: s3 manifest entries fetched via aws s3 cp"
    FAILURES=$((FAILURES + 1))
fi
rm -rf "$scratch" "$stub_dir"

# --- localize_manifest: manifest fetch failure (aws s3 cp fails) returns non-zero ---
scratch=$(mktemp -d)
stub_dir=$(mktemp -d)
make_aws_stub "$stub_dir" fail
manifest="$scratch/manifest.json"
cat > "$manifest" <<EOF
{"files": [{"path": "s3://bucket/key/file1.nc"}]}
EOF
if PATH="$stub_dir:$PATH" run_case "localize_manifest granules '$manifest' '$scratch'" >/dev/null 2>&1; then
    echo "FAIL: s3 manifest fetch failure returns non-zero — expected non-zero exit, got 0"
    FAILURES=$((FAILURES + 1))
else
    echo "PASS: s3 manifest fetch failure returns non-zero"
fi
rm -rf "$scratch" "$stub_dir"

# --- localize_manifest: a manifest entry pointing at a nonexistent local
# source materializes as a dangling symlink -- verification must catch this
# and fail loudly instead of silently handing MATLAB a broken path. ---
scratch=$(mktemp -d)
manifest="$scratch/manifest.json"
cat > "$manifest" <<EOF
{"files": [{"path": "/nonexistent/does-not-exist.nc"}]}
EOF
if run_case "localize_manifest granules '$manifest' '$scratch'" >/dev/null 2>&1; then
    echo "FAIL: dangling symlink (missing source file) returns non-zero — expected non-zero exit, got 0"
    FAILURES=$((FAILURES + 1))
else
    echo "PASS: dangling symlink (missing source file) returns non-zero"
fi
rm -rf "$scratch"

# --- localize_manifest: verification logs one "ok ... bytes" line per
# materialized file to stderr ---
scratch=$(mktemp -d)
src_dir=$(mktemp -d)
echo "hello" > "$src_dir/file1.nc"
manifest="$scratch/manifest.json"
cat > "$manifest" <<EOF
{"files": [{"path": "$src_dir/file1.nc"}]}
EOF
err=$(run_case "localize_manifest granules '$manifest' '$scratch'" 2>&1 1>/dev/null)
if [[ "$err" == *"ok "*"file1.nc"*"bytes"* ]]; then
    echo "PASS: localize_manifest logs a per-file ok/size line to stderr"
else
    echo "FAIL: localize_manifest logs a per-file ok/size line to stderr — got: $err"
    FAILURES=$((FAILURES + 1))
fi
rm -rf "$scratch" "$src_dir"

# --- an empty manifest must fail, not silently produce an empty product ---
#
# Observed on a real DPS job: a day with no granules localized cleanly (nothing
# is missing when nothing was listed), MATLAB ran over an empty directory, and
# L2P emitted a 48-byte BIC and a 0-byte L2Plist while reporting success. A
# downstream MRVA would then consume that as real data. No consumer has a
# meaningful use for an empty fan-in.
scratch=$(mktemp -d)
empty_manifest="$scratch/empty.json"
echo '{"files": []}' > "$empty_manifest"

if run_case "localize_manifest granules '$empty_manifest' '$scratch/out'" >/dev/null 2>&1; then
    echo "FAIL: localize_manifest accepted an empty manifest"
    FAILURES=$((FAILURES + 1))
else
    echo "PASS: localize_manifest rejects an empty manifest"
fi

err=$(run_case "localize_manifest granules '$empty_manifest' '$scratch/out'" 2>&1 >/dev/null)
case "$err" in
    *"listed no files"*) echo "PASS: the error says the manifest was empty" ;;
    *) echo "FAIL: unhelpful error for an empty manifest: $err"
       FAILURES=$((FAILURES + 1)) ;;
esac
rm -rf "$scratch"

# --- access kinds: the container decides HOW to read each source ---
#
# The orchestrator says WHAT to fetch; localize.sh says how. Three kinds exist
# today -- a mounted file, a bucket the runtime's own role can read, and a DAAC
# bucket it cannot -- and adding a fourth means adding a case to fetch_uri
# rather than changing any caller.

out=$(run_case 'access_kind_for "/data/in/x.nc"')
assert_eq "a bare path is local" "local" "$out"

out=$(run_case 'access_kind_for "s3://my-bucket/x.bic"')
assert_eq "an ordinary bucket uses the runtime role" "s3" "$out"

out=$(run_case 'access_kind_for "s3://podaac-ops-cumulus-protected/x.nc"')
assert_eq "a PO.DAAC bucket needs DAAC credentials" "podaac" "$out"

out=$(run_case 'access_kind_for "https://example.com/x.nc"')
assert_eq "an https URL is fetched over http" "http" "$out"

# A declared kind must win over inference: the orchestrator knows things the
# bucket name does not say.
scratch=$(mktemp -d)
printf 'real\n' > "$scratch/src.nc"
cat > "$scratch/m.json" <<EOF
{"files": [{"path": "$scratch/src.nc", "relative_path": "a.nc", "access": "local"}]}
EOF
out=$(run_case "localize_manifest granules '$scratch/m.json' '$scratch/out'" 2>/dev/null)
if [[ -r "$scratch/out/granules/a.nc" ]]; then
    echo "PASS: a local entry is materialized without any S3 call"
else
    echo "FAIL: local entry was not materialized"
    FAILURES=$((FAILURES + 1))
fi

# DAAC credentials are minted once per run, not once per file. A sensor-day is
# hundreds of granules; one exchange each would be hundreds of round trips.
cat > "$scratch/many.json" <<'EOF'
{"files": [
  {"path": "s3://podaac-ops-cumulus-protected/a.nc", "relative_path": "a.nc", "access": "podaac"},
  {"path": "s3://podaac-ops-cumulus-protected/b.nc", "relative_path": "b.nc", "access": "podaac"},
  {"path": "s3://podaac-ops-cumulus-protected/c.nc", "relative_path": "c.nc", "access": "podaac"}
]}
EOF
# Stub the credential HELPER, not _ensure_podaac_credentials -- overriding the
# function would bypass the caching guard this is meant to test.
cat > "$scratch/fake_creds.py" <<'CREDEOF'
import sys
print("MINT", file=sys.stderr)
print("export AWS_ACCESS_KEY_ID=fake")
print("export AWS_SECRET_ACCESS_KEY=fake")
print("export AWS_SESSION_TOKEN=fake")
CREDEOF
mints=$(bash -c "
    source '$HELPER'
    export MUR_CREDENTIAL_HELPER='$scratch/fake_creds.py'
    aws() { mkdir -p \"\$(dirname \"\$4\")\"; echo stub > \"\$4\"; return 0; }
    localize_manifest granules '$scratch/many.json' '$scratch/out2' >/dev/null
" 2>&1 | grep -c MINT)
assert_eq "DAAC credentials are minted once for a whole manifest" "1" "$mints"
rm -rf "$scratch"

# --- transient fetch failures are retried ---------------------------------
#
# A MODIS sensor-day is ~350 granules. Observed on a real job: `aws s3 cp`
# died with SIGSEGV on one granule after the previous ones had transferred
# cleanly at 30 MB/s, and that single failure discarded the whole job --
# every granule already fetched included.

scratch=$(mktemp -d)

# Fails twice, then succeeds. A counter file survives the subshell the podaac
# branch runs `aws` in, which a shell variable would not.
cat > "$scratch/flaky_aws" <<'AWSEOF'
#!/bin/bash
# args: s3 cp <src> <dest>
count_file="${FLAKY_COUNT_FILE}"
n=$(( $(cat "$count_file" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$count_file"
if [[ "$n" -lt 3 ]]; then
    # Leave a partial file behind, exactly as a killed transfer would.
    printf 'partial' > "$4"
    exit 139        # SIGSEGV's shell status
fi
printf 'complete-and-good\n' > "$4"
exit 0
AWSEOF
chmod +x "$scratch/flaky_aws"

printf '0' > "$scratch/count"
out=$(PATH="$scratch:$PATH" FLAKY_COUNT_FILE="$scratch/count" \
      MUR_FETCH_RETRY_DELAY=0 bash -c "
    source '$HELPER'
    _ensure_podaac_credentials() { return 0; }
    mv '$scratch/flaky_aws' '$scratch/aws'
    fetch_uri 's3://podaac-ops-cumulus-protected/x.nc' '$scratch/x.nc' podaac
" 2>&1)
rc=$?

if [[ "$rc" -eq 0 && "$(cat "$scratch/x.nc" 2>/dev/null)" == "complete-and-good" ]]; then
    echo "PASS: a transient fetch failure is retried until it succeeds"
else
    echo "FAIL: retry did not recover (rc=$rc, content=$(cat "$scratch/x.nc" 2>/dev/null))"
    FAILURES=$((FAILURES + 1))
fi

# The partial file from a failed attempt must not survive. localize_manifest's
# readability check passes on a truncated file, so a leftover would be handed
# to MATLAB as though it were data.
if [[ "$(cat "$scratch/x.nc" 2>/dev/null)" != *partial* ]]; then
    echo "PASS: a partial file from a failed attempt is discarded"
else
    echo "FAIL: a partial file survived the retry"
    FAILURES=$((FAILURES + 1))
fi

# Retries are bounded: a genuinely dead source must still fail the job rather
# than spin forever.
cat > "$scratch/aws" <<'AWSEOF'
#!/bin/bash
printf 'partial' > "$4"
exit 139
AWSEOF
chmod +x "$scratch/aws"
out=$(PATH="$scratch:$PATH" MUR_FETCH_RETRIES=3 MUR_FETCH_RETRY_DELAY=0 bash -c "
    source '$HELPER'
    _ensure_podaac_credentials() { return 0; }
    fetch_uri 's3://podaac-ops-cumulus-protected/y.nc' '$scratch/y.nc' podaac
" 2>&1)
rc=$?
if [[ "$rc" -ne 0 ]]; then
    echo "PASS: a permanently failing fetch still fails the job"
else
    echo "FAIL: a dead source reported success"
    FAILURES=$((FAILURES + 1))
fi
attempts=$(grep -c 'attempt .* failed' <<< "$out")
assert_eq "retries are bounded by MUR_FETCH_RETRIES" "2" "$attempts"
if [[ ! -e "$scratch/y.nc" ]]; then
    echo "PASS: nothing is left behind by a fetch that never succeeded"
else
    echo "FAIL: a partial file survived a permanent failure"
    FAILURES=$((FAILURES + 1))
fi

# A missing mounted file will not appear on a second look. Retrying it only
# delays a failure that is already certain.
start=$(date +%s)
out=$(MUR_FETCH_RETRY_DELAY=5 bash -c "
    source '$HELPER'
    fetch_uri '$scratch/definitely-not-here.nc' '$scratch/z.nc' local
" 2>&1)
elapsed=$(( $(date +%s) - start ))
if [[ "$elapsed" -lt 3 ]]; then
    echo "PASS: a missing local file fails immediately rather than retrying"
else
    echo "FAIL: a missing local file was retried (${elapsed}s)"
    FAILURES=$((FAILURES + 1))
fi

rm -rf "$scratch"

echo ""
if [[ "$FAILURES" -eq 0 ]]; then
    echo "All tests passed."
    exit 0
else
    echo "$FAILURES test(s) failed."
    exit 1
fi
