"""Outbound TLS profiles: trust anchors, client certificates and proxies.

Certificate and hostname verification are invariants. A profile chooses what is
trusted (the platform store, a CA bundle or directory), an optional client
certificate, a minimum protocol version and an optional proxy; it can never turn
verification off. Certificate material held in secrets is resolved through
:mod:`scion_sdk.credentials` references and written only to private
runtime files that are removed on cleanup and at process exit.

* :mod:`~scion_sdk.tls.resolve`: :func:`resolve_tls_profile`.
* :mod:`~scion_sdk.tls.profile`: :class:`ResolvedTLSProfile` and its
  client adapters.
* :mod:`~scion_sdk.tls.errors`: :class:`TransportSecurityError`.

Replaces ``agent_utilities.core.transport_security``.
"""
