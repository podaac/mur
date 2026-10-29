"""Job tags: which batch a job lands in on the MAAP Console.

The Console's Batches view (console.maap-project.org/batches) groups jobs by
their tag -- a batch IS one tag value, and /batches/<tag> is its page. So the
tag is a batch name, one per kind of job:

    MUR-COG  MUR-L2P  MUR-iQUAM  MUR-LANDICE  MUR-MRVA

and every job of that kind, from every day and both modes, is listed under it.

The tag used to be per job (mur.nrt.2026-09-20.l2p.AMSR2R.2026-09-18), which
made every job its own one-job batch and buried the view under hundreds of
them. The cost of grouping: inside a batch the Console labels each job only
by its Job Type (mur-l2p_1756 2.0.19), so which day, sensor or resolution a
row is shows only in that job's inputs. The tag can carry no more than the
batch name -- MAAP has no separate per-job name field to put the detail in.
"""

BATCHES = {
    "cog": "MUR-COG",
    "iquam": "MUR-iQUAM",
    "l2p": "MUR-L2P",
    "landice": "MUR-LANDICE",
    "mrva": "MUR-MRVA",
}


def batch(stage: str) -> str:
    """The batch name for a stage ("l2p") or its process id ("mur-l2p").

    A process with no entry still gets a MUR-<NAME> batch rather than an
    error: a submit is not the place to fail over a label.
    """
    stage = stage.removeprefix("mur-")
    return BATCHES.get(stage, f"MUR-{stage.upper()}")
