# IMPORTANT: ddtrace.auto MUST be the very first import.
# Cloud Run Functions don't run via ddtrace-run, so auto-instrumentation
# of the underlying Flask framework only happens if ddtrace.auto is
# imported before functions_framework / Flask. Without this, no service
# entry span is created and Code Origin will NOT appear in the UI.
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

    The Flask request that wraps this function is what Code Origin attaches
    its span to (the service entry span). You should see this file and the
    line number of `def main` in the Code Origin panel in Datadog APM.
    """
    logger.info("Hello world! method=%s path=%s", request.method, request.path)
    datadog.statsd.distribution("our-sample-app.sample-metric", 1)
    return "Hello World!", 200
