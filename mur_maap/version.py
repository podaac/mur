"""The algorithm version, in one place.

This number appears in five: the four maap/<module>/algorithm_config.yml
files (as algorithm_version and again as the image tag in
algorithm_container_url), the CWL filenames generated from them, the tag
passed to the build scripts, and the version the orchestrator asks MAAP to
resolve. They must agree, and when they do not the failure is silent rather
than loud.

That is the whole problem. MAAP keeps every registered version, so asking for
a version that is merely OLD succeeds -- it resolves, it submits, the job
runs, and it runs last week's image. Nothing in the output says so. A
mismatched version is therefore not a configuration error that surfaces; it is
a wrong answer that looks like a right one.

So: Python reads the version from here, never from a config default, and
tests/test_algorithm_configs.py asserts the four YAML files agree with it.
Change it with utils/bump_algorithm_version.sh, which edits every place at
once rather than leaving four of five updated.
"""

ALGORITHM_VERSION = "2.0.2"
