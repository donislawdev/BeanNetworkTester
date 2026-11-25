# The command line as a container image: ghcr.io/donislawdev/beannetworktester.
#
# Not built from source. The build context is the Linux package of a PUBLISHED
# release, unpacked by .github/workflows/docker.yml only after its checksum and
# its build provenance checked out. So the program in the image is, byte for
# byte, the one a person downloads, and its licences and notices travel inside
# it (_internal/LICENSE, THIRD-PARTY-NOTICES.md, licenses/).
#
# Ubuntu 24.04 because the package is built and tested on it: the program uses
# the system's C library, and one older than the build's refuses to start it.
# Pinned by digest, which Dependabot moves (.github/dependabot.yml), and every
# move is tried by the workflow's pull request run before it is merged.
FROM ubuntu:24.04@sha256:562111b88caa79c71391c0c4d3c2114a7d5c35915c20561fd893cb1e07929e6b

COPY BeanNetworkTester /opt/beannetworktester

# Files a run writes (--log-conns, --repro-out, a CSV) go to the folder the
# caller mounts here, and a scenario file is read from it.
WORKDIR /work

# Root on purpose. A capture needs CAP_BPF, CAP_PERFMON and CAP_NET_ADMIN, and
# what `docker run --cap-add` grants is held by root; any other user gets them
# only as a limit it may never use, and --doctor answers FAIL. For that reason
# semgrep's two rules asking for a USER are silenced here, each by name
# (tests/test_repo_conventions.py lists every suppression in the repository).
# nosemgrep: dockerfile.security.missing-user-entrypoint.missing-user-entrypoint
ENTRYPOINT ["/opt/beannetworktester/BeanNetworkTester"]

# With no arguments the program opens its window, and an image has no screen:
# it would print advice about a missing font library instead of how to use it.
# nosemgrep: dockerfile.security.missing-user.missing-user
CMD ["--help"]
