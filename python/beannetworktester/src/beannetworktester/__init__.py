# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Slow down, break or cut the network for a test: pytest, Playwright for Python, any code.

    from beannetworktester import bad_network

    with bad_network(server="http://localhost:3000", latency=300, loss=2):
        ...   # every connection to that server is slowed, on a real network

In pytest the ``bad_network`` fixture does the same and stops the session when the
test ends. It runs Bean Network Tester's own program, which this package carries for
Windows x64 and Linux x64.
"""

from ._program import BadNetworkError
from ._session import BadNetwork, BadNetworkWarning, bad_network

__all__ = ["BadNetwork", "BadNetworkError", "BadNetworkWarning", "bad_network"]
