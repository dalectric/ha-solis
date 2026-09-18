"""Exception hierarchy for the SolisCloud API.

Every failure mode gets its own type. The integration this replaces collapsed HTTP
errors, transport errors, API-level errors and a genuinely empty result into a single
empty return value, so "No inverters found" was logged identically whether the
credentials were wrong, the clock was skewed, the rate limit was hit or the plant
really had no inverters. Callers here can always tell those apart.
"""


class SolisError(Exception):
    """Base class for every SolisCloud failure."""


class SolisAuthError(SolisError):
    """Credentials or signature rejected. Never worth retrying."""

    def __init__(self, code: str, msg: str, endpoint: str | None = None):
        self.code = code
        self.msg = msg
        self.endpoint = endpoint
        super().__init__(f"SolisCloud auth failed ({code}): {msg}")


class SolisClockSkewError(SolisError):
    """HTTP 408.

    Usually means the signed Date header is too far from the server's clock, but a
    proxy in front of a slow API also returns 408 for an ordinary request timeout,
    so this is retried rather than treated as fatal.
    """

    def __init__(self, local_date: str, server_date: str | None = None):
        self.local_date = local_date
        self.server_date = server_date
        detail = f" (server said {server_date})" if server_date else ""
        super().__init__(
            f"SolisCloud returned 408 for a request dated {local_date}{detail}. "
            "Most often a clock/timezone mismatch on this machine; can also be a "
            "gateway timeout, since the API is slow."
        )


class SolisRateLimitError(SolisError):
    """Rate limited. SolisCloud allows three calls per five seconds per IP."""

    def __init__(self, msg: str = "rate limited", retry_after: float | None = None):
        self.retry_after = retry_after
        super().__init__(f"SolisCloud rate limit hit: {msg}")


class SolisAPIError(SolisError):
    """The API answered with a non-zero code."""

    def __init__(self, code: str, msg: str, endpoint: str | None = None, request_body: str | None = None):
        self.code = code
        self.msg = msg
        self.endpoint = endpoint
        self.request_body = request_body
        where = f" at {endpoint}" if endpoint else ""
        super().__init__(f"SolisCloud API error {code}{where}: {msg}")


class SolisTransportError(SolisError):
    """Timeout, connection reset or other network-level failure."""

    def __init__(self, msg: str, endpoint: str | None = None):
        self.endpoint = endpoint
        where = f" to {endpoint}" if endpoint else ""
        super().__init__(f"SolisCloud request{where} failed: {msg}")
