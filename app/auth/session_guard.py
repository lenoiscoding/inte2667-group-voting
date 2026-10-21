"""Req 3: one place that decides whether the visitor is still logged in."""
import time

from flask import current_app, session


def active_user_id():
    """The logged-in user's ID, or None if not logged in or idle for too long.

    An expired session is cleared. Each authenticated request counts as
    activity, so the idle timer starts again.
    """
    user_id = session.get("authenticated_user_id")
    idle_seconds = time.time() - session.get("last_activity", 0)
    if not user_id or idle_seconds >= current_app.config["SESSION_TIMEOUT_SECONDS"]:
        session.clear()
        return None
    session["last_activity"] = time.time()
    return user_id
