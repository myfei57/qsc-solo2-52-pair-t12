"""Routes for health, state, the record stream and the plant manifest."""

from __future__ import annotations

from typing import Any

from ..errors import ValidationError
from .response import inject_snapshot
from .router import Request, Response, Router


def register(router: Router, runtime: Any, pages: Any) -> None:
    """Register the plant wide routes."""

    router.add(
        "GET",
        "/",
        lambda _: Response.html(inject_snapshot(pages.load("recipe"), runtime.controller.recipe_view())),
    )
    router.add("GET", "/api/health", lambda _: Response.json(runtime.health()))
    router.add("GET", "/api/state", lambda _: Response.json(runtime.state()))
    router.add("GET", "/api/plant", lambda _: Response.json(runtime.controller.manifest()))
    router.add("GET", "/api/diagnostics", lambda _: Response.json(runtime.controller.diagnostics()))
    router.add("GET", "/api/records", lambda request: Response.json(runtime.records(dict(request.query))))
    router.add("GET", "/api/history", _history(runtime))
    router.add("GET", "/api/limits", _limits(runtime))
    router.add("POST", "/api/limits/explain", _explain(runtime))


def _limits(runtime: Any):
    def handler(request: Request) -> Response:
        category = request.query.get("category")
        if category:
            return Response.json(runtime.limit_history(str(category)))
        return Response.json(runtime.limit_book.describe(now=runtime.clock.now()))

    return handler


def _explain(runtime: Any):
    def route(request: Request) -> Response:
        body = request.body if isinstance(request.body, dict) else {}
        verdict = body.get("verdict", body)
        return Response.json(runtime.explain_verdict(verdict))

    return route


def _history(runtime: Any):
    def handler(request: Request) -> Response:
        raw = request.require_field("tick")
        try:
            tick = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValidationError("tick must be an integer", tick=str(raw)) from exc
        return Response.json(runtime.history(tick))

    return handler
