"""Normalized taxonomy records shared by the NCBI and GBIF connectors.

Durable `:Taxon` individuals, `TaxonShape` validation and reasoning are owned
by epistemic-graph; this package only normalizes what a source adapter
observed before it reaches the sink boundary. A vendor connector (NCBI
Taxonomy, GBIF backbone) owns its own credentials and API implementation and
maps its provider's shape onto ``TaxonRecord``.
"""
