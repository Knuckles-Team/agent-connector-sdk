"""Normalized occurrence and weather source records shared by every adapter.

Durable graph schemas live in epistemic-graph; this package only normalizes
what a source adapter observed before it reaches the sink boundary. A vendor
connector (GBIF, iNaturalist, NOAA GHCN/ISD, Open-Meteo, NOAA storm events)
owns its own credentials and API implementation and maps its provider's
shape onto these record types.
"""
