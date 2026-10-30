"""Native authority seam for profile-as-evidence references."""

from __future__ import annotations

from typing import Protocol

from .models import ProfileEvidenceReference, ProfileTarget


class ProfileEvidenceAuthority(Protocol):
    """Separate native authority for profile-as-evidence references."""

    def authorize_profile_evidence(
        self,
        *,
        profile_digest: str,
        target: ProfileTarget,
    ) -> ProfileEvidenceReference:
        """Create a ChangeEnvelope-backed reference after policy admission."""
