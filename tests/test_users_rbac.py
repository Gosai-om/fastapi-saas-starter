from app.models import Role

USERS = "/api/v1/users"


async def test_regular_user_cannot_list_users(client, make_user, login):
    user = await make_user(Role.USER)
    resp = await client.get(USERS, headers=await login(user.email))
    assert resp.status_code == 403


async def test_manager_can_list_users_with_pagination_and_filter(client, make_user, login):
    manager = await make_user(Role.MANAGER)
    for _ in range(3):
        await make_user(Role.USER)
    headers = await login(manager.email)

    page = (await client.get(USERS, params={"limit": 2}, headers=headers)).json()
    assert page["total"] == 4 and len(page["items"]) == 2

    only_users = (await client.get(USERS, params={"role": "user"}, headers=headers)).json()
    assert only_users["total"] == 3


async def test_pagination_limit_is_bounded(client, make_user, login):
    manager = await make_user(Role.MANAGER)
    resp = await client.get(USERS, params={"limit": 1000}, headers=await login(manager.email))
    assert resp.status_code == 422


async def test_manager_cannot_change_roles(client, make_user, login):
    manager = await make_user(Role.MANAGER)
    target = await make_user(Role.USER)
    resp = await client.patch(
        f"{USERS}/{target.id}/role", json={"role": "admin"}, headers=await login(manager.email)
    )
    assert resp.status_code == 403


async def test_admin_can_change_role_and_it_applies_immediately(client, make_user, login):
    admin = await make_user(Role.ADMIN)
    target = await make_user(Role.USER)
    target_headers = await login(target.email)
    assert (await client.get(USERS, headers=target_headers)).status_code == 403

    resp = await client.patch(
        f"{USERS}/{target.id}/role", json={"role": "manager"}, headers=await login(admin.email)
    )
    assert resp.status_code == 200 and resp.json()["role"] == "manager"
    # Same token, new permissions: roles are read from the database, not the token.
    assert (await client.get(USERS, headers=target_headers)).status_code == 200


async def test_admin_cannot_change_own_role(client, make_user, login):
    admin = await make_user(Role.ADMIN)
    resp = await client.patch(
        f"{USERS}/{admin.id}/role", json={"role": "user"}, headers=await login(admin.email)
    )
    assert resp.status_code == 400


async def test_deactivated_user_loses_access_immediately(client, make_user, login):
    admin = await make_user(Role.ADMIN)
    target = await make_user(Role.USER)
    target_headers = await login(target.email)

    resp = await client.patch(
        f"{USERS}/{target.id}/status", json={"is_active": False}, headers=await login(admin.email)
    )
    assert resp.status_code == 200 and resp.json()["is_active"] is False
    assert (await client.get("/api/v1/auth/me", headers=target_headers)).status_code == 401

    relogin = await client.post(
        "/api/v1/auth/login", data={"username": target.email, "password": "correct-horse-battery"}
    )
    assert relogin.status_code == 403


async def test_unknown_user_returns_404(client, make_user, login):
    admin = await make_user(Role.ADMIN)
    resp = await client.patch(
        f"{USERS}/00000000-0000-0000-0000-000000000000/role",
        json={"role": "user"},
        headers=await login(admin.email),
    )
    assert resp.status_code == 404
