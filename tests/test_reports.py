import uuid

from app.models import Report, ReportStatus, Role
from app.services.reports import process_report

REPORTS = "/api/v1/reports"


async def test_user_requests_report_and_worker_completes_it(client, make_user, login, queue, db):
    user = await make_user(Role.USER)
    headers = await login(user.email)

    resp = await client.post(REPORTS, json={"kind": "my_activity"}, headers=headers)
    assert resp.status_code == 202
    report_id = uuid.UUID(resp.json()["id"])
    assert resp.json()["status"] == "pending"
    assert queue.reports == [report_id]

    # Simulate the Celery worker picking up the job.
    await process_report(db, report_id)

    done = (await client.get(f"{REPORTS}/{report_id}", headers=headers)).json()
    assert done["status"] == "completed"
    assert done["result"]["role"] == "user"
    assert done["result"]["reports_requested"] == 1
    assert done["completed_at"] is not None


async def test_processing_twice_is_safe(client, make_user, login, db):
    user = await make_user()
    headers = await login(user.email)
    report_id = uuid.UUID(
        (await client.post(REPORTS, json={"kind": "my_activity"}, headers=headers)).json()["id"]
    )
    await process_report(db, report_id)
    await process_report(db, report_id)  # duplicate delivery from the broker
    report = await db.get(Report, report_id)
    assert report.status is ReportStatus.COMPLETED


async def test_regular_user_cannot_request_team_overview(client, make_user, login):
    user = await make_user(Role.USER)
    resp = await client.post(
        REPORTS, json={"kind": "team_overview"}, headers=await login(user.email)
    )
    assert resp.status_code == 403


async def test_manager_team_overview_counts_users(client, make_user, login, db):
    manager = await make_user(Role.MANAGER)
    await make_user(Role.USER)
    await make_user(Role.ADMIN)
    headers = await login(manager.email)
    report_id = uuid.UUID(
        (await client.post(REPORTS, json={"kind": "team_overview"}, headers=headers)).json()["id"]
    )
    await process_report(db, report_id)
    result = (await client.get(f"{REPORTS}/{report_id}", headers=headers)).json()["result"]
    assert result["total_users"] == 3
    assert result["users_by_role"] == {"admin": 1, "manager": 1, "user": 1}


async def test_users_cannot_see_each_others_reports_but_admin_can(client, make_user, login):
    owner, other, admin = await make_user(), await make_user(), await make_user(Role.ADMIN)
    owner_headers = await login(owner.email)
    report_id = (
        await client.post(REPORTS, json={"kind": "my_activity"}, headers=owner_headers)
    ).json()["id"]

    other_view = await client.get(f"{REPORTS}/{report_id}", headers=await login(other.email))
    assert other_view.status_code == 404  # not 403: existence is not revealed

    admin_headers = await login(admin.email)
    assert (await client.get(f"{REPORTS}/{report_id}", headers=admin_headers)).status_code == 200
    assert (await client.get(REPORTS, headers=await login(other.email))).json()["total"] == 0
    assert (await client.get(REPORTS, headers=admin_headers)).json()["total"] == 1


async def test_report_is_marked_failed_when_queue_is_down(client, make_user, login, queue):
    user = await make_user()
    headers = await login(user.email)
    queue.fail = True
    resp = await client.post(REPORTS, json={"kind": "my_activity"}, headers=headers)
    assert resp.status_code == 503
    listed = (await client.get(REPORTS, headers=headers)).json()["items"]
    assert listed[0]["status"] == "failed"


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}
    assert "X-Request-ID" in resp.headers
