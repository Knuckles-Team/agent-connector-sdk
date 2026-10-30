"""A connector's typed path to epistemic-graph compute and algorithm selection.

The connector does not hold analytics or choose algorithms. It asks the graph
service which algorithms its ontology binds to an analysis, then asks the
graph service to run them. A method the graph service does not serve yet is
refused with :class:`MethodNotServedError`; there is no local fallback.
"""

from scion_sdk.compute.engine import (
    COMPUTE_SCOPES,
    AlgorithmBinding,
    ComputeUnavailableError,
    EngineCompute,
    MethodNotServedError,
    connect_compute,
)

__all__ = [
    "COMPUTE_SCOPES",
    "AlgorithmBinding",
    "ComputeUnavailableError",
    "EngineCompute",
    "MethodNotServedError",
    "connect_compute",
]
