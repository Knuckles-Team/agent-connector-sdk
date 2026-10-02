"""Normalized finance source records shared by every vendor adapter.

Durable graph schemas and finance calculations are owned by the graph
service; this package only normalizes what a source adapter observed before
it reaches the sink boundary. A vendor connector owns its own credentials and
API implementation and maps its provider's shape onto these record types.
"""
