"""Built-in document-source connectors (CONCEPT:AU-ECO.connector.document-source-framework).

Each module in this package registers its connector via the ``@register_source``
decorator (CONCEPT:AU-ECO.connector.factory-ingestion-adaptor). They are imported by
:func:`agent_connector_sdk.source_connectors.registry.discover`, which walks
this package so the decorators run on the live ingestion path. Importing this
package directly does **not** import the submodules (discovery is explicit) — this
keeps connector heavy-deps lazy.

Reference connectors:
  * :mod:`web` — recursive same-domain crawler (``web``).
  * :mod:`rest` — paginated JSON endpoint (``rest``).
  * :mod:`rss` — RSS and Atom feeds (``rss``).
  * :mod:`arxiv` — arXiv category feeds (``arxiv``).
  * :mod:`package_manifest` — package presets for the connector fleet.
"""
