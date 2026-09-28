# Cloud lanes

Four dialect ports target engines that run in no container — Snowflake, BigQuery, Redshift
and Databricks — and each is established by the ladder [Dialects](../reference/dialects.md)
describes: offline rungs on every pull request, a *surrogate* lane that is evidence and never
the oracle, and the engine's own compiler as the oracle. The surrogate lanes need nothing but
Docker (and a JVM, which CI installs, for the Spark one). The authoritative lanes need an
account each, and every one of them **skips with a stated reason** until its account is
wired, so a green run without one says only that the lane did not run. This page is what to
create, where to put it, and what it costs.

Every credential lives in a GitHub *environment*, never in the repository, and a pull request
from a fork reaches none of them (S-0012/D-5). Variables name things a log may print — an
account, a project, a warehouse; secrets hold the one bearer per engine. The authoritative
lanes run on a push to `main` and on a release tag (`force_full`), never on a pull request;
the surrogate lanes need no credential and run on a pull request too, whenever its diff
touches engine code.

## Snowflake — `EXPLAIN USING JSON`, then the execution corpus

| What | Where | Value |
|---|---|---|
| environment | `snowflake` | exists, empty |
| `SNOWFLAKE_ACCOUNT` | variable | the account identifier, e.g. `xy12345.eu-central-1` |
| `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`, `SNOWFLAKE_ROLE` | variables | the database and schema the compile lane resolves names in, and the role the session takes |
| `SNOWFLAKE_TOKEN` | secret | a programmatic access token for a user holding that role |
| `SNOWFLAKE_WAREHOUSE` | variable | **optional** — names the warehouse the execution corpus runs on; unset, the lane is compile-only |

The compile lane reads the named database and schema and writes nothing. The execution
corpus does not use them: it creates a **transient database of its own** per run, builds in
it, and drops it at the end (`tests/support/snowflake.py`), so the role needs `CREATE
DATABASE` on the account and `USAGE` on the warehouse — not only rights inside the
documented database.

The compile lane (`tests/engines/test_snowflake_live.py`, job `snowflake-compile`) submits
`EXPLAIN USING JSON` for every statement the shared corpus renders: the engine's parser,
binder and function resolution, no data scanned, no warehouse needed. The execution corpus in
the same module runs only when `SNOWFLAKE_WAREHOUSE` is set; an X-Small warehouse with
auto-suspend at one minute holds its cost to seconds of compute per run.

Snowflake has no perpetual free tier. A trial account (30 days, with credits) is enough to
wire the lane and to run the corpus a few times; after that the compile lane is the one worth
keeping, since it costs no compute.

## BigQuery — a dry run, then the execution corpus

| What | Where | Value |
|---|---|---|
| environment | `bigquery` | create it |
| `BIGQUERY_PROJECT`, `BIGQUERY_DATASET` | variables | a project and a tiny dataset that exists before the lane does (S-0014/D-5) |
| `BIGQUERY_WORKLOAD_IDENTITY_PROVIDER` | variable | `projects/<number>/locations/global/workloadIdentityPools/<pool>/providers/<provider>` |
| `BIGQUERY_SERVICE_ACCOUNT` | variable | the service account's email |
| `BIGQUERY_EXECUTE` | variable | **optional** — any value enables the execution corpus beside the dry run |

No key file anywhere: CI authenticates with Workload Identity Federation from the job's OIDC
token (S-0014/D-4), which is what `id-token: write` on the `bigquery-dry-run` job is for.
The **BigQuery sandbox** needs no billing account and covers this lane whole: a dry run
scans no bytes and bills nothing, and the execution corpus reads a few kilobytes.

Once, with `gcloud` on the project:

```sh
PROJECT=<project-id>; NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
gcloud iam workload-identity-pools create github --location=global --project="$PROJECT"
gcloud iam workload-identity-pools providers create-oidc github \
  --location=global --workload-identity-pool=github --project="$PROJECT" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository == 'morzecrew/bloomery'"
gcloud iam service-accounts create bloomery-ci --project="$PROJECT"
SA="bloomery-ci@$PROJECT.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" --role=roles/bigquery.jobUser
gcloud iam service-accounts add-iam-policy-binding "$SA" --project="$PROJECT" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/morzecrew/bloomery"
bq --project_id="$PROJECT" mk --dataset "$PROJECT:bloomery_ci"
```

Then grant the service account `BigQuery Data Editor` on that dataset, and set the
variables: the provider is
`projects/$NUMBER/locations/global/workloadIdentityPools/github/providers/github`.

## Databricks — `EXPLAIN EXTENDED` and `DESCRIBE QUERY`, then the runtime corpus

| What | Where | Value |
|---|---|---|
| environment | `databricks-free` | create it |
| `DATABRICKS_HOST` | variable | the workspace URL |
| `DATABRICKS_WAREHOUSE_ID` | variable | a serverless SQL warehouse's id (2X-Small is enough) |
| `DATABRICKS_TOKEN` | secret | a personal access token (S-0016/D-5: the documented path on Free Edition) |

The workflow is `.github/workflows/databricks-live.yaml`: weekly and on demand, never on a
pull request; `compile` first, `runtime` after it, in catalog `workspace` and schema
`bloomery_conformance`. **Databricks Free Edition** is enough to bootstrap it (S-0016/D-6)
and not enough to run the generated corpus at scale, which is why the lane stays small.

The Spark surrogate (`tests/engines/test_databricks_surrogate.py`, marker
`surrogate("databricks_spark")`) needs no account: local PySpark from the `spark` dependency
group and a JVM, both of which the `engine-e2e` job now provides.

## Redshift — `EXPLAIN`, DDL and the targeted corpus

| What | Where | Value |
|---|---|---|
| environment | `redshift` | create it |
| `REDSHIFT_CONFIGURED` | repository variable | `true` turns the job on |
| `REDSHIFT_DSN` | secret | a full `postgresql://` DSN to a cluster or Serverless workgroup |

Nothing here is free for long: a Redshift Serverless trial carries credits for a limited
time, and a provisioned cluster bills by the hour. Until one exists the job `redshift-live`
stays off, and the **PostgreSQL surrogate** (`tests/engines/test_redshift_surrogate.py`,
marker `surrogate("redshift_postgres")`) is the only local evidence — which is exactly why
its test names say PostgreSQL accepted the query, and nothing more (S-0015/D-2).

## Reading a run

Every lane above skips rather than fails when its account is missing, and each skip names
the variable that is unset (`-rs` in the job's `pytest` call prints them). A lane that runs
and is green has spoken for the engine; a lane that skipped has not, and the job's log is
where the difference shows.
