"""Comparing a day's inputs between MAAP and production.

Everything here is the parsing and selection the comparison rests on: if a
DPS key, a makebiq log line or the ssh dump is misread, the report says the
two pipelines disagree when they do not, or worse, agree when they do not.
"""
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "utils"))

import compare_maap_prod_inputs as cmp  # noqa: E402


def test_dps_key_with_workspace_prefix():
    f = cmp.parse_dps_key(
        "jleach/dps_output/mur-mrva_1756/2.0.12/2026/10/08/18/10/20/964098/"
        "csp/2026/2026100709_MRVA4_Global_inputs.txt")
    assert f.algo == "mur-mrva_1756"
    assert f.job.endswith("/2026/10/08/18/10/20/964098")
    assert f.rel == "csp/2026/2026100709_MRVA4_Global_inputs.txt"
    assert f.name == "2026100709_MRVA4_Global_inputs.txt"
    assert f.ts == (2026, 10, 8, 18, 10, 20, 964098)
    assert f.when == "2026-10-08 18:10:20Z"


def test_dps_key_with_a_tag_level_and_at_bucket_root():
    f = cmp.parse_dps_key(
        "dps_output/mur-l2p_1756/2.0.19/MUR-L2P/2026/10/21/03/00/01/7/"
        "L2Plist_Global_MODISA_2026_293.txt")
    assert f.algo == "mur-l2p_1756"
    assert f.rel == "L2Plist_Global_MODISA_2026_293.txt"
    assert f.ts[:3] == (2026, 10, 21)


def test_non_dps_key_is_ignored():
    assert cmp.parse_dps_key("jleach/mur/bic/AMSR2R/2026/293.bic.gz") is None


def test_run_times_order_numerically_not_lexically():
    early = cmp.parse_dps_key("dps_output/a/v/2026/10/08/18/10/20/99/x")
    late = cmp.parse_dps_key("dps_output/a/v/2026/10/08/18/10/20/100/x")
    assert early.ts < late.ts


def test_inputs_txt():
    rt, rows = cmp.parse_inputs_txt(
        "RealTime 0 0 0 (realtime if this line exists)\n"
        "AMSR2R 2026 291 1234567 points\n"
        "MODIST 2026 293 0 points (no file)\n"
        "IQUAM0 2026 290 0 points (invalid nday=0)\n")
    assert rt is True
    assert rows[("AMSR2R", 2026, 291)] == (1234567, "")
    assert rows[("MODIST", 2026, 293)] == (0, "(no file)")
    assert rows[("IQUAM0", 2026, 290)] == (0, "(invalid nday=0)")


def test_inputs_txt_without_realtime_line_is_rea():
    rt, _ = cmp.parse_inputs_txt("AMSR2R 2026 291 5 points\n")
    assert rt is False


def test_file_names_compare_by_basename():
    prod = "/nas2/l2p/x/20261020-A.nc\n/nas2/l2p/x/20261020-B.nc\n\n"
    maap = "/data/input/20261020-B.nc\n/data/input/20261020-C.nc\n"
    d = cmp.diff_names(cmp.file_names(prod), cmp.file_names(maap))
    assert d["common"] == 1
    assert d["only_prod"] == ["20261020-A.nc"]
    assert d["only_maap"] == ["20261020-C.nc"]


def test_remote_dump_round_trip():
    dump = (
        "@@@BEGIN /nas2/bic/A/L2Plist.txt\n"
        "/x/g1.nc\n/x/g2.nc\n\n"
        "@@@END /nas2/bic/A/L2Plist.txt\n"
        "@@@MISSING /nas2/bic/B/L2Plist.txt\n"
        "@@@SIZE /nas2/iquam/2026/Global_IQUAM0_2026_293.bii 40960\n"
        "@@@MISSING /nas2/iquam/2026/Global_IQUAM0_2026_294.bii\n")
    text, size = cmp.parse_remote_dump(dump)
    assert cmp.file_names(text["/nas2/bic/A/L2Plist.txt"]) == ["g1.nc", "g2.nc"]
    assert text["/nas2/bic/B/L2Plist.txt"] is None
    assert size["/nas2/iquam/2026/Global_IQUAM0_2026_293.bii"] == 40960
    assert size["/nas2/iquam/2026/Global_IQUAM0_2026_294.bii"] is None


def test_remote_script_quotes_paths():
    script = cmp.remote_script(["/a b/c.txt"], ["/d.bii"])
    assert "emit '/a b/c.txt'" in script
    assert "size /d.bii" in script


