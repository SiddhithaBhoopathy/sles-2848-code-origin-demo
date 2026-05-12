#!/usr/bin/env bash
#
# Deploy a Python Cloud Run Function (Gen 2) and instrument it with Datadog,
# including Code Origin for Spans.
#
# Required env vars:
#   PROJECT_ID         - GCP project ID
#   GCP_FUNCTION_NAME  - Cloud Run service / function name
#   DD_SERVICE         - Datadog service name
# Optional:
#   DD_API_KEY         - if unset, the Cloud Run function is deployed but
#                        the `datadog-ci cloud-run instrument` step is
#                        skipped (datadog-ci validates the key against
#                        Datadog's API and refuses to run with a bad/empty
#                        value). Set the key and re-run to add the sidecar.
#   DD_SITE            - Datadog site. Only needed when DD_API_KEY is set.
#                        Defaults to datadoghq.com.
#   REGION             - GCP region (default: us-central1)
#   DD_GIT_REPOSITORY_URL / DD_GIT_COMMIT_SHA - source-code-integration
#                        values for Code Origin's code preview panel.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Auto-source .env if it exists. Keeps secrets out of your shell history and
# means you don't have to re-export every time you open a new terminal.
if [ -f "$SCRIPT_DIR/.env" ]; then
  echo "Loading config from .env"
  set -a
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/.env"
  set +a
fi

: "${PROJECT_ID:?PROJECT_ID is required}"
: "${GCP_FUNCTION_NAME:?GCP_FUNCTION_NAME is required}"
: "${DD_SERVICE:?DD_SERVICE is required}"
REGION="${REGION:-us-central1}"

# Function entry point in main.py. The Google Cloud Buildpacks detect Python
# from requirements.txt and wrap this with functions-framework so the
# resulting container exposes it as an HTTP service.
ENTRY_POINT="main"

# --- Source Code Integration --------------------------------------------------
# Code Origin's code-preview panel needs DD_GIT_REPOSITORY_URL and
# DD_GIT_COMMIT_SHA to resolve files. Derive them from git if not already set.
if [ -z "${DD_GIT_REPOSITORY_URL:-}" ] && git -C "$SCRIPT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  DD_GIT_REPOSITORY_URL="$(git -C "$SCRIPT_DIR" config --get remote.origin.url || echo "")"
fi
if [ -z "${DD_GIT_COMMIT_SHA:-}" ] && git -C "$SCRIPT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  DD_GIT_COMMIT_SHA="$(git -C "$SCRIPT_DIR" rev-parse HEAD || echo "")"
fi

echo "====== Configuration ======"
echo "PROJECT_ID:            $PROJECT_ID"
echo "REGION:                $REGION"
echo "GCP_FUNCTION_NAME:     $GCP_FUNCTION_NAME"
echo "DD_SERVICE:            $DD_SERVICE"
echo "DD_SITE:               ${DD_SITE:-<unset - only needed if DD_API_KEY is set>}"
echo "DD_GIT_REPOSITORY_URL: ${DD_GIT_REPOSITORY_URL:-<unset - code preview will be empty>}"
echo "DD_GIT_COMMIT_SHA:     ${DD_GIT_COMMIT_SHA:-<unset - code preview will be empty>}"

gcloud config set project "$PROJECT_ID"

echo -e "\n====== Deploying Cloud Run Function (Gen 2) ======"
# All env vars set on the APPLICATION container. The sidecar gets its own
# env vars (DD_API_KEY, DD_SITE, DD_SERVERLESS_LOG_PATH, FUNCTION_TARGET)
# from `datadog-ci cloud-run instrument` below.
#
# Notes:
# - GOOGLE_FUNCTION_TARGET tells the Python buildpack which function in
#   main.py to wrap with functions-framework. Replaces the newer `--function`
#   flag and works on any reasonably recent gcloud version.
# - DD_CODE_ORIGIN_FOR_SPANS_ENABLED is what turns on Code Origin.
# - DD_LOGS_INJECTION enriches logs with trace IDs.
# - PYTHONUNBUFFERED keeps stdout in real-time so the sidecar can tail logs.
# - DD_ENV / DD_VERSION feed Unified Service Tagging.
SET_ENV_VARS="DD_SERVICE=$DD_SERVICE"
SET_ENV_VARS="$SET_ENV_VARS,DD_ENV=${DD_ENV:-dev}"
SET_ENV_VARS="$SET_ENV_VARS,DD_VERSION=${DD_VERSION:-0.1.0}"
SET_ENV_VARS="$SET_ENV_VARS,DD_CODE_ORIGIN_FOR_SPANS_ENABLED=true"
SET_ENV_VARS="$SET_ENV_VARS,DD_LOGS_INJECTION=true"
SET_ENV_VARS="$SET_ENV_VARS,PYTHONUNBUFFERED=1"
SET_ENV_VARS="$SET_ENV_VARS,GOOGLE_FUNCTION_TARGET=$ENTRY_POINT"
[ -n "${DD_GIT_REPOSITORY_URL:-}" ] && SET_ENV_VARS="$SET_ENV_VARS,DD_GIT_REPOSITORY_URL=$DD_GIT_REPOSITORY_URL"
[ -n "${DD_GIT_COMMIT_SHA:-}"     ] && SET_ENV_VARS="$SET_ENV_VARS,DD_GIT_COMMIT_SHA=$DD_GIT_COMMIT_SHA"

gcloud run deploy "$GCP_FUNCTION_NAME" \
  --region="$REGION" \
  --source="$SCRIPT_DIR" \
  --allow-unauthenticated \
  --memory=512Mi \
  --timeout=60s \
  --set-env-vars="$SET_ENV_VARS" \
  --project="$PROJECT_ID"

if [ -z "${DD_API_KEY:-}" ]; then
  cat <<EOF

====== Skipping Datadog instrumentation (DD_API_KEY not set) ======
The Cloud Run function was deployed, but the Datadog sidecar has NOT been
added. \`datadog-ci cloud-run instrument\` validates DD_API_KEY against the
Datadog API and refuses to run with an empty or invalid value, so we skip
that step rather than fail the deploy.

Next steps:
  1. Add the real key to .env:
        DD_API_KEY="<your key>"
        # DD_SITE="datadoghq.com"   # uncomment & change if you're not on US1
  2. Re-run this script:
        ./build_and_deploy.sh

That second run will run \`datadog-ci cloud-run instrument\`, which injects
the serverless-init sidecar + shared volume + sidecar env vars onto the
deployed service as a new revision. No code changes needed in between.
EOF
  exit 0
fi

DD_SITE="${DD_SITE:-datadoghq.com}"

echo -e "\n====== Instrumenting with datadog-ci (sidecar + shared volume) ======"
echo "Using DD_SITE=$DD_SITE"
# datadog-ci handles:
#   - injecting the serverless-init sidecar
#   - mounting the shared in-memory volume
#   - setting DD_API_KEY, DD_SITE, DD_SERVERLESS_LOG_PATH, FUNCTION_TARGET on the sidecar
#   - adding the `service` label on the Cloud Run service
DD_API_KEY="$DD_API_KEY" \
DD_SITE="$DD_SITE" \
DD_SERVICE="$DD_SERVICE" \
datadog-ci cloud-run instrument \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --service "$GCP_FUNCTION_NAME"

echo -e "\n====== Done ======"
echo "Hit the service a few times, then open APM > Trace Explorer in Datadog,"
echo "filter to: service:$DD_SERVICE @_dd.span_kind:server"
echo "and confirm the 'Code Origin' panel appears on the span Overview tab."
