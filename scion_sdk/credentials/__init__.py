"""Credentials by reference (RF-ADR-009 2.2.1): parse, validate and resolve.

Connector configuration, manifests, content packs and records only carry secret
*references*; values are resolved in memory at the composition root.

* :mod:`~scion_sdk.credentials.references`: the reference grammar.
* :mod:`~scion_sdk.credentials.resolver`: the resolver port and the
  environment and per-scheme resolvers.
* :mod:`~scion_sdk.credentials.openbao`: the OpenBao KV v2 resolver.
* :mod:`~scion_sdk.credentials.resolution`: bounded resolution and
  the argparse action.
* :mod:`~scion_sdk.credentials.provider_profile`: the reference-only
  provider profile a launcher selects with ``AGENT_PROVIDER_PROFILE``.

Replaces the connector-facing half of ``agent_utilities.security.cli_secrets``
and ``agent_utilities.security.secrets_client``.
"""
