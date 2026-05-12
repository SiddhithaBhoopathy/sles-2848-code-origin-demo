# Code Origin for Python on GCP Cloud Run Functions (Gen 2)

End-to-end working example of a Python Cloud Run Function (Gen 2) instrumented
with Datadog APM and **Code Origin for Spans** enabled.

References:
- [Instrumenting a Python Cloud Run Function](https://docs.datadoghq.com/serverless/google_cloud_run/functions/python/?tab=datadogcli)
- [Code Origin for Spans](https://docs.datadoghq.com/tracing/code_origin/)
- [Source Code Integration](https://docs.datadoghq.com/integrations/guide/source-code-integration/)

## Why CLI over manual setup

Use `datadog-ci cloud-run instrument`. It is strictly the easier path because
it does all of the following for you, any of which is easy to get wrong by
hand:

- Injects the `serverless-init` sidecar container with the right image tag.
- Creates the shared in-memory volume and mounts it into **both** containers
  at the same path.
- Sets `DD_API_KEY`, `DD_SITE`, `DD_SERVERLESS_LOG_PATH`, and `FUNCTION_TARGET`
  on the sidecar container (not the app container).
- Adds the `service` label on the Cloud Run service so it shows up in the
  Software Catalog.

Manual setup is only worth doing if you have an existing IaC pipeline (e.g.
Terraform via the [`DataDog/cloud-run-datadog`](https://github.com/DataDog/terraform-google-cloud-run-datadog) module) and need full control.

## Code Origin gotchas (the reason it's "not working")

Code Origin is enabled by `DD_CODE_ORIGIN_FOR_SPANS_ENABLED=true`, but the
following four things must **all** be true or it silently does nothing:

1. **`ddtrace>=2.15.0`** in `requirements.txt`. (See `requirements.txt`.)
2. **A supported framework is auto-instrumented.** For Python that means
   Django / Flask / Starlette / derivatives. Cloud Run Functions run on top of
   `functions-framework` which is Flask under the hood — but it is only
   instrumented if `ddtrace.auto` is imported **before** any framework
   imports. Cloud Run Functions do not use `ddtrace-run`, so this import is
   mandatory and must be the first line of `main.py`. (See `main.py`.)
3. **`DD_CODE_ORIGIN_FOR_SPANS_ENABLED=true`** is on the **application**
   container, not the sidecar. (See `build_and_deploy.sh`'s `--set-env-vars`
   block.)
4. **`DD_GIT_REPOSITORY_URL` and `DD_GIT_COMMIT_SHA`** are set if you want the
   in-UI code preview. Without them Code Origin still attaches file/line/method
   metadata to the span, but the source preview panel will be blank. The
   script auto-derives both from `git` when the workspace is a git repo with
   an `origin` remote.

In Trace Explorer, Code Origin only appears on **Service Entry Spans**. Filter
to `@_dd.span_kind:server` (or use the "Service Entry Spans" preset) — it is
not on every span.

## Files in this repo

| File | Purpose |
| ---- | ------- |
| `main.py` | The Cloud Run Function. First line is `import ddtrace.auto`. |
| `requirements.txt` | `ddtrace==4.5.0` (>= 2.15.0 required for Code Origin), `datadog`, `functions-framework`, `flask`. |
| `Procfile` | One-liner that tells the Python buildpack to launch the app via `functions-framework --target=main`. |
| `build_and_deploy.sh` | `gcloud run deploy --source=.` then `datadog-ci cloud-run instrument`. Sources `.env` if present. All container env vars (including `DD_CODE_ORIGIN_FOR_SPANS_ENABLED=true`) are passed inline via `--set-env-vars`. |
| `.env.example` | Committable template. Copy to `.env` and fill in. |
| `.env` | Per-developer overrides (gitignored). Holds `DD_API_KEY`. |
| `.gitignore` | Excludes `.env`, caches, IDE state. |
| `DEPLOY.md` | Step-by-step runbook with verification commands. |

## Prerequisites

```bash
# gcloud CLI authenticated
gcloud auth login
gcloud auth application-default login

# Datadog CLI plugin for Cloud Run
npm install -g @datadog/datadog-ci @datadog/datadog-ci-plugin-cloud-run
```

## Deploy

```bash
cp .env.example .env
${EDITOR:-vi} .env       # fill in values; DD_API_KEY is optional (see below)

./build_and_deploy.sh
```

`DD_API_KEY` is optional. The script behaves differently depending on
whether it's set:

- **Key set in `.env`** — `gcloud run deploy` runs, then
  `datadog-ci cloud-run instrument` runs. The latter validates the key
  against Datadog's API (refuses to proceed if invalid), then injects the
  `serverless-init` sidecar, the shared in-memory volume, and the sidecar
  env vars onto a new revision. Telemetry starts flowing within ~30s.
- **Key unset in `.env`** — only `gcloud run deploy` runs. The script
  prints a "skipping instrumentation" message and exits 0. The function
  is live but has no Datadog sidecar yet. Add the key to `.env` and
  re-run to attach the sidecar — no code changes needed in between.
  This is the right path for prod GCP accounts where the deploying user
  doesn't hold the Datadog API key (someone with the key re-runs the
  script once it's available).

> An earlier version of this script tried to bake a placeholder
> `DD_API_KEY` onto the sidecar so the instrumentation step could always
> run. That doesn't work: `datadog-ci cloud-run instrument` validates the
> key live against `https://api.<DD_SITE>` before it patches the service.

### Authentication requirements (both required)

```bash
gcloud auth login                          # for `gcloud run deploy`
gcloud auth application-default login      # for `datadog-ci cloud-run instrument`
```

`datadog-ci` uses the Google Cloud Node SDK, which only reads
[Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials)
— not the regular `gcloud auth login` token. Without ADC you'll see
`Unable to authenticate with GCP` from `datadog-ci` even after a clean
`gcloud auth login`. See `DEPLOY.md` step 1 for the full setup.

## Verify Code Origin is working

1. Hit the function URL a handful of times so spans are generated:

   ```bash
   URL=$(gcloud run services describe "$GCP_FUNCTION_NAME" --region "$REGION" --format='value(status.url)')
   for i in {1..10}; do curl -s "$URL" >/dev/null; done
   ```

2. In Datadog go to **APM → Trace Explorer**.
3. Filter: `service:code-origin-demo` and add the **Service Entry Spans** filter.
4. Click a span → on the **Overview** tab look for the **Code Origin** section.
   You should see:
   - File: `main.py`
   - Line: the line where `def main(request)` is defined
   - Method: `main`
   - A code preview of `main.py` (if `DD_GIT_*` are set and the commit is
     pushed to the configured remote).

## Troubleshooting

### "Code Origin" section is missing from the span

- Confirm `DD_CODE_ORIGIN_FOR_SPANS_ENABLED=true` is set on the **application**
  container (Cloud Run console → service → revision → container "main" → variables).
- Confirm you are looking at a **Service Entry Span**, not a child span.
- Confirm `ddtrace>=2.15.0` is installed in the deployed container:

  ```bash
  gcloud run services describe "$GCP_FUNCTION_NAME" --region "$REGION" \
    --format='value(spec.template.spec.containers[0].image)'
  ```

  then pull and inspect the image, or run `pip show ddtrace` locally against
  `requirements.txt`.
- Confirm `import ddtrace.auto` is the **first** import in `main.py`. If
  something (e.g. `from flask import Request`) is imported above it, Flask
  will not be instrumented and no service-entry span is produced.

### Code preview is blank but file/line are populated

- `DD_GIT_REPOSITORY_URL` and `DD_GIT_COMMIT_SHA` aren't set, OR the commit
  hasn't been pushed to the remote Datadog is trying to fetch from.
- Verify on a span in Trace Explorer — the **Infrastructure** tab will list
  the environment variables actually set on the container.

### Traces appear but no logs (or vice versa)

- Logs from the **first revision** of the service (the one created by
  `gcloud run deploy` before `datadog-ci instrument` ran) will never reach
  Datadog because that revision has no sidecar / no shared volume. Logs
  from the second revision onward (created by `datadog-ci instrument`)
  will work. Check the **active** revision in `gcloud run services
  describe` — it should be the one with two containers.
- Make sure `PYTHONUNBUFFERED=1` is set on the app container. The script
  sets it via `--set-env-vars`; confirm in the Cloud Run console under
  the revision's environment variables.
- Make sure `DD_LOGS_INJECTION=true` is set (same place).
- Confirm the shared volume is mounted at `/shared-volume` in **both**
  containers:
  ```bash
  gcloud run services describe "$GCP_FUNCTION_NAME" --region "$REGION" \
    --format=json | jq '.spec.template.spec.containers[].volumeMounts'
  ```
