"""The governed HTTP client connectors use to reach their vendor APIs.

* :mod:`~agent_connector_sdk.http.client`: :class:`HttpClientOptions`,
  :func:`create_http_client` and :func:`create_async_http_client` (finite
  timeouts, mandatory verification, bounded retries, request logging).
* :mod:`~agent_connector_sdk.http.retry`: :class:`RetryPolicy` and
  ``Retry-After`` parsing.
* :mod:`~agent_connector_sdk.http.transport`: the retrying, logging transports.
* :mod:`~agent_connector_sdk.http.problems` and
  :mod:`~agent_connector_sdk.http.errors`: RFC 9457 problem details and the
  exceptions they travel in.
* :mod:`~agent_connector_sdk.http.bodies` and
  :mod:`~agent_connector_sdk.http.responses`: size-bounded bodies, success
  checks and JSON requests.
* :mod:`~agent_connector_sdk.http.pagination`: tool result pages that feed the
  ``mcp_tool`` pagination modes.
* :mod:`~agent_connector_sdk.http.redaction`: secret redaction for logs.

Replaces ``agent_utilities.core.http_client``.
"""
