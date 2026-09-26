"""Tiny local site used by the integration tests (mirrors the AEM page structure)."""
from __future__ import annotations

import json
import threading
from functools import partial
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent


# A stand-in for the site's WAF.  WAF["until"]: until then every /bin/ call (and, with WAF["pages"], every page) is answered 403.
# FLAKY: the first FLAKY["block"] loads of /flaky/... are answered 403 (a WAF that lets you in once it has cooled down).
WAF = {"until": 0.0, "pages": False}
FLAKY = {"block": 0, "seen": 0}


# A stand-in for Okta's code check (``okta.html``): the secret it checks against and the codes it has already accepted (each code works once).
OKTA: dict = {"secret": "", "used": set(), "seen": []}


# A stand-in for the policy API (API tests): what the last request looked like, so tests can see exactly what was sent.
API_SEEN: dict = {"headers": {}, "body": None, "path": "", "count": 0}
POLICY = {"transactionStatus": "Success", "detailResponse": {"policyDetail": {
    "displayStatus": "Active", "accountDetail": {"agent": {"email": "qa@example.com"}},
    "travelers": [{"customElements": [{"value": "n/a"}, {"value": "Cover not available"}]}], "premium": 123.5, "covered": True}}}


# The frames reCAPTCHA serves: the challenge (pick the pictures; its Verify button tells the page it was solved) and the badge.
CAPTCHA_FRAMES = {
    "bframe": b"<!doctype html><html><body><div class='rc-imageselect-desc-wrapper'><strong>Select all images with</strong><br>"
              b"<strong>a fire hydrant</strong><br><span>Click verify once there are none left.</span></div>"
              b"<button id='verify' onclick=\"parent.postMessage('captcha-solved', '*')\">Verify</button></body></html>",
    "anchor": b"<!doctype html><html><body>Protected by reCAPTCHA</body></html>",
}


class Handler(SimpleHTTPRequestHandler):
    def _json(self, status: int, payload, headers: dict | None = None) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _api(self, method: str) -> bool:
        """/policy/v4/... needs the apiKey and Bearer headers, like the real API.  Returns True when it answered."""
        if not self.path.startswith(("/policy/", "/cloudfront")):
            return False
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        API_SEEN.update(headers={k.lower(): v for k, v in self.headers.items()}, path=self.path, count=API_SEEN["count"] + 1,
                        body=json.loads(raw) if raw else None)
        if self.path.split("?")[0] == "/policy/v4/":                       # the gateway's answer to a URL that is not one of its routes: JSON, from the API itself
            self._json(403, {"message": "Invalid key=value pair (missing equal-sign) in Authorization header (hashed with SHA-256 and encoded with Base64): 'abc='."},
                       {"Via": "1.1 abc.cloudfront.net (CloudFront)", "X-Amz-Cf-Id": "xyz", "x-amzn-ErrorType": "IncompleteSignatureException"})
        elif self.path.startswith("/cloudfront"):
            self._json(403, {"message": "Request blocked."}, {"Server": "CloudFront", "X-Cache": "Error from cloudfront", "X-Amz-Cf-Id": "abc"})
        elif method == "POST" and self.path == "/policy/purchase/v2":       # the purchase API: the key only; answers with the last name it was sent
            if self.headers.get("apiKey") != "KEY-123":
                self._json(401, {"message": "Unauthorized"})
            else:
                body = API_SEEN["body"] or {}
                self._json(200, {"transactionStatus": "Success", "siteUrl": f"http://{self.headers.get('Host')}/", "purchaseResponse": {"policyResponses": [
                    {"policyDetail": {"policyNumber": "P-777", "policyHolder": {"firstName": "Claim", "lastName": body.get("lastName")}}},
                    {"policyDetail": {"policyNumber": "P-778", "policyHolder": {"firstName": "Duplicate", "lastName": "Second"}}}]}})
        elif self.headers.get("apiKey") != "KEY-123" or not str(self.headers.get("Authorization", "")).startswith("Bearer TOKEN-"):
            self._json(401, {"message": "Unauthorized"})
        elif method == "GET" and self.path == "/policy/v4/P-100":
            self._json(200, POLICY)
        elif method == "POST" and self.path == "/policy/v4/search":
            self._json(200, {"echo": API_SEEN["body"], "transactionStatus": "Success"})
        else:
            self._json(404, {"message": "Not found", "path": self.path})
        return True

    def do_POST(self):
        if not self._api("POST"):
            self.send_error(405)

    def _forbidden(self) -> None:
        body = b"Forbidden"
        self.send_response(403)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self._api("GET"):
            return
        import time as _time
        if _time.time() < WAF["until"] and (self.path.startswith("/bin/") or (WAF["pages"] and not self.path.startswith("/api/"))):
            return self._forbidden()
        if self.path.startswith("/recaptcha/api2/"):
            body = CAPTCHA_FRAMES["bframe" if "/bframe" in self.path else "anchor"]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/flaky/"):
            FLAKY["seen"] += 1
            if FLAKY["seen"] <= FLAKY["block"]:
                return self._forbidden()
            self.path = self.path[len("/flaky"):] or "/"
        if self.path.startswith(("/api/slow", "/bin/slow")):
            import time
            from urllib.parse import parse_qs, urlparse
            time.sleep(int((parse_qs(urlparse(self.path).query).get("ms") or ["800"])[0]) / 1000)
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/okta/verify"):
            from urllib.parse import parse_qs, urlparse
            from regrunner import totp
            code = (parse_qs(urlparse(self.path).query).get("code") or [""])[0]
            OKTA["seen"].append(code)
            if code in OKTA["used"]:
                return self._json(403, {"errorCode": "E0000068", "errorSummary": "Each code can only be used once", "passCode": code})
            if not OKTA["secret"] or code != totp.code_at(OKTA["secret"]):             # strict: only the current window's code
                return self._json(403, {"errorCode": "E0000068", "errorSummary": "Invalid Passcode/Answer", "passCode": code})
            OKTA["used"].add(code)
            return self._json(200, {"status": "SUCCESS"})
        if self.path.startswith("/bin/forever"):
            import time
            time.sleep(120)                                    # never, as far as a test is concerned
            try:
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
            except OSError:
                pass
            return
        if self.path.startswith(("/api/hang", "/bin/hang")):
            import time
            time.sleep(20)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/forbidden"):
            body = b"<html><head><title>403 Forbidden</title></head><body>Access denied</body></html>"
            self.send_response(403)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/api/whoami"):
            jar = SimpleCookie(self.headers.get("Cookie", ""))
            token = jar["recaptchaBypassToken"].value if "recaptchaBypassToken" in jar else ""
            body = json.dumps({"bypass": token}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def log_message(self, *args):  # keep test output clean
        pass


def start(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"
