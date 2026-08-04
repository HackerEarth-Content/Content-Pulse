"""The two gates that decide who gets in and who can write. Both are pure
logic — no Google round-trip needed."""

import pytest
from fastapi import HTTPException

from core import users
from core.deps import require_member
from core.orm import Member


@pytest.mark.parametrize(
    "allowlist,email,expected",
    [
        ("", "anyone@example.com", True),  # empty allowlist = open
        ("a@x.com,b@x.com", "b@x.com", True),
        ("a@x.com,b@x.com", "c@x.com", False),
        (" A@X.com , b@x.com ", "a@x.com", True),  # case + whitespace tolerant
        ("a@x.com", "  A@X.COM  ", True),
    ],
)
def test_allowlist(monkeypatch, allowlist, email, expected):
    monkeypatch.setattr(users.settings, "ALLOWED_EMAILS", allowlist)
    assert users._is_allowed(email) is expected


async def test_require_member_rejects_unlinked_account():
    with pytest.raises(HTTPException) as e:
        await require_member()(member=None)
    assert e.value.status_code == 403
    assert e.value.detail["code"] == "no_member"


async def test_require_member_rejects_wrong_role():
    member = Member(display_name="Someone", role="content")
    with pytest.raises(HTTPException) as e:
        await require_member("admin")(member=member)
    assert e.value.detail["code"] == "wrong_role"


@pytest.mark.parametrize("role", ["content", "ae", "manager", "admin"])
async def test_require_member_default_allows_every_role(role):
    member = Member(display_name="Someone", role=role)
    assert await require_member()(member=member) is member
