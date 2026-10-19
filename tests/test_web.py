import json
import threading
import unittest
from http.client import HTTPResponse
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.web import MAX_REQUEST_BYTES, ExplainMyDiffHandler


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "fixture-a.diff"


class WebInterfaceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ExplainMyDiffHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, path: str, method: str = "GET", body: bytes | None = None) -> tuple[int, dict[str, str], bytes]:
        request = Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            response: HTTPResponse = urlopen(request, timeout=5)
        except HTTPError as error:
            body = error.read()
            error.close()
            return error.code, dict(error.headers.items()), body
        return response.status, dict(response.headers.items()), response.read()

    def test_health_returns_json_status(self) -> None:
        status, headers, body = self.request("/health")

        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["content-type".title()])
        self.assertEqual(json.loads(body), {"status": "ok"})

    def test_homepage_is_self_contained_ui(self) -> None:
        status, headers, body = self.request("/")
        page = body.decode("utf-8")

        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["content-type".title()])
        self.assertIn("Explain My Diff", page)
        self.assertIn("/api/triage", page)
        self.assertIn("<style>", page)
        self.assertIn("<script>", page)

    def test_triage_returns_json_result_and_markdown(self) -> None:
        diff = FIXTURE.read_bytes()
        status, _, body = self.request("/api/triage", method="POST", body=json.dumps({"diff": diff.decode(), "reviewer_focus": "security"}).encode())
        result = json.loads(body)

        self.assertEqual(status, 200)
        self.assertEqual(result["input_status"], "ok")
        self.assertEqual(result["review_order"][0]["files"][0], "src/api/routes.py")
        self.assertIn("# PR Review Triage Report", result["markdown"])
        self.assertIn("**Status:** `ok`", result["markdown"])

    def test_malformed_json_and_missing_diff_return_clear_400_errors(self) -> None:
        malformed_status, _, malformed_body = self.request("/api/triage", method="POST", body=b"{not json")
        missing_status, _, missing_body = self.request("/api/triage", method="POST", body=b"{}")

        self.assertEqual(malformed_status, 400)
        self.assertEqual(json.loads(malformed_body)["error"], "invalid_json")
        self.assertEqual(missing_status, 400)
        self.assertEqual(json.loads(missing_body)["error"], "missing_diff")

    def test_oversized_input_is_rejected_before_triage(self) -> None:
        oversized = json.dumps({"diff": "x" * MAX_REQUEST_BYTES}).encode()
        status, _, body = self.request("/api/triage", method="POST", body=oversized)

        self.assertEqual(status, 413)
        error = json.loads(body)
        self.assertEqual(error["error"], "request_too_large")
        self.assertIn(str(MAX_REQUEST_BYTES), error["message"])


if __name__ == "__main__":
    unittest.main()
