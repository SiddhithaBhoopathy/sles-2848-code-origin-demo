# Code Origin for Python on GCP Cloud Run Functions (Gen 2)

End-to-end working example of a Python Cloud Run Function (Gen 2) instrumented
with Datadog APM and **Code Origin for Spans** enabled.

References:
- [Instrumenting a Python Cloud Run Function](https://docs.datadoghq.com/serverless/google_cloud_run/functions/python/?tab=datadogcli)
- [Code Origin for Spans](https://docs.datadoghq.com/tracing/code_origin/)
- [Source Code Integration](https://docs.datadoghq.com/integrations/guide/source-code-integration/)



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

