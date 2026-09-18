import base64
import hashlib
import hmac
import re
from unittest.mock import patch

import pytest

from soliscloud_api.auth import (
    build_auth_headers,
    build_sign_string,
    compute_authorization,
    compute_content_md5,
)


class TestComputeContentMd5:
    def test_known_input(self):
        body = '{"pageNo":1,"pageSize":100}'
        expected = base64.b64encode(hashlib.md5(body.encode("utf-8"), usedforsecurity=False).digest()).decode("utf-8")
        assert compute_content_md5(body) == expected

    def test_empty_body(self):
        body = "{}"
        result = compute_content_md5(body)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_deterministic(self):
        body = '{"key":"value"}'
        assert compute_content_md5(body) == compute_content_md5(body)


class TestComputeAuthorization:
    def test_known_values(self):
        secret = "test-secret"
        md5 = "abc123"
        ct = "application/json"
        date = "Sat, 01 Jan 2026 00:00:00 GMT"
        resource = "/v1/api/inverterList"

        sign_str = f"POST\n{md5}\n{ct}\n{date}\n{resource}"
        expected = base64.b64encode(
            hmac.new(secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha1).digest()
        ).decode("utf-8")

        result = compute_authorization(secret, md5, ct, date, resource)
        assert result == expected

    def test_different_secrets_produce_different_signatures(self):
        args = ("md5val", "application/json", "date", "/v1/api/test")
        sig1 = compute_authorization("secret1", *args)
        sig2 = compute_authorization("secret2", *args)
        assert sig1 != sig2


class TestBuildAuthHeaders:
    @patch("soliscloud_api.auth.formatdate", return_value="Sat, 01 Jan 2026 00:00:00 GMT")
    def test_returns_required_headers(self, _mock_date):
        headers, _ = build_auth_headers("my-id", "my-secret", '{"key":"val"}', "/v1/api/test")

        assert "Content-Type" in headers
        assert headers["Content-Type"] == "application/json"
        assert "Date" in headers
        assert "Content-MD5" in headers
        assert "Authorization" in headers

    @patch("soliscloud_api.auth.formatdate", return_value="Sat, 01 Jan 2026 00:00:00 GMT")
    def test_authorization_format(self, _mock_date):
        headers, _ = build_auth_headers("my-id", "my-secret", "{}", "/v1/api/test")
        assert headers["Authorization"].startswith("API my-id:")

    @patch("soliscloud_api.auth.formatdate", return_value="Sat, 01 Jan 2026 00:00:00 GMT")
    def test_content_md5_matches(self, _mock_date):
        body = '{"pageNo":1}'
        headers, _ = build_auth_headers("id", "secret", body, "/v1/api/test")
        assert headers["Content-MD5"] == compute_content_md5(body)


class TestDateHeaderIsLocaleIndependent:
    """The Date header is signed, so a localised day/month name breaks authentication.

    email.utils.formatdate uses hardcoded English names; strftime("%a"/"%b") does not.
    That is the reason for the formatdate call in auth.py.
    """

    def test_format_is_rfc_1123_english(self):
        from email.utils import formatdate

        pattern = r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4} \d{2}:\d{2}:\d{2} GMT$"
        assert re.match(pattern, formatdate(usegmt=True))

    def test_stays_english_under_a_non_english_locale(self):
        import locale
        from email.utils import formatdate

        previous = locale.setlocale(locale.LC_TIME)
        for candidate in ("de_DE.UTF-8", "fr_FR.UTF-8", "nl_NL.UTF-8"):
            try:
                locale.setlocale(locale.LC_TIME, candidate)
            except locale.Error:
                continue
            try:
                result = formatdate(usegmt=True)
            finally:
                locale.setlocale(locale.LC_TIME, previous)
            assert result.split(",")[0] in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
            return
        pytest.skip("no non-English locale available on this machine")


class TestReturnedSignStringMatchesTheSignature:
    """The probe prints this string; it must be what was actually signed.

    Previously the client rebuilt it from parts, so a change to what
    build_auth_headers signs would have made the debug output silently wrong.
    """

    @patch("soliscloud_api.auth.formatdate", return_value="Sat, 01 Jan 2026 00:00:00 GMT")
    def test_sign_string_reproduces_the_authorization_header(self, _mock_date):
        body = '{"pageNo":1,"pageSize":100}'
        headers, sign_string = build_auth_headers("my-id", "my-secret", body, "/v1/api/inverterList")

        expected = base64.b64encode(hmac.new(b"my-secret", sign_string.encode("utf-8"), hashlib.sha1).digest()).decode(
            "utf-8"
        )
        assert headers["Authorization"] == f"API my-id:{expected}"

    @patch("soliscloud_api.auth.formatdate", return_value="Sat, 01 Jan 2026 00:00:00 GMT")
    def test_sign_string_embeds_the_sent_headers(self, _mock_date):
        body = "{}"
        headers, sign_string = build_auth_headers("id", "secret", body, "/v1/api/test")
        assert sign_string == build_sign_string(
            headers["Content-MD5"], headers["Content-Type"], headers["Date"], "/v1/api/test"
        )
