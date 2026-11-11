"""Create or promote a platform admin.

    python -m app.scripts.create_admin you@example.com [password]
"""
from __future__ import annotations

import secrets
import sys

from sqlalchemy import select

from app.core.db import SessionLocal, init_db
from app.core.security import hash_password
from app.models import Membership, Organization, User
from app.services.auth import initials


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    email = sys.argv[1].strip().lower()
    password = sys.argv[2] if len(sys.argv) > 2 else "Adm" + secrets.token_urlsafe(9) + "7"

    init_db()
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            org = Organization(name="BrandSetGo Ops", slug=f"ops-{secrets.token_hex(3)}",
                               account_type="business", plan="enterprise", seats=5, billing_email=email)
            db.add(org)
            db.flush()
            user = User(email=email, name="Platform Admin", avatar_initials=initials("Platform Admin"),
                        password_hash=hash_password(password), account_type="business", platform_role="admin")
            db.add(user)
            db.flush()
            org.created_by = user.id
            db.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
            print(f"Created admin {email} with password: {password}")
        else:
            user.platform_role = "admin"
            print(f"Promoted {email} to platform admin.")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
