# The base every sandbox image inherits (S-0063/D-7).
#
# What every definition needs and none of them should carry a copy of: git
# for the workspace, `python3` for the acceptance commands that call it
# bare, `uv` for the ones that do not, and the engine's own CLI.
#
# node:24-slim rather than a python base because four of the six harnesses
# are npm packages and the fifth would have had to install node anyway. The
# CLI layer below installs its own interpreter through uv, so nothing here
# depends on the base's python — `python3` is present for a repository
# whose battery calls it directly, not for torve.
FROM node:24-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      git curl ca-certificates python3 zstd \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# The engine's own CLI, for the verbs an attempt calls from inside its
# sandbox: `torve log divergence` records a divergence through the run's
# channel, `torve log notes` reads what the engine had to say. Without it
# the prompt names commands the sandbox does not have.
#
# Its own interpreter and its own environment, under /opt/torve: the
# repository under work owns the workspace, and the intake must not depend
# on what that repository happens to install — or on it being a Python
# project at all. The interpreter is installed where every uid can read it,
# because a sandbox runs as the host's uid and uv's default install
# directory is root's home; the build proves it by running the verb as
# `nobody` rather than as the user that built it.
#
# The context is the repository root, so the project's inputs are named
# rather than swept — a `COPY .` here would bake the worktree, the venv and
# every artefact into a layer.
#
# The list is what `project_inputs` reads off pyproject.toml, and
# `tests/test_sandbox_defs.py` holds the two in step. It is a hand-kept list
# in a Dockerfile, which went stale once before when it was a hand-kept list
# in Python; the check is what makes that a red test rather than a wheel
# that builds without its package data.
COPY pyproject.toml uv.lock README.md LICENSE /opt/torve/build-context/
COPY src /opt/torve/build-context/src
COPY skills /opt/torve/build-context/skills
COPY migrations /opt/torve/build-context/migrations
ENV UV_PYTHON_INSTALL_DIR=/opt/torve/python
RUN set -eu; \
    uv python install 3.13; \
    uv venv --python 3.13 /opt/torve/cli; \
    UV_PROJECT_ENVIRONMENT=/opt/torve/cli \
      uv sync --locked --no-cache --no-dev --no-editable \
        --project /opt/torve/build-context; \
    ln -sf /opt/torve/cli/bin/torve /usr/local/bin/torve; \
    chmod -R a+rX /opt/torve/python /opt/torve/cli; \
    su -s /bin/sh -c "torve --version" nobody; \
    rm -rf /opt/torve/build-context

# Where a definition puts the two scripts the engine runs (S-0063/D-1,
# S-0063/D-3). The base carries neither: it contains no harness, so it has
# nothing to invoke and nothing to equip. `sandbox-base` is not a runnable
# seat, and a definition that inherits it without writing them is an image
# no seat can use.
RUN mkdir -p /opt/torve
