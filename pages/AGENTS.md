<!-- torve:managed pages — rendered from the corpus; do not edit by hand -->

## Decisions governing `pages/`

### S-0018/D-1 — `ASSUMED` (Project foundations: packaging, tooling, CI, docs)

House scaffold adopted from forze; deliberate divergences: the `rfcs` directory (since retired) is committed, mermaid over d2, no CI sharding/conformance/DST apparatus.

- Paths: `pages/zensical.toml`

### S-0018/D-13 — `ASSUMED` (Project foundations: packaging, tooling, CI, docs)

The repository slug is `morzecrew/bloomery`: `[project.urls]` in `pyproject.toml`, `repo_url` in `pages/zensical.toml`, the README badges and the changelog links all point at `https://github.com/morzecrew/bloomery`, the repository the package is pushed to

- Paths: `pyproject.toml` `pages/zensical.toml` `README.md` `CHANGELOG.md`
- Consequence: Moving the repository to another org or name is one coordinated edit of these four files, and the PyPI project links and the docs site follow them

<!-- /torve:managed -->
