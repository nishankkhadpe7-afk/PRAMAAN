"""The security layer's route -> action resolution must hold on every supported FastAPI version."""
import re
import unittest

from starlette.routing import Match

from Pramaan.backend import app as p1
from Pramaan.backend.security import AUDITOR, CLIENT, leaf_routes, resolve_route


def scope_for(path: str, method: str) -> dict:
    return {"type": "http", "path": path, "method": method, "root_path": "", "headers": [], "query_string": b""}


def sample_path(route) -> str:
    return re.sub(r"\{[^}:]+(:path)?\}", "x1", route.path)


class RouteResolutionTests(unittest.TestCase):
    def test_every_endpoint_resolves_to_its_own_name(self):
        routes = [r for r in leaf_routes(p1.app) if getattr(r, "methods", None)]
        self.assertGreater(len(routes), 50)
        for route in routes:
            for method in sorted(route.methods - {"HEAD"}):
                with self.subTest(path=route.path, method=method):
                    found = resolve_route(p1.app, scope_for(sample_path(route), method))
                    self.assertIsNotNone(found)
                    # A more specific route may legitimately shadow a pattern; it must still fully match.
                    self.assertEqual(found.matches(scope_for(sample_path(route), method))[0], Match.FULL)
                    if found is not route:
                        self.assertNotEqual(found.path, route.path)

    def test_permissioned_actions_are_reachable_routes(self):
        names = {r.name for r in leaf_routes(p1.app)}
        missing = sorted((CLIENT | AUDITOR) - names - {"health"})
        self.assertEqual(missing, [], "permission lists name actions that no route serves")

    def test_unknown_paths_and_wrong_methods_do_not_resolve(self):
        self.assertIsNone(resolve_route(p1.app, scope_for("/definitely/not/here", "GET")))
        self.assertIsNone(resolve_route(p1.app, scope_for("/p6/actions/A1/confirm", "GET")))
        self.assertEqual(resolve_route(p1.app, scope_for("/p6/actions/A1/confirm", "POST")).name, "confirm_agent_action")
        self.assertEqual(resolve_route(p1.app, scope_for("/p6/runs/R1/investigations", "POST")).name, "investigate_finding")


if __name__ == "__main__":
    unittest.main()
