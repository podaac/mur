#!/usr/bin/env python3
"""Resolve a container image tag to its immutable registry digest.

WHY NOT `docker buildx imagetools inspect`
    The CWL is generated and deployed from a MAAP workspace -- that is where
    deploy_algorithm_from_cwl_file() reads its file_path from -- and a
    workspace is a JupyterHub pod with no Docker daemon. Requiring docker to
    pin a digest would split one job across two machines: build on the MATLAB
    host, then carry a sha back to the workspace by hand.

    A registry digest is just an HTTP header. Reading it needs a network and
    nothing else, so this is stdlib-only for the same reason
    common/bin/maap_credentials.py is.

WHY A DIGEST AT ALL
    cwltool runs `docker pull` only when `docker inspect <dockerPull>` FAILS,
    so a DPS worker that has already run a tag keeps its cached copy even
    after the tag is rebuilt and repushed. A digest cannot be reused, so the
    inspect fails and the pull happens.

    Prefer rolling the version (utils/bump_algorithm_version.sh) for ordinary
    changes; pin a digest when a version number must stay put.

    ./utils/resolve_image_digest.py ghcr.io/podaac/mur/l2p-dps:2.0.0
    ghcr.io/podaac/mur/l2p-dps@sha256:1a2b...
"""
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

# A tag request returns the digest of whichever manifest the registry picks
# for this Accept set. Asking for the multi-arch types first gets the index
# digest -- the same one `docker buildx imagetools inspect` reports, and the
# one `docker pull repo@sha256:...` expects. Omitting them would pin a single
# architecture's manifest, which still works but says less than it appears to.
MANIFEST_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
)

DEFAULT_REGISTRY = "registry-1.docker.io"


def split_image(image):
    """"ghcr.io/podaac/mur/l2p-dps:2.0.0" -> (registry, repository, tag)."""
    if "@" in image:
        raise ValueError(f"{image} is already digest-pinned")

    head, _, tail = image.partition("/")
    # A registry is distinguishable from a namespace only by having a dot or a
    # port, or being localhost. "podaac/mur" has no registry; "ghcr.io/x" does.
    if tail and ("." in head or ":" in head or head == "localhost"):
        registry, remainder = head, tail
    else:
        registry, remainder = DEFAULT_REGISTRY, image

    repository, sep, tag = remainder.rpartition(":")
    if not sep or "/" in tag:            # no tag, or the colon was a port
        repository, tag = remainder, "latest"

    if registry == DEFAULT_REGISTRY and "/" not in repository:
        repository = f"library/{repository}"      # docker.io official images

    return registry, repository, tag


def _auth_token(registry, repository):
    """An anonymous pull token. Public packages need no credentials, but the
    registry still requires a bearer token rather than no Authorization."""
    if registry == DEFAULT_REGISTRY:
        service, host = "registry.docker.io", "auth.docker.io"
    else:
        service, host = registry, registry
    url = (f"https://{host}/token?service={urllib.parse.quote(service)}"
           f"&scope=repository:{urllib.parse.quote(repository)}:pull")
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            body = json.loads(resp.read().decode())
        return body.get("token") or body.get("access_token") or ""
    except (urllib.error.URLError, ValueError, OSError):
        # Some registries serve manifests unauthenticated.
        return ""


def digest_for(image, timeout=30):
    """The digest the registry currently publishes for this tag."""
    registry, repository, tag = split_image(image)

    headers = {"Accept": ", ".join(MANIFEST_TYPES)}
    token = _auth_token(registry, repository)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"https://{registry}/v2/{repository}/manifests/{urllib.parse.quote(tag)}"
    req = urllib.request.Request(url, headers=headers, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            digest = resp.headers.get("Docker-Content-Digest")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise SystemExit(
                f"{image}: the registry refused an anonymous pull ({exc.code}).\n"
                f"A CWL DockerRequirement carries no credentials either, so DPS\n"
                f"could not pull this image regardless. Make the package public.")
        if exc.code == 404:
            raise SystemExit(
                f"{image}: no such tag in the registry ({exc.code}).\n"
                f"Push the image before pinning it -- the digest is assigned\n"
                f"by the registry at push time.")
        raise SystemExit(f"{image}: registry returned HTTP {exc.code}")
    except (urllib.error.URLError, OSError) as exc:
        raise SystemExit(f"{image}: could not reach {registry}: {exc}")

    if not digest:
        # Every registry worth using sends this header on a manifest request.
        raise SystemExit(
            f"{image}: {registry} returned no Docker-Content-Digest header")
    if not digest.startswith("sha256:"):
        raise SystemExit(f"{image}: unexpected digest {digest!r}")

    return digest


def pinned_reference(image):
    """The full <repo>@sha256:... reference to write into a CWL."""
    registry, repository, tag = split_image(image)
    base = image[: -(len(tag) + 1)] if image.endswith(f":{tag}") else image
    return f"{base}@{digest_for(image)}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("image", help="e.g. ghcr.io/podaac/mur/l2p-dps:2.0.0")
    parser.add_argument("--digest-only", action="store_true",
                        help="print just sha256:... instead of repo@sha256:...")
    args = parser.parse_args(argv)

    if args.digest_only:
        print(digest_for(args.image))
    else:
        print(pinned_reference(args.image))
    return 0


if __name__ == "__main__":
    sys.exit(main())
