"""Built-in document-source connectors.

Each module registers its connector with ``@register_source``.
:func:`scion_sdk.source_connectors.registry.discover` imports every
module here so the decorators run; importing this package alone imports no
submodule, so heavy optional dependencies stay lazy.

* :mod:`web`: same-domain crawler (``web``).
* :mod:`rest`: paginated JSON endpoint (``rest``).
* :mod:`rss`: syndication feeds (``rss``, ``feeds`` extra).
* :mod:`arxiv`: paper metadata (``arxiv``).
* :mod:`database`: rows of one read-only query (``database``, ``db`` extra).
* :mod:`graphql_document`: secret-profiled GraphQL responses
  (``graphql_document``, ``graphql`` extra).
* :mod:`mcp_package`: a connector package's MCP tool (``mcp``, ``mcp`` extra).
* :mod:`package_manifest`: the package preset catalog.

Filesystem and git-markdown corpora are
:mod:`scion_sdk.adapters.document_sources`; declarative MCP-tool
record listing is :mod:`scion_sdk.adapters.mcp_tool`.
"""
