"""
broker/upstox/auth.py
--------------
Handles Upstox OAuth2 Authentication and daily token management.

HOW UPSTOX OAuth2 WORKS (Plain English):
-----------------------------------------
Upstox uses a two-step login process called OAuth2:

Step 1 — Get Authorization Code:
    You open a special Upstox URL in your browser.
    You log in with your Upstox credentials.
    Upstox redirects your browser to your redirect_uri with a 'code' in the URL.
    Example: https://127.0.0.1:5000/callback?code=abc123

Step 2 — Exchange Code for Access Token:
    You take that 'code' and POST it to Upstox along with your API key + secret.
    Upstox gives you an access_token (valid for the rest of the trading day).
    You store this token and use it in every subsequent API call.

IMPORTANT:
    - The token expires every day at midnight.
    - You must repeat this flow every morning before trading starts.
    - Our scheduler (Phase 7) will automate this at 9:00 AM daily.

USAGE:
    from broker.upstox.auth import AuthManager
    auth = AuthManager()

    # Step 1: Get the login URL and open it in browser
    url = auth.get_login_url()

    # Step 2: After redirect, you can either:
    # Option A: Use just the code from the URL
    token = auth.generate_token(auth_code="abc123")
    # Option B: Use the full redirect URL (recommended)
    token = auth.generate_token_from_url("https://127.0.0.1:5000/?code=abc123")
    # Option C: Capture the redirect automatically via a local callback server
    token = auth.login_and_capture_token()

    # All subsequent uses — just get a valid token:
    token = auth.get_valid_token()
"""

import json
import logging
import os
import socket
import ssl
import stat
import threading
import webbrowser
from datetime import datetime, date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlparse, parse_qs

try:
    import requests
except ImportError:  # pragma: no cover - dependency is optional in tests
    requests = None

from config import config

# Module-level logger — follows the pattern established in config.py
logger = logging.getLogger(__name__)

KEYRING_SERVICE = "algodesk"
KEYRING_USERNAME = "upstox_token"


def _get_keyring():
    """Import keyring lazily so auth does not depend on it at module import time."""
    try:
        import keyring  # type: ignore
        return keyring
    except ImportError:  # pragma: no cover - optional dependency in tests/dev envs
        return None


