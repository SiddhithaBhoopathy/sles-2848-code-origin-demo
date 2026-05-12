# Deployment Instructions

Step-by-step checklist to deploy this Python Cloud Run Function (Gen 2) with
Datadog Code Origin enabled. Run each block in order; verification command
at the end of each step.

For background on *why* each piece exists, see [`README.md`](./README.md).

---

## 0. Prerequisites (one-time)

Install the two CLIs the script depends on.

```bash
# gcloud CLI - https://cloud.google.com/sdk/docs/install
gcloud version

# Node.js (for datadog-ci) - https://nodejs.org
node --version   # any recent LTS is fine

# Datadog CLI + Cloud Run plugin
npm install -g @datadog/datadog-ci @datadog/datadog-ci-plugin-cloud-run
datadog-ci version
```

If you'd rather not install `datadog-ci` globally, that's fine - the deploy
script will pick it up from `npx` too:

```bash
alias datadog-ci='npx -y -p @datadog/datadog-ci -p @datadog/datadog-ci-plugin-cloud-run datadog-ci'
```

---

## 1. Authenticate `gcloud` (TWO logins, not one)

You need **both** credential stores wired up. They look almost identical and
they both open a browser, but they serve different consumers:

```bash
# (a) Logs you in for the `gcloud` CLI itself - needed by `gcloud run deploy`.
gcloud auth login

# (b) Writes Application Default Credentials (ADC) - needed by `datadog-ci`,
#     Terraform, and anything else that calls Google APIs via a client SDK.
gcloud auth application-default login

gcloud config set project <YOUR_GCP_PROJECT>
```

If you skip (b), the deploy will succeed but the instrumentation step will
fail with:

```
[Error] Unable to authenticate with GCP.
```

Verify both are set:

```bash
gcloud auth list                                        # (a)
gcloud auth application-default print-access-token >/dev/null \
  && echo "ADC OK" || echo "ADC MISSING - run step (b) above"
gcloud config list
```

> If you're in CI / on a server with no browser, swap both `auth login`
> commands for a single service account:
> ```bash
> gcloud auth activate-service-account --key-file=/path/to/sa-key.json
> export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa-key.json
> ```
> The second line is what makes ADC discoverable to client SDKs.

---

## 2. Configure `.env`

```bash
cp .env.example .env
${EDITOR:-vi} .env
```

Fill in at minimum:

```
PROJECT_ID="datadog-sandbox"
GCP_FUNCTION_NAME="code-origin-demo"
DD_SERVICE="code-origin-demo"
```

`DD_API_KEY` and `DD_SITE` are optional. If left unset:

- The script still deploys **and** instruments with the Datadog sidecar.
- A placeholder string (`REPLACE_VIA_CLOUD_RUN_UI`) is baked into the
  sidecar's `DD_API_KEY` env var.
- You replace it via the Cloud Run console after deploy (step 5 below).

---

## 3. Deploy + instrument

```bash
./build_and_deploy.sh
```

What this does, in order:

1. Sources `.env`.
2. `gcloud run deploy` - creates / updates the Cloud Run service from
   `main.py`, and sets all container env vars (`DD_SERVICE`, `DD_ENV`,
   `DD_VERSION`, `DD_CODE_ORIGIN_FOR_SPANS_ENABLED=true`,
   `DD_LOGS_INJECTION=true`, `PYTHONUNBUFFERED=1`,
   `GOOGLE_FUNCTION_TARGET=main`, plus auto-derived `DD_GIT_*`) inline
   via `--set-env-vars`.
3. `datadog-ci cloud-run instrument` - patches the service to add the
   `serverless-init` sidecar, an in-memory shared volume mounted into both
   containers, and the sidecar env vars (`DD_API_KEY`, `DD_SITE`,
   `DD_SERVERLESS_LOG_PATH`, `FUNCTION_TARGET`).

Verify the service is up and reachable:

```bash
URL=$(gcloud run services describe "$GCP_FUNCTION_NAME" \
  --region us-central1 --format='value(status.url)')
curl -s "$URL"
# Expected: Hello World!
```

Verify both containers exist on the service:

```bash
gcloud run services describe "$GCP_FUNCTION_NAME" \
  --region us-central1 \
  --format='value(spec.template.spec.containers[].name)'
# Expected (newline-separated): the function container + a datadog sidecar
```

---

## 4. (If you set `DD_API_KEY` in `.env`) verify telemetry

Hit the service a handful of times so spans are produced:

```bash
for i in {1..10}; do curl -s "$URL" >/dev/null; done
```

In Datadog:

1. **APM > Trace Explorer**.
2. Filter `service:code-origin-demo` and select the **Service Entry Spans**
   preset.
3. Open a span -> **Overview** tab -> look for the **Code Origin** section.
   You should see `main.py`, the line of `def main`, and method `main`.

If the **Code Origin** section is missing, see the troubleshooting section
in [`README.md`](./README.md).

---

## 5. (If you left `DD_API_KEY` unset) replace the placeholder via the UI

The function and sidecar are already deployed - you just need to swap the
placeholder API key for a real one.

1. Open the [Cloud Run console](https://console.cloud.google.com/run) and
   click into `code-origin-demo`.
2. Click **Edit & Deploy New Revision**.
3. In the **Containers** section pick the Datadog sidecar container (its
   image starts with `gcr.io/datadoghq/serverless-init:...`).
4. **Variables & Secrets** tab -> find `DD_API_KEY` -> edit:
   - Plain value: paste the real Datadog API key, **or**
   - Reference a Secret Manager secret (recommended for prod, since the key
     stays out of revision metadata).
5. Click **Deploy** at the bottom. Cloud Run will create a new revision
   and roll traffic to it.

Then run step 4 ("verify telemetry") above.

---

## 6. Re-deploy on code changes

For any change to `main.py`, `requirements.txt`, `Procfile`, or the env vars
in `build_and_deploy.sh`:

```bash
./build_and_deploy.sh
```

The script is idempotent. `datadog-ci instrument` is a no-op (well, a
revision bump) if the sidecar is already wired up correctly.

**Important:** `datadog-ci cloud-run instrument` always rewrites the
sidecar's `DD_API_KEY` to whatever is in your shell when the script runs.
That means if you replaced the placeholder via the UI in step 5, the
**next** run of `build_and_deploy.sh` with `DD_API_KEY` unset in `.env`
will clobber your real key with the placeholder again.

Pick one of these on the second deploy and after:

- **Put the real key in `.env`** (gitignored - safe locally) so the script
  re-applies it every time. Easiest, but the key lives on the deployer's
  laptop.
- **Use a Secret Manager reference** instead of a plain value. Set
  `DD_API_KEY` in `.env` to the secret resource path
  (`projects/PROJECT/secrets/datadog-api-key/versions/latest`), then pass
  `--api-key-secret` to `datadog-ci`. (Requires a small script tweak -
  ping if you want this added.) Production-recommended path.
- **Manually edit the sidecar after each redeploy.** Works but tedious -
  only sane for one-off changes.

---

## Cleanup

```bash
gcloud run services delete "$GCP_FUNCTION_NAME" --region us-central1
```
