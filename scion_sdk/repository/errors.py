"""Repository transport failures."""

__all__ = ["RepositoryTransportError"]


class RepositoryTransportError(RuntimeError):
    """A provider page or engine result violates the repository contract."""
