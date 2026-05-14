# Deployment Instructions

Step-by-step checklist to deploy this Python Cloud Run service with Datadog
APM + Code Origin enabled. Run each block in order; verification command at
the end of each step.

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
PROJECT_ID="datadog-serverless-gcp-demo"
GCP_FUNCTION_NAME="code-origin-demo"
DD_SERVICE="code-origin-demo"
```

`DD_API_KEY` and `DD_SITE` are optional:

- **Set** — full deploy + instrument flow runs end to end.
- **Unset** — only `gcloud run deploy` runs; the script prints a "skipping
  instrumentation" message and exits 0. Add the key to `.env` later and
  re-run to attach the sidecar.

---

## 3. Deploy + instrument

```bash
./build_and_deploy.sh
```

What this does, in order:

1. Sources `.env`.
2. `gcloud run deploy --source=.` — Google Cloud Buildpacks detect Python
   from `requirements.txt`, install dependencies, and produce a container
   whose start command comes from `Procfile`:
   `ddtrace-run gunicorn -w 4 -b :$PORT main:app`. The script sets all
   application-container env vars inline via `--set-env-vars`
   (`DD_SERVICE`, `DD_ENV`, `DD_VERSION`, `DD_TRACE_ENABLED=true`,
   `DD_REMOTE_CONFIGURATION_ENABLED=false`,
   `DD_CODE_ORIGIN_FOR_SPANS_ENABLED=true`, `DD_LOGS_INJECTION=true`,
   `PYTHONUNBUFFERED=1`, plus auto-derived `DD_GIT_*`).
3. `datadog-ci cloud-run instrument` — patches the service to add the
   `serverless-init` sidecar, an in-memory shared volume mounted into both
   containers, and the sidecar env vars (`DD_API_KEY`, `DD_SITE`,
   `DD_SERVERLESS_LOG_PATH`).

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
# Expected (newline-separated): the application container + a datadog sidecar
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
   You should see `main.py`, the line of the route handler, and the method
   name.

If the **Code Origin** section is missing, see the troubleshooting section
in [`README.md`](./README.md).

---

## 5. Re-deploy on code changes

For any change to `main.py`, `requirements.txt`, `Procfile`, or the env vars
in `build_and_deploy.sh`:

```bash
./build_and_deploy.sh
```

The script is idempotent. `datadog-ci instrument` is a no-op (well, a
revision bump) if the sidecar is already wired up correctly.

---

## Cleanup

```bash
gcloud run services delete "$GCP_FUNCTION_NAME" --region us-central1
```
