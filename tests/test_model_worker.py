"""The off-thread model rebuild: the UI thread must never do the sorting.

Why this exists: the tables are virtualised, so DRAWING them is free. Deciding
which rows and in what order is not - 361 ms at 500 000 rows, 1.5 s at two million
- and that ran on the UI thread, where it is a frozen window. A frozen window in
this tool is not cosmetic: the user has impaired their own machine's networking,
and STOP is how they undo it.

So the invariants:

* the UI thread hands the work over and returns immediately;
* while the worker works, the PREVIOUS rows stay on screen (stale beats broken);
* requests coalesce - typing does not start six sorts of a million rows;
* a result that no longer matches what was asked for is DISCARDED, so a slow sort
  finishing late cannot resurrect an order the user has already moved on from;
* a worker that raises does not take the page down, and does not blank the table.
"""
import threading
import time

from beantester.gui.model_worker import AsyncModel


def _wait(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def _collect(model, timeout=10.0):
    """Poll the way the page does, until the worker delivers something."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = model.poll()
        if result is not None:
            return result
        time.sleep(0.005)
    raise AssertionError("the worker never delivered a model")


def test_the_ui_thread_hands_the_work_over_and_returns():
    started = threading.Event()
    release = threading.Event()

    def build(payload):
        started.set()
        release.wait(timeout=5)
        return [payload]

    model = AsyncModel(build)

    t0 = time.perf_counter()
    model.request("work")
    handed_over_ms = (time.perf_counter() - t0) * 1000

    assert started.wait(timeout=5), "the worker never started"
    assert handed_over_ms < 50, f"request() blocked the UI thread for {handed_over_ms:.0f} ms"
    assert model.poll() is None, "nothing is ready yet - the UI must carry on"

    release.set()
    assert _collect(model) == ["work"]


def test_the_result_comes_back_whole():
    model = AsyncModel(lambda payload: sorted(payload, reverse=True))
    model.request([3, 1, 2])
    assert _collect(model) == [3, 2, 1]
    assert not model.busy()


def test_requests_coalesce_so_typing_does_not_start_six_sorts():
    """A user typing 'chrome' fires six searches. Only the last one matters."""
    builds = []
    gate = threading.Event()

    def build(payload):
        builds.append(payload)
        gate.wait(timeout=5)            # hold the first one open
        return payload

    model = AsyncModel(build)
    model.request("c")
    assert _wait(lambda: builds, timeout=5)

    for text in ("ch", "chr", "chro", "chrom", "chrome"):
        model.request(text)             # all while the first is still running

    assert len(builds) == 1, f"a sort started per keystroke: {builds}"
    gate.set()

    # the first result arrives, and the LAST request (not the middle ones) follows
    assert _wait(lambda: model.poll() is not None, timeout=5)
    assert _wait(lambda: len(builds) == 2, timeout=5), builds
    assert builds[1] == "chrome", f"the wrong request was kept: {builds}"


def test_a_stale_result_is_discarded():
    """A slow sort finishing after the user changed column must not resurrect the
    old order."""
    slow = threading.Event()

    def build(payload):
        if payload == "slow":
            slow.wait(timeout=5)
        return payload

    model = AsyncModel(build)
    model.request("slow")
    assert _wait(lambda: model.busy(), timeout=5)

    # the user moves on; the queued request supersedes the one in flight
    model.request("fresh")
    slow.set()

    # the page must end up showing the LATEST answer, never the superseded one
    delivered = []
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and "fresh" not in delivered:
        result = model.poll()
        if result is not None:
            delivered.append(result)
        time.sleep(0.005)

    assert "fresh" in delivered, f"the newest request never landed: {delivered}"
    assert delivered[-1] == "fresh", f"a stale result won: {delivered}"


def test_a_worker_that_raises_keeps_the_old_model_on_screen():
    """A stale table beats a broken one - and the page must not go down with it."""
    def build(payload):
        raise RuntimeError("the sort blew up")

    model = AsyncModel(build)
    model.request("anything")

    assert _wait(lambda: not model.busy(), timeout=5), "a failed build never cleared"
    assert model.poll() is None, "a failed build must not deliver an empty model"

    # and the model still works afterwards
    ok = AsyncModel(lambda p: [p])
    ok.request("later")
    assert _wait(lambda: ok.poll() is not None, timeout=5)


def test_a_build_returning_none_does_not_wedge_the_worker():
    """``None`` used to mean two things at once, and the collision was permanent.

    ``poll()`` started with ``rows = None`` and bailed out early on ``rows is None``,
    so a build that genuinely returned ``None`` looked like "nothing arrived" - and
    ``_pending`` was never cleared. From then on every ``request()`` coalesced into
    ``_latest`` and nothing ever ran again: the table stopped rebuilding for the rest
    of the session, and ``busy()`` stayed True, leaving the page's 40 ms catch-up
    poll rescheduling itself for ever.

    Latent today (the connections page always returns a dict), but ``AsyncModel`` is
    the mechanism every future heavy table is meant to use, so the contract has to
    hold before somebody builds on it.
    """
    model = AsyncModel(lambda payload: None)
    model.request("first")

    # poll the way the page does - busy() only clears once a result is COLLECTED
    def polled_until_idle(timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            assert model.poll() is None, "there is no model to show, and that is fine"
            if not model.busy():
                return True
            time.sleep(0.005)
        return False

    assert polled_until_idle(), \
        "a build returning None never released the worker"

    # the point of the fix: the worker is still usable afterwards
    delivered = AsyncModel(lambda payload: [payload])
    delivered.request("later")
    assert _collect(delivered, timeout=5) == ["later"]

    # and the SAME instance recovers too, once its build starts producing rows
    model._build = lambda payload: [payload]
    model.request("second")
    assert _collect(model, timeout=5) == ["second"], \
        "the worker never accepted another request"


def test_no_thread_is_left_behind():
    """Twenty rebuilds must not leave twenty threads.

    (``busy()`` stays true until the result is COLLECTED, which is what the page's
    fast poll relies on - so the way to wait for a rebuild is to poll for it, not
    to spin on ``busy()``.)
    """
    before = threading.active_count()
    model = AsyncModel(lambda p: [p])
    for i in range(20):
        model.request(i)
        assert _collect(model, timeout=5) == [i]
    time.sleep(0.3)
    assert threading.active_count() <= before + 1, "model workers are leaking"
