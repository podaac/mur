"""Resolving an image tag to a registry digest.

This runs in the MAAP workspace -- where the CWL is generated and deployed
from -- which is a JupyterHub pod with no Docker daemon. So the resolution is
plain HTTPS against the registry, and these tests cover the parsing and the
error paths without touching the network.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "utils"))

from resolve_image_digest import DEFAULT_REGISTRY, split_image  # noqa: E402


@pytest.mark.parametrize("image,expected", [
    # The one that matters: every MUR image looks like this.
    ("ghcr.io/podaac/mur/l2p-dps:2.0.0", ("ghcr.io", "podaac/mur/l2p-dps", "2.0.0")),
    ("ghcr.io/podaac/mur/mrva-dps:2.0.1", ("ghcr.io", "podaac/mur/mrva-dps", "2.0.1")),
    # A registry is told from a namespace by a dot, a port, or localhost --
    # there is no other signal in the string.
    ("podaac/mur:1.0", (DEFAULT_REGISTRY, "podaac/mur", "1.0")),
    ("ubuntu:22.04", (DEFAULT_REGISTRY, "library/ubuntu", "22.04")),
    ("localhost:5000/x/y:t", ("localhost:5000", "x/y", "t")),
    # No tag means latest, which is never what a CWL should pin.
    ("ghcr.io/a/b", ("ghcr.io", "a/b", "latest")),
])
def test_split_image(image, expected):
    assert split_image(image) == expected


def test_a_port_in_the_registry_is_not_mistaken_for_a_tag():
    """rpartition(':') would otherwise read "5000/x/y" as the tag."""
    _, repo, tag = split_image("localhost:5000/x/y")
    assert (repo, tag) == ("x/y", "latest")


def test_an_already_pinned_reference_is_refused():
    """Pinning a pin would produce repo@sha256:a@sha256:b."""
    with pytest.raises(ValueError, match="already digest-pinned"):
        split_image("ghcr.io/podaac/mur/l2p-dps@sha256:" + "a" * 64)


def test_the_resolver_needs_no_docker_and_no_third_party_package():
    """The workspace has neither a Docker daemon nor a guarantee of requests.
    An import added here is a dependency on the machine that deploys."""
    import ast
    source = pathlib.Path(
        pathlib.Path(__file__).resolve().parent.parent / "utils" /
        "resolve_image_digest.py").read_text()
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    stdlib = {"argparse", "json", "sys", "urllib"}
    assert imported <= stdlib, f"non-stdlib imports: {sorted(imported - stdlib)}"
    assert "subprocess" not in source and "docker" not in source.lower().split("\n")[0]


def test_the_multi_arch_manifest_types_are_requested_first():
    """Asking only for a single-image manifest pins one architecture while
    looking like it pinned the image."""
    from resolve_image_digest import MANIFEST_TYPES
    assert MANIFEST_TYPES[0].endswith("index.v1+json")
    assert any("manifest.list" in t for t in MANIFEST_TYPES)


def test_generate_cwl_uses_this_and_not_docker():
    script = (pathlib.Path(__file__).resolve().parent.parent /
              "utils" / "generate_cwl.sh").read_text()
    assert "resolve_image_digest.py" in script
    assert "imagetools" not in script, \
        "generate_cwl.sh still shells to docker; it must run in the workspace"
