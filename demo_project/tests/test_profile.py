import pytest

from app.profile import Address, Profile, ProfileError, normalize_display_name, set_avatar, validate_address, validate_email
from support import simulate_io


@pytest.fixture
def profile():
    return Profile(user_id="u-1", display_name="Ada", email="ada@example.com")


def test_display_name_whitespace_is_collapsed():
    """Inner runs of whitespace collapse to single spaces."""
    simulate_io(1.5)
    assert normalize_display_name("  Ada   Lovelace ") == "Ada Lovelace"


def test_blank_display_name_is_rejected():
    """Whitespace only is treated as empty."""
    simulate_io(1.5)
    with pytest.raises(ProfileError):
        normalize_display_name("   ")


def test_email_is_normalized_and_validated():
    """Emails are lowercased and trimmed before the pattern check."""
    simulate_io(2.5)
    assert validate_email("  Ada@Example.COM ") == "ada@example.com"
    with pytest.raises(ProfileError):
        validate_email("ada@example")


def test_us_address_requires_postal_code():
    """US addresses need a five or nine digit ZIP."""
    simulate_io(4.0)
    validate_address(Address(line1="1 Main St", city="Pittsburgh", postal_code="15213"))
    with pytest.raises(ProfileError):
        validate_address(Address(line1="1 Main St", city="Pittsburgh", postal_code="ABC"))


@pytest.mark.slow
def test_avatar_upload_accepts_png(profile):
    """Avatar upload round trip, standing in for object storage latency."""
    simulate_io(25.0)
    stored = set_avatar(profile, "image/png", 120_000)
    assert stored["content_type"] == "image/png"
    assert profile.avatar is stored
    with pytest.raises(ProfileError):
        set_avatar(profile, "image/png", 5 * 1024 * 1024)
    with pytest.raises(ProfileError):
        set_avatar(profile, "image/gif", 1000)
