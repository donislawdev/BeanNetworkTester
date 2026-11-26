# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The pytest fixture ``bad_network``.

    def test_the_page_survives_a_slow_api(bad_network, page):
        bad_network(server="http://localhost:8000", latency=300, loss=2)
        page.goto("http://localhost:3000")
        ...

Calling it starts a session at once and returns it, exactly as
``beannetworktester.bad_network`` does. Every session it started is stopped when the
test ends, and its summary goes into the test's ``user_properties`` (and so into a
JUnit XML report), under ``bad_network``.
"""

from __future__ import annotations

import json

import pytest

from ._session import BadNetwork


def _brief(summary: dict | None) -> str:
    if not summary:
        return ""
    counters = summary.get("counters") or {}
    return json.dumps({key: summary.get(key) for key in ("stop_reason", "seed", "elapsed_s",
                                                         "repro_command")}
                      | {"packets": counters.get("seen"), "in_scope": counters.get("scoped_seen")})


@pytest.fixture
def bad_network(request):
    sessions: list[BadNetwork] = []

    def start(**options) -> BadNetwork:
        # Kept once it started: a session that failed to start has cleaned up after
        # itself, and has no summary to report.
        session = BadNetwork(**options).start()
        sessions.append(session)
        return session

    yield start
    errors = []
    for session in sessions:
        try:
            summary = session.stop()
        except Exception as exc:  # noqa: BLE001 - every session is stopped, then it is raised
            errors.append(exc)
            continue
        request.node.user_properties.append(("bad_network", _brief(summary)))
    if errors:
        raise errors[0]
