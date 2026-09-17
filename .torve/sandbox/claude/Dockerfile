# Sandbox image for harness-backed agents (S-0004): the harness is baked into
# the image, never injected from the host. git, python3, uv and the engine's
# own CLI come from the base (S-0063/D-7); this adds claude and nothing else.
ARG BASE=sandbox-base
FROM ${BASE}
# The harness version rides a pinned-default ARG (S-0033/D-3): a bump is a
# one-line reviewed diff, never a rebuild side effect.
ARG CLAUDE_VERSION=2.1.252
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_VERSION} && claude --version

# What this definition puts inside the image (S-0063/D-14): `toolkit/` is
# `/opt/torve`, named for where its contents land, and one COPY installs the
# lot. `/opt/torve/equip` turns the equipment manifest into whatever this
# harness needs and `/opt/torve/run` invokes it; the engine names only what the
# attempt is.
COPY toolkit/ /opt/torve/
RUN chmod -R a+rX /opt/torve && chmod +x /opt/torve/run /opt/torve/equip

# No plugin is baked (S-0063/D-9). The image used to carry pinned clones of
# caveman and ponytail so the retired renderer could write bookkeeping beside
# them; both are equipment now, fetched host-side into a cache this mounts
# read-only (S-0062/D-4). Two copies of a repository with one reader was the
# whole cost of keeping them here.
