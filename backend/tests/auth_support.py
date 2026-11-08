"""Provision real credentials for the pre-P4 regression fixtures."""
from fastapi import HTTPException
from Pramaan.backend import app as p1, p3
from Pramaan.backend.security import CLIENT, issue, resolve_route


def headers(scope):
    route = resolve_route(p1.app, scope)
    role = "client_employee" if route.name in CLIENT else "auditor"
    return [(b"authorization", ("Bearer " + issue("regression-" + role, role)).encode())]


def offline_fixture_import():
    # Synthetic fixture loading is an administrator operation, not a judge tool.
    try:
        return 200, p3.import_fixture_dataset()
    except HTTPException as exc:
        return exc.status_code, {"detail": exc.detail}
