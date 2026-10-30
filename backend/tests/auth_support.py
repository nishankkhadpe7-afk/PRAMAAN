"""Provision real credentials for the pre-P4 regression fixtures."""
from starlette.routing import Match
from fastapi import HTTPException
from Pramaan.backend import app as p1, p3
from Pramaan.backend.security import CLIENT, issue


def headers(scope):
    route = next(r for r in p1.app.routes if r.matches(scope)[0] == Match.FULL)
    role = "client_employee" if route.name in CLIENT else "auditor"
    return [(b"authorization", ("Bearer " + issue("regression-" + role, role)).encode())]


def offline_fixture_import():
    # Synthetic fixture loading is an administrator operation, not a judge tool.
    try:
        return 200, p3.import_fixture_dataset()
    except HTTPException as exc:
        return exc.status_code, {"detail": exc.detail}