def test_find_params_digs_through_job_json():
    job = {"job": {"params": {"inputs": {"prior_csp_file": "s3://b/k.c06",
                                         "mode": "nrt",
                                         "unrelated": 1}}}}
    assert cmp.find_params(job) == {"prior_csp_file": "s3://b/k.c06", "mode": "nrt"}


def _f(ts):
    return cmp.parse_dps_key(f"dps_output/mur-mrva_1/v/{ts}/0/x")


def test_choose_mrva_matches_prods_kind_by_default():
    nrt = (_f("2026/10/21/01/00/00"), True)
    rea = (_f("2026/10/24/01/00/00"), False)
    nrt_again = (_f("2026/10/22/01/00/00"), True)
    cands = [nrt, rea, nrt_again]
    assert cmp.choose_mrva(cands, "auto", prod_realtime=True) is nrt_again
    assert cmp.choose_mrva(cands, "auto", prod_realtime=False) is rea
    assert cmp.choose_mrva(cands, "auto", prod_realtime=None) is rea   # latest
    assert cmp.choose_mrva(cands, "nrt", prod_realtime=False) is nrt_again


def test_choose_mrva_falls_back_when_no_run_of_that_kind():
    only_nrt = [(_f("2026/10/21/01/00/00"), True)]
    assert cmp.choose_mrva(only_nrt, "rea", prod_realtime=None) is only_nrt[0]
    assert cmp.choose_mrva([], "auto", prod_realtime=True) is None


def _sample_report(prior_csp="s3://b/2026101909_MRVA4_Global.c06"):
    return {
        "date": "2026-10-20", "year": 2026, "doy": 293, "host": "podaac-mure",
        "generated": "2026-10-28 12:00 UTC",
        "differences": {"mrva_ingest": 1, "l2p": 1, "landice": 0, "iquam": 0},
        "mrva_ingest": {
            "prod_file": "/nas4/cyc4out/2026/2026102009_MRVA4_Global_inputs.txt",
            "prod_realtime": False, "maap_realtime": True,
            "maap_job": "u/dps_output/mur-mrva_1/v/2026/10/21/01/00/00/1",
            "maap_when": "2026-10-21 01:00:00Z",
            "candidates": [{"when": "2026-10-21 01:00:00Z", "realtime": True,
                            "job": "u/dps_output/mur-mrva_1/v/2026/10/21/01/00/00/1"}],
            "rows": [
                {"sensor": "AMSR2R", "year": 2026, "doy": 293, "prod": 1000,
                 "prod_note": "", "maap": 990, "maap_note": "", "match": False},
                {"sensor": "MODIST", "year": 2026, "doy": 294, "prod": 0,
                 "prod_note": "(no file)", "maap": 0, "maap_note": "(no file)",
                 "match": True},
            ]},
        "mrva_params": {"mode": "nrt", "prior_csp_file": prior_csp},
        "l2p": [{"sensor": "MODISA", "year": 2026, "doy": 293,
                 "prod_missing": False, "maap_versions": ["2026-10-21 00:00:00Z"],
                 "prod": 3, "maap": 2, "common": 2,
                 "only_prod": ["<late>.nc"], "only_maap": [], "note": "1"}],
        "landice": {"prod": 2, "maap": 2, "common": 2, "only_prod": [],
                    "only_maap": [], "prod_file": "/p/icefiles.txt",
                    "maap_key": "u/mur/landice/icefiles.txt"},
        "iquam": [{"year": 2026, "doy": 293, "prod": 10, "maap": 10, "match": True}],
    }


def test_html_report_shows_each_stage_and_escapes_names():
    page = cmp.render_html(_sample_report())
    assert page.startswith("<!doctype html>")
    for heading in ("MRVA ingest", "MRVA job parameters", "L2P granules per BIC",
                    "Land/ice", "iQUAM"):
        assert heading in page
    assert "-10" in page and "-1.00%" in page          # AMSR2R 1000 -> 990
    assert "&lt;late&gt;.nc" in page and "<late>" not in page
    assert "no run of the same kind" in page            # prod REA vs MAAP NRT
    assert "bootstrapped" not in page


def test_html_report_warns_when_mrva_bootstrapped():
    page = cmp.render_html(_sample_report(prior_csp=None))
    assert "bootstrapped" in page


def test_find_params_reads_dps_hyphenated_names_and_keeps_empty_values():
    # The shape of a real mur-mrva outputs_result-*.context.json (2026/293).
    ctx = {"job_specification": {"params": [{"name": "prior-csp-file"}]},
           "inputs": {"mode": "nrt", "prior-csp-file": "", "doy": "293"}}
    assert cmp.find_params(ctx) == {"mode": "nrt", "prior_csp_file": ""}
