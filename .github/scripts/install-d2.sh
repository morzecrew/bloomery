#!/usr/bin/env bash
# Install the d2 diagram compiler that `just build-diagrams` shells out to.
#
# Pinned by version *and* by artifact hash. d2 publishes no checksums file
# alongside its releases, so the digest below was computed from the downloaded
# v0.7.1 linux-amd64 tarball and is checked on every run: an upstream artifact
# that changes under its tag fails here rather than silently rendering the
# published documentation with something else.
#
# Override with D2_VERSION; an override must bring its own D2_SHA256, because a
# pin that falls back to "whatever downloaded" is not a pin.
set -euxo pipefail

D2_VERSION="${D2_VERSION:-v0.7.1}"

if [ "$D2_VERSION" = "v0.7.1" ]; then
	D2_SHA256="${D2_SHA256:-eb172adf59f38d1e5a70ab177591356754ffaf9bebb84e0ca8b767dfb421dad7}"
else
	D2_SHA256="${D2_SHA256:?overriding D2_VERSION requires D2_SHA256 for the tarball}"
fi

curl -LsSf -o /tmp/d2.tar.gz \
	"https://github.com/terrastruct/d2/releases/download/${D2_VERSION}/d2-${D2_VERSION}-linux-amd64.tar.gz"
echo "${D2_SHA256}  /tmp/d2.tar.gz" | sha256sum --check --strict

mkdir -p /tmp/d2-extract
tar -xzf /tmp/d2.tar.gz -C /tmp/d2-extract
sudo mv "$(find /tmp/d2-extract -type f -name d2 | head -n 1)" /usr/local/bin/d2
sudo chmod +x /usr/local/bin/d2

d2 --version
