# =============================================================================
# Datadog Code Origin demo for Google Cloud Run Functions Gen 2 (Python).
#
# This file implements the workaround documented in the Datadog Code Origin
# setup docs and recommended by Datadog engineering for unsupported runtimes:
#
#     "import ddtrace.auto themselves as part of the bootstrap, or as
#      early as possible in their code"
#
# It is the FIRST executable statement of this module, before any framework
# or logging imports, exactly as the docs prescribe.
#
# -----------------------------------------------------------------------------
# EXPECTED LIMITATIONS (do not assume Code Origin works as-is)
# -----------------------------------------------------------------------------
#
# Cloud Run Functions Python is not in the officially supported list for
# Code Origin (Django / Flask / Starlette and derivatives). The runtime
# uses `functions-framework`, which constructs its own Flask app BEFORE
# importing this file to resolve the `main` target. By the time
# `import ddtrace.auto` runs here, Flask has already been instantiated
# without ddtrace's WSGI middleware. Observed consequences:
#
#   - Flask child spans appear (flask.dispatch_request, flask.process_response,
#     etc.) because ddtrace can still monkey-patch Flask class methods at
#     runtime,
#   - but the parent `flask.request` service-entry span is NOT created, so
#     every request logs `WARNING [ddtrace.internal.core] No span found in
#     ExecutionContext flask._patched_request`,
#   - and Code Origin has nothing to attach to, so the Code Origin panel in
#     Datadog APM remains empty.
#
# A workaround that produces a proper `flask.request` root span is to
# launch via `ddtrace-run` in the Procfile (`web: ddtrace-run
# functions-framework --target=main --port=$PORT`). That fixes the orphan
# spans but, as of ddtrace 4.5.0 + Python 3.14 in the GCP buildpack, still
# does NOT activate Code Origin on the root span. Tracked as an FR with
# the Live Debugger team.
#
# Cold-start cost: `import ddtrace.auto` adds ~100 ms to container cold
# starts. Same order of magnitude as `ddtrace-run`.
#
# References:
#   https://docs.datadoghq.com/tracing/code_origin/
#   https://docs.datadoghq.com/serverless/google_cloud_run/functions/python/
# =============================================================================

import ddtrace.auto  # noqa: F401,E402  isort:skip

import logging
import os
import sys
from typing import Any

import datadog
from flask import Request

datadog.initialize(
    statsd_host="127.0.0.1",
    statsd_port=8125,
)

handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
if "DD_SERVERLESS_LOG_PATH" in os.environ:
    LOG_FILE = os.environ["DD_SERVERLESS_LOG_PATH"].replace("*.log", "app.log")
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    handlers.append(logging.FileHandler(LOG_FILE))

FORMAT = (
    "%(asctime)s %(levelname)s [%(name)s] [%(filename)s:%(lineno)d] "
    "[dd.service=%(dd.service)s dd.env=%(dd.env)s dd.version=%(dd.version)s "
    "dd.trace_id=%(dd.trace_id)s dd.span_id=%(dd.span_id)s] - %(message)s"
)

logging.basicConfig(level=logging.INFO, format=FORMAT, handlers=handlers, force=True)
logger = logging.getLogger(__name__)


def main(request: Request) -> Any:
    """Cloud Run Function entry point.

    Per the Code Origin docs, the Flask service-entry span that wraps this
    function is where Code Origin metadata (file/line/method + code preview)
    would attach. See the EXPECTED LIMITATIONS section at the top of this
    file for why that isn't happening in this runtime today.
    """
    logger.info("Hello world! method=%s path=%s", request.method, request.path)
    datadog.statsd.distribution("our-sample-app.sample-metric", 1)
    return "Hello World!", 200
