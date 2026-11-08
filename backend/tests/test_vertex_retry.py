"""Rate-limit handling: a short 2-4 s jittered backoff in vertex.generate.
No network: urlopen is faked.

Run: python -m unittest tests.test_vertex_retry   (from backend/)
"""
import io
import json
import unittest
import urllib.error
from unittest import mock

from app.services.three_d import pipeline, vertex


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, "busy", {}, io.BytesIO(b'{"error": "RESOURCE_EXHAUSTED"}'))


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


OK = FakeResponse(json.dumps({"candidates": [{"content": {"parts": [{"text": "hello"}]}}]}).encode())


class BackoffTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(vertex, "_token_and_project", return_value=("tok", "proj"))
        p.start()
        self.addCleanup(p.stop)

    def test_backoff_is_short_and_capped(self):
        for attempt in range(8):
            w = vertex.backoff(attempt)
            self.assertGreaterEqual(w, 2.0)
            self.assertLessEqual(w, 4.0)                   # always 2-4 s (was a fixed 15 s)

    def test_retries_a_busy_model_then_succeeds(self):
        waits = []
        with mock.patch.object(vertex.urllib.request, "urlopen", side_effect=[http_error(429), http_error(503), OK]), \
                mock.patch.object(vertex.time, "sleep", side_effect=waits.append):
            self.assertEqual(vertex.generate("m", ["hi"]), "hello")
        self.assertEqual(len(waits), 2)
        self.assertLess(sum(waits), 10)                    # was 15 + 30 = 45 s

    def test_raises_rate_limited_after_the_retries(self):
        with mock.patch.object(vertex.urllib.request, "urlopen", side_effect=[http_error(429)] * 4), \
                mock.patch.object(vertex.time, "sleep"):
            with self.assertRaises(vertex.RateLimited):
                vertex.generate("m", ["hi"], retries=3)

    def test_other_errors_are_not_rate_limited(self):
        with mock.patch.object(vertex.urllib.request, "urlopen", side_effect=[http_error(400)]):
            with self.assertRaises(RuntimeError) as ctx:
                vertex.generate("m", ["hi"])
        self.assertNotIsInstance(ctx.exception, vertex.RateLimited)


class RenderFallbackTest(unittest.TestCase):
    ITEMS = [{"product": {"name": "Oak desk", "width_cm": 100, "depth_cm": 50, "height_cm": 75}, "box": [0, 0, 1, 1]}]

    def test_switches_to_the_fallback_image_model_when_rate_limited(self):
        calls = []

        def fake_generate(model, parts, **kw):
            calls.append(model)
            if model == pipeline.IMAGE_MODEL:
                raise vertex.RateLimited("busy")
            return b"png-from-fallback"

        with mock.patch.object(pipeline, "generate", side_effect=fake_generate):
            self.assertEqual(pipeline.render(b"guide", self.ITEMS, [], [], "cozy", "3:4"), b"png-from-fallback")
        self.assertEqual(calls, [pipeline.IMAGE_MODEL, pipeline.FALLBACK_IMAGE_MODEL])

    def test_no_fallback_when_the_main_model_works(self):
        with mock.patch.object(pipeline, "generate", return_value=b"png") as gen:
            self.assertEqual(pipeline.render(b"guide", self.ITEMS, [], [], "cozy", "3:4"), b"png")
        self.assertEqual(gen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
