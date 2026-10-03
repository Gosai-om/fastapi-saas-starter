"""Create the first admin (or promote an existing user).

Usage:
    python -m app.scripts.create_admin --email admin@example.com --name "Admin"
The password is read from the ADMIN_PASSWORD environment variable, or prompted for.
"""

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select

from app.db.session import get_engine, get_sessionmaker
from app.models import Role, User
from app.schemas import UserCreate
from app.services.users import register_user


async def _run(email: str, name: str, password: str) -> str:
    async with get_sessionmaker()() as db:
        existing = await db.scalar(select(User).where(User.email == email.strip().lower()))
        if existing:
            existing.role = Role.ADMIN
            existing.is_active = True
            await db.commit()
            message = "Existing user promoted to admin."
        else:
            data = UserCreate(email=email, full_name=name, password=password)
            await register_user(db, data, role=Role.ADMIN)
            message = "Admin user created."
    await get_engine().dispose()
    return message


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="Administrator")
    args = parser.parse_args()
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Admin password (12+ chars): ")
    if len(password) < 12:
        sys.exit("Password must be at least 12 characters.")
    print(asyncio.run(_run(args.email, args.name, password)))


if __name__ == "__main__":
    main()