class _DualProtocolLoopbackListener:
    """
    Accept HTTPS or plain HTTP on the same loopback port.

    This is useful for local OAuth callbacks because the browser may first hit
    the registered HTTPS loopback URI and, after certificate interstitial flow,
    end up sending a plain HTTP request to the same port.
    """

    def __init__(
        self,
        host: str,
        port: int,
        expected_path: str,
        cert_file: str,
        key_file: str,
    ) -> None:
        if not cert_file or not key_file:
            raise RuntimeError(
                "HTTPS redirect capture requires "
                "UPSTOX_REDIRECT_SSL_CERT_FILE and "
                "UPSTOX_REDIRECT_SSL_KEY_FILE."
            )

        self.host = host
        self.port = port
        self.expected_path = expected_path or "/"
        self.timeout = 0.5
        self.captured: dict[str, Optional[str]] = {"url": None}
        self.event = threading.Event()
        self._stop_event = threading.Event()

        self._ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._ssl_context.load_cert_chain(certfile=cert_file, keyfile=key_file)

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(5)
        self._sock.settimeout(self.timeout)

    def serve_forever(self) -> None:
        while not self._stop_event.is_set():
            try:
                conn, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._handle_connection(conn)

    def shutdown(self) -> None:
        self._stop_event.set()

    def server_close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def _handle_connection(self, raw_conn: socket.socket) -> None:
        conn = raw_conn
        scheme = "http"
        try:
            try:
                first_byte = raw_conn.recv(1, socket.MSG_PEEK)
            except (OSError, ValueError):
                first_byte = b""

            # TLS handshake records start with 0x16.
            if first_byte[:1] == b"\x16":
                conn = self._ssl_context.wrap_socket(raw_conn, server_side=True)
                scheme = "https"

            conn.settimeout(2.0)
            request_bytes = b""
            while b"\r\n\r\n" not in request_bytes and len(request_bytes) < 8192:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                request_bytes += chunk

            if not request_bytes:
                return

            lines = request_bytes.decode("latin1", errors="ignore").split("\r\n")
            request_line = lines[0] if lines else ""
            parts = request_line.split()
            path = parts[1] if len(parts) >= 2 else "/"
            host_header = f"{self.host}:{self.port}"
            for line in lines[1:]:
                if line.lower().startswith("host:"):
                    host_header = line.split(":", 1)[1].strip()
                    break

            query = parse_qs(urlparse(path).query)
            request_path = urlparse(path).path
            if request_path.startswith(self.expected_path) or "code" in query:
                self.captured["url"] = f"{scheme}://{host_header}{path}"
                self.event.set()
                body = (
                    "<html><body><h3>Upstox login captured.</h3>"
                    "<p>You can close this window now.</p></body></html>"
                ).encode("utf-8")
                self._send_response(conn, 200, body)
                return

            self._send_response(conn, 404, b"Not Found")
        except ssl.SSLError as exc:
            logger.debug("Local redirect TLS error: %s", exc)
        except OSError as exc:
            logger.debug("Local redirect socket error: %s", exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @staticmethod
    def _send_response(conn: socket.socket, status_code: int, body: bytes) -> None:
        status_text = "OK" if status_code == 200 else "Not Found"
        response = (
            f"HTTP/1.1 {status_code} {status_text}\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("utf-8") + body
        conn.sendall(response)


def _require_requests() -> None:
    """Raise a clear error when the requests dependency is absent."""
    if requests is None:
        raise RuntimeError(
            "The 'requests' package is required for Upstox authentication "
            "and instrument downloads."
        )


class AuthManager:
    """
    Manages the full Upstox OAuth2 authentication lifecycle.

    Responsibilities:
    - Generate the Upstox login URL for the browser
    - Exchange the auth code for an access token
    - Save the token to disk (so you don't re-login on every restart)
    - Load and validate the saved token on startup
    - Detect if the token is expired (it's a new day) and prompt re-login
    """

    def __init__(self):
        self.api_key = config.UPSTOX_API_KEY
        self.api_secret = config.UPSTOX_API_SECRET
        self.redirect_uri = config.UPSTOX_REDIRECT_URI
        self.auth_url = config.UPSTOX_AUTH_URL
        self.token_file = config.UPSTOX_TOKEN_FILE_PATH

        # In-memory token cache: loaded from file or freshly generated
        self._token_data: Optional[dict] = None

    # ── Step 1: Generate Login URL ────────────────────────────────────────────

    def get_login_url(self) -> str:
        """
        Build and return the Upstox authorization URL.

        The user must open this URL in a browser, log in to Upstox,
        and then copy the redirected URL (or just the 'code' parameter).

        Returns:
            str: Full authorization URL to open in browser.
        """
        params = {
            "response_type": "code",
            "client_id": self.api_key,
            "redirect_uri": self.redirect_uri,
        }
        login_url = f"https://api.upstox.com/v2/login/authorization/dialog?{urlencode(params)}"
        logger.info("Login URL generated. Opening in browser...")
        logger.info(f"If browser doesn't open, manually visit:\n{login_url}")
        return login_url

    def open_login_page(self):
        """
        Convenience method: generate the login URL and open it in the default browser.
        After logging in, Upstox will redirect to your redirect_uri with ?code=...
        """
        url = self.get_login_url()
        webbrowser.open(url)
        print("\n" + "=" * 60)
        print("  UPSTOX LOGIN")
        print("=" * 60)
        print("1. Your browser should have opened the Upstox login page.")
        print("2. Log in with your Upstox credentials.")
        print("3. After login, you'll be redirected to a URL like:")
        print("   http://127.0.0.1:5000?code=XXXXX")
        print("4. Copy that full URL (or just the code value) and")
        print("   call: auth.generate_token_from_url('<paste here>')")
        print("=" * 60 + "\n")

    def _build_redirect_listener(self):
        """
        Create the temporary callback server plus its captured-url state.

        The caller is responsible for starting ``serve_forever`` in a thread and
        shutting the server down in a ``finally`` block.
        """
        parsed = urlparse(self.redirect_uri)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        expected_path = parsed.path or "/"
        is_loopback = host in {"127.0.0.1", "localhost"}

        if parsed.scheme == "https" and is_loopback:
            server = _DualProtocolLoopbackListener(
                host=host,
                port=port,
                expected_path=expected_path,
                cert_file=config.UPSTOX_REDIRECT_SSL_CERT_FILE,
                key_file=config.UPSTOX_REDIRECT_SSL_KEY_FILE,
            )
            return server, server.event, server.captured

        captured: dict[str, Optional[str]] = {"url": None}
        event = threading.Event()

        class _CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # type: ignore[override]
                request_path = urlparse(self.path).path
                query = parse_qs(urlparse(self.path).query)
                if self.path.startswith(expected_path) or "code" in query:
                    scheme = parsed.scheme or "http"
                    host_header = self.headers.get("Host", f"{host}:{port}")
                    captured["url"] = f"{scheme}://{host_header}{self.path}"
                    event.set()
                    body = (
                        "<html><body><h3>Upstox login captured.</h3>"
                        "<p>You can close this window now.</p></body></html>"
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                self.send_response(404)
                self.end_headers()

            def log_message(self, format, *args):  # noqa: A003
                return

        server = ThreadingHTTPServer((host, port), _CallbackHandler)
        server.timeout = 0.5

        if parsed.scheme == "https":
            cert_file = config.UPSTOX_REDIRECT_SSL_CERT_FILE
            key_file = config.UPSTOX_REDIRECT_SSL_KEY_FILE
            if not cert_file or not key_file:
                server.server_close()
                raise RuntimeError(
                    "HTTPS redirect capture requires "
                    "UPSTOX_REDIRECT_SSL_CERT_FILE and "
                    "UPSTOX_REDIRECT_SSL_KEY_FILE. "
                    "Alternatively set UPSTOX_REDIRECT_URI to an http://127.0.0.1 callback."
                )
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(certfile=cert_file, keyfile=key_file)
            server.socket = ssl_context.wrap_socket(server.socket, server_side=True)

        return server, event, captured

    def wait_for_redirect_url(self, timeout: int = 180) -> str:
        """
        Start a temporary local callback server and wait for Upstox redirect.

        This removes the need to manually copy the short-lived browser URL.
        The redirect URI configured in Upstox must point to this same local
        address and port.
        """
        server, event, captured = self._build_redirect_listener()

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            if not event.wait(timeout):
                raise TimeoutError(
                    f"Timed out after {timeout}s waiting for Upstox redirect on {self.redirect_uri}"
                )
            if not captured["url"]:
                raise RuntimeError("Redirect was received but the URL could not be captured.")
            return str(captured["url"])
        finally:
            server.shutdown()
            server.server_close()

    def login_and_capture_token(self, timeout: int = 180, open_browser: bool = True) -> dict:
        """
        Open the Upstox login page, wait for the redirect locally, and
        exchange the captured code for an access token.
        """
        login_url = self.get_login_url()
        server, event, captured = self._build_redirect_listener()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            logger.info("Local redirect listener started on %s", self.redirect_uri)
            if open_browser:
                webbrowser.open(login_url)
            if not event.wait(timeout):
                raise TimeoutError(
                    f"Timed out after {timeout}s waiting for Upstox redirect on {self.redirect_uri}"
                )
            redirect_url = captured.get("url")
            if not redirect_url:
                raise RuntimeError("Redirect was received but the URL could not be captured.")
            logger.info("Captured redirect URL automatically from local callback server.")
            return self.generate_token_from_url(str(redirect_url))
        finally:
            server.shutdown()
            server.server_close()

    # ── Step 2: Exchange Code for Token ───────────────────────────────────────

    def generate_token(self, auth_code: str) -> dict:
        """
        Exchange the authorization code for an access token.

        Upstox gives us an access_token after we send:
        - The auth code received from the browser redirect
        - Our API key and API secret

        Args:
            auth_code (str): The 'code' value from the redirect URL.

        Returns:
            dict: Token data including 'access_token', 'token_type', etc.

        Raises:
            ValueError: If the API returns an error.
            requests.RequestException: If the network call fails.
        """
        _require_requests()
        logger.info("Exchanging authorization code for access token...")

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        payload = {
            "code": auth_code,
            "client_id": self.api_key,
            "client_secret": self.api_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }

        try:
            response = requests.post(
                self.auth_url,
                data=payload,
                headers=headers,
                timeout=15  # 15-second timeout — never block forever
            )
            response.raise_for_status()  # Raises HTTPError for 4xx/5xx responses

        except requests.exceptions.Timeout:
            logger.error("Token request timed out after 15 seconds.")
            raise

        except requests.exceptions.ConnectionError:
            logger.error("Network error: Could not reach Upstox API. Check your internet.")
            raise

        except requests.exceptions.HTTPError as e:
            # Parse the error body from Upstox for a helpful message
            error_body = response.json() if response.content else {}
            error_msg = error_body.get("message", str(e))
            logger.error(f"Upstox API error during token exchange: {error_msg}")
            raise ValueError(f"Token generation failed: {error_msg}") from e

        token_data = response.json()

        # Add the date this token was generated so we can detect expiry tomorrow
        token_data["generated_date"] = date.today().isoformat()

        # Save to disk and cache in memory
        self._save_token(token_data)
        self._token_data = token_data

        logger.info(
            f"✅ Access token generated successfully. "
        )

        return token_data

    def generate_token_from_url(self, redirect_url: str) -> dict:
        """
        Convenience method: extracts the auth code from the full redirect URL
        and then generates the token.

        Args:
            redirect_url (str): The full URL you were redirected to after login.
                                 e.g. https://127.0.0.1:5000/

        Returns:
            dict: Token data.
        """
        try:
            parsed = urlparse(redirect_url)
            params = parse_qs(parsed.query)
            auth_code = params.get("code", [None])[0]

            if not auth_code:
                raise ValueError(
                    "Could not find 'code' in the redirect URL. "
                    "Make sure you copied the full URL after login."
                )

            logger.info(f"Extracted auth code from redirect URL.")
            return self.generate_token(auth_code)

        except Exception as e:
            logger.error(f"Failed to extract auth code from URL: {e}")
            raise

    # ── Token Storage ─────────────────────────────────────────────────────────

    def _save_token(self, token_data: dict):
        """
        Save token data to disk as JSON.

        Why we save to disk: If the app restarts during the trading day,
        we don't want to force the user to log in again. As long as the
        saved token was generated today, it's still valid.

        Security model:
        - Store the bearer token in the OS keyring when available.
        - Persist only non-secret token metadata to JSON on disk.
        - Restrict the JSON file to owner read/write (0o600).

        Args:
            token_data (dict): Token data from Upstox API.
        """
        if requests is None:
            # No network dependency needed here, but keep the guard in place
            # so downstream callers get a clearer failure mode if the module
            # is used in a stripped-down environment.
            pass
        try:
            # Ensure the parent directory exists
            self.token_file.parent.mkdir(parents=True, exist_ok=True)

            access_token = token_data.get("access_token", "")
            keyring_backend = _get_keyring()
            disk_token_data = dict(token_data)

            if access_token and keyring_backend is not None:
                keyring_backend.set_password(
                    KEYRING_SERVICE, KEYRING_USERNAME, access_token
                )
                disk_token_data.pop("access_token", None)

            with open(self.token_file, "w") as f:
                json.dump(disk_token_data, f, indent=2)

            os.chmod(self.token_file, stat.S_IRUSR | stat.S_IWUSR)

            if access_token and keyring_backend is None:
                logger.warning(
                    "keyring is not installed; falling back to storing access token "
                    "in a local file restricted to mode 0o600."
                )

            logger.info(f"Token metadata saved to: {self.token_file} (mode 0o600)")

        except Exception as e:
            # This is non-fatal — we still have the token in memory
            logger.warning(f"Could not persist token security: {e}")


    def _load_token(self) -> Optional[dict]:
        """
        Load token from disk if it exists.

        Returns:
            dict if a valid (today's) token exists on disk, else None.
        """
        if not self.token_file.exists():
            logger.info("No saved token file found.")
            return None

        try:
            with open(self.token_file, "r") as f:
                token_data = json.load(f)
            generated_date = token_data.get("generated_date")

            # Check if the token was generated today
            if generated_date == date.today().isoformat():
                keyring_backend = _get_keyring()
                access_token = None
                if keyring_backend is not None:
                    access_token = keyring_backend.get_password(
                        KEYRING_SERVICE, KEYRING_USERNAME
                    )

                # Backward-compatibility: support older plaintext token files.
                if not access_token:
                    access_token = token_data.get("access_token")

                if not access_token:
                    logger.warning(
                        "Token metadata exists but no access token is available in keyring."
                    )
                    return None

                token_data["access_token"] = access_token
                logger.info(f"Valid token loaded from disk (generated today: {generated_date})")
                return token_data
            else:
                logger.warning(
                    f"Saved token is from {generated_date}, not today. "
                    f"A new login is required."
                )
                return None

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Token file is corrupted or unreadable: {e}. Ignoring.")
            return None

    # ── Main Public Interface ─────────────────────────────────────────────────

    def get_valid_token(self) -> str:
        """
        The main method all other modules should call to get a usable token.

        Logic:
        1. If we have a token in memory that was generated today → return it.
        2. If there's a valid token on disk (generated today) → load and return it.
        3. Otherwise → raise an error telling the user to log in.

        Returns:
            str: The access token string.

        Raises:
            RuntimeError: If no valid token exists and a new login is required.
        """
        # 1. Check in-memory cache first (fastest)
        if self._token_data:
            if self._token_data.get("generated_date") == date.today().isoformat():
                return self._token_data["access_token"]
            else:
                logger.info("In-memory token is from a previous day. Clearing cache.")
                self._token_data = None

        # 2. Try loading from disk
        token_data = self._load_token()
        if token_data:
            self._token_data = token_data
            return token_data["access_token"]

        # 3. No valid token — user must log in
        raise RuntimeError(
            "\n" + "=" * 60 +
            "\n  ⚠️  NO VALID TOKEN FOUND" +
            "\n  You need to log in to Upstox for today's session." +
            "\n  Run the following in your terminal:" +
            "\n\n  from broker.auth import AuthManager" +
            "\n  auth = AuthManager()" +
            "\n  auth.login_and_capture_token()   # preferred" +
            "\n  # or auth.open_login_page() + auth.generate_token_from_url(...)" +
            "\n" + "=" * 60
        )

    def is_authenticated(self) -> bool:
        """
        Quick check: do we have a valid token for today?

        Returns:
            bool: True if authenticated, False if login is needed.
        """
        try:
            self.get_valid_token()
            return True
        except RuntimeError:
            return False

    def get_token_info(self) -> dict:
        """
        Return non-sensitive info about the current token for display/logging.

        Returns:
            dict with token status info (no actual token value exposed in logs).
        """
        if self._token_data:
            return {
                "status": "valid",
                "generated_date": self._token_data.get("generated_date"),
                "token_type": self._token_data.get("token_type", "bearer"),
                "user_id": self._token_data.get("user_id", "unknown"),
            }

        # Try loading from disk without raising error
        token_data = self._load_token()
        if token_data:
            return {
                "status": "valid (from disk)",
                "generated_date": token_data.get("generated_date"),
                "token_type": token_data.get("token_type", "bearer"),
                "user_id": token_data.get("user_id", "unknown"),
            }

        return {"status": "not authenticated — login required"}

    def logout(self):
        """
        Clear token from memory and disk.
        Also calls the Upstox logout endpoint to invalidate the token server-side.
        """
        logger.info("Logging out and clearing token...")

        # Attempt server-side logout (non-critical — proceed even if it fails)
        try:
            _require_requests()
            token = self._token_data.get("access_token") if self._token_data else None
            if token:
                requests.delete(
                    f"{config.BASE_URL}/v2/logout",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    timeout=10,
                )
        except Exception as e:
            logger.warning(f"Server-side logout failed (non-critical): {e}")

        # Clear from memory
        self._token_data = None

        # Delete token file from disk
        if self.token_file.exists():
            self.token_file.unlink()
            logger.info("Token file deleted from disk.")

        keyring_backend = _get_keyring()
        if keyring_backend is not None:
            try:
                keyring_backend.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
            except Exception:
                pass

        logger.info("✅ Logged out successfully.")


# ── Module-level singleton ────────────────────────────────────────────────────
# All other modules use this single instance:
#   from broker.auth import auth_manager
#   token = auth_manager.get_valid_token()
auth_manager = AuthManager()
