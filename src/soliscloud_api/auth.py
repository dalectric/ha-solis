import base64
import hashlib
import hmac
from email.utils import formatdate

CONTENT_TYPE = "application/json"


def compute_content_md5(body: str) -> str:
    digest = hashlib.md5(body.encode("utf-8"), usedforsecurity=False).digest()
    return base64.b64encode(digest).decode("utf-8")


def build_sign_string(
    content_md5: str,
    content_type: str,
    date: str,
    canonicalized_resource: str,
) -> str:
    """The exact string SolisCloud expects to be HMAC-signed.

    Exposed separately so the probe command can print it verbatim -- a wrong signature
    is otherwise close to undebuggable from the API's error message alone.
    """
    return "\n".join(["POST", content_md5, content_type, date, canonicalized_resource])


def compute_authorization(
    api_secret: str,
    content_md5: str,
    content_type: str,
    date: str,
    canonicalized_resource: str,
) -> str:
    sign_str = build_sign_string(content_md5, content_type, date, canonicalized_resource)
    signature = hmac.new(
        api_secret.encode("utf-8"),
        sign_str.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(signature).decode("utf-8")


def build_auth_headers(
    api_id: str,
    api_secret: str,
    body: str,
    canonicalized_resource: str,
) -> tuple[dict[str, str], str]:
    """Return the request headers and the exact string that was signed.

    The sign string is returned rather than recomputed by callers, so anything that
    displays it (the probe command) shows what was really signed, not a reconstruction
    that could drift from it.
    """
    content_type = CONTENT_TYPE
    date = formatdate(usegmt=True)
    content_md5 = compute_content_md5(body)
    sign_string = build_sign_string(content_md5, content_type, date, canonicalized_resource)
    signature = hmac.new(
        api_secret.encode("utf-8"),
        sign_string.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    sign = base64.b64encode(signature).decode("utf-8")

    headers = {
        "Content-Type": content_type,
        "Date": date,
        "Content-MD5": content_md5,
        "Authorization": f"API {api_id}:{sign}",
    }
    return headers, sign_string
