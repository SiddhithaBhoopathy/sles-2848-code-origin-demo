# ddtrace bootstrapping happens in the Procfile via `ddtrace-run`, NOT here.
#
# Why not `import ddtrace.auto` at the top of this file (as the Datadog
# Code Origin docs suggest)?
#
#   With Cloud Run Functions, the Python buildpack launches
#   `functions-framework --target=main`. functions-framework creates its
#   Flask app *before* it imports this file to look up `main`, so by the
#   time `import ddtrace.auto` would run here, Flask has already been
#   instantiated without ddtrace's WSGI middleware. The `flask.request`
#   service-entry span never gets created, and Code Origin has nothing to
#   attach to. Symptom in Cloud Run logs:
#     WARNING [ddtrace.internal.core] No span found in ExecutionContext
#     flask._patched_request
#
# Using `ddtrace-run` as the process launcher (see Procfile) guarantees
# ddtrace patches Flask BEFORE functions-framework constructs its app.

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

    The Flask request that wraps this function is what Code Origin attaches
    its span to (the service entry span). You should see this file and the
    line number of `def main` in the Code Origin panel in Datadog APM.
    """
    logger.info("Hello world! method=%s path=%s", request.method, request.path)
    datadog.statsd.distribution("our-sample-app.sample-metric", 1)
    return "Hello World!", 200
