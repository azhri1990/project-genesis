import unittest
from unittest.mock import patch

from jarvis_server import app


class JarvisApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True)

    def setUp(self):
        self.client = app.test_client()

    @patch("jarvis_server.get_temperature", return_value=None)
    def test_missing_query_is_rejected(self, _temperature):
        response = self.client.post("/jarvis", json={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Missing query")

    @patch("jarvis_server.speak")
    @patch("jarvis_server.execute_command", return_value=("ok", 0))
    @patch("jarvis_server.get_temperature", return_value=36.0)
    def test_direct_command_uses_allowlisted_argv(self, _temperature, execute, _speak):
        response = self.client.post("/jarvis", json={"query": "list files"})
        self.assertEqual(response.status_code, 200)
        execute.assert_called_once_with(("ls", "-la"))
        self.assertEqual(response.get_json()["mode"], "direct")

    @patch("jarvis_server.speak")
    @patch("jarvis_server.get_temperature", return_value=None)
    def test_thermal_guard_aborts(self, _temperature, _speak):
        with patch("jarvis_server.TEMP_CRITICAL", 48.0), patch("jarvis_server.get_temperature", return_value=49.0):
            response = self.client.post("/jarvis", json={"query": "list files"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["status"], "aborted")

    @patch("jarvis_server.speak")
    @patch("jarvis_server.shutil.which", return_value="/usr/bin/tgpt")
    @patch("jarvis_server.get_temperature", return_value=None)
    @patch("jarvis_server.subprocess.run")
    def test_ai_receives_query_as_one_argument(self, run, _temperature, _which, _speak):
        run.return_value = type("Result", (), {"returncode": 0, "stdout": "answer", "stderr": ""})()
        response = self.client.post("/jarvis", json={"query": "hello; echo unsafe"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(run.call_args.args[0], ["tgpt", "hello; echo unsafe"])
        self.assertNotIn("shell", run.call_args.kwargs)

    @patch("jarvis_server.get_temperature", return_value=None)
    def test_health_reports_unknown_thermal_state(self, _temperature):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["thermal_guard"], "unknown")


if __name__ == "__main__":
    unittest.main()
