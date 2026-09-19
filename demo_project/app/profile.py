"""User profile handling.

Deliberately independent of the pricing path: a discount change must not make
these tests interesting, which is exactly what the demo measures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")
ALLOWED_AVATAR_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_AVATAR_BYTES = 2 * 1024 * 1024
MAX_DISPLAY_NAME = 32


class ProfileError(Exception):
    """Raised when profile data is rejected."""


@dataclass
class Address:
    line1: str
    city: str
    postal_code: str
    country: str = "US"


@dataclass
class Profile:
    user_id: str
    display_name: str
    email: str
    address: Address | None = None
    avatar: dict[str, object] | None = field(default=None)


def normalize_display_name(raw: str) -> str:
    collapsed = " ".join(raw.split())
    if not collapsed:
        raise ProfileError("display name must not be blank")
    if len(collapsed) > MAX_DISPLAY_NAME:
        raise ProfileError("display name too long")
    return collapsed


def validate_email(email: str) -> str:
    candidate = email.strip().lower()
    if not EMAIL_PATTERN.match(candidate):
        raise ProfileError(f"invalid email: {email}")
    return candidate


def validate_address(address: Address) -> None:
    if not address.line1.strip():
        raise ProfileError("address line1 is required")
    if not address.city.strip():
        raise ProfileError("city is required")
    if address.country == "US" and not re.fullmatch(r"\d{5}(-\d{4})?", address.postal_code):
        raise ProfileError("invalid US postal code")


def set_avatar(profile: Profile, content_type: str, size_bytes: int) -> dict[str, object]:
    if content_type not in ALLOWED_AVATAR_TYPES:
        raise ProfileError(f"unsupported avatar type: {content_type}")
    if size_bytes <= 0:
        raise ProfileError("avatar must not be empty")
    if size_bytes > MAX_AVATAR_BYTES:
        raise ProfileError("avatar exceeds the size limit")
    profile.avatar = {"content_type": content_type, "size_bytes": size_bytes}
    return profile.avatar
