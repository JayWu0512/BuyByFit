"""Design reviewer client: config gating, reply parsing, and failing soft. No network (requests.post is faked).

Run: python -m unittest tests.test_reviewer   (from backend/)
"""
import io
import json
import os
import unittest
from unittest import mock

from PIL import Image

from app.services.three_d import reviewer

GOOD = {"overall": 7, "scores": {"scale": 4, "layout": 3, "focal_point": 4, "lighting": 2, "palette": 4,
                                 "restraint": 5, "cohesion": 4},
        "issues": ["Flat overhead light only", "Rug too small"], "fixes": ["Add two lamps", "Size up the rug"],
        "verdict": "Good bones, needs layered light."}


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1600, 1200), (200, 190, 180)).save(buf, "PNG")
    return buf.getvalue()


def reply(content: str, status: int = 200):
    r = mock.Mock(ok=status == 200, status_code=status, text=content)
    r.json.return_value = {"choices": [{"message": {"content": content}}]}
    return r


ENV = {"TASTE_REVIEWER_MODEL": "tinker://run/sampler_weights/00040", "TINKER_API_KEY": "tml-test"}


class ReviewerTest(unittest.TestCase):
    def test_not_configured_skips_without_calling(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(reviewer.requests, "post") as post:
            self.assertIsNone(reviewer.review_render(png()))
            post.assert_not_called()

    def test_good_reply_is_parsed(self):
        with mock.patch.dict(os.environ, ENV), \
                mock.patch.object(reviewer.requests, "post", return_value=reply(json.dumps(GOOD))) as post:
            out = reviewer.review_render(png())
        self.assertEqual(out["overall"], 7)
        self.assertEqual(out["scores"]["lighting"], 2)
        self.assertEqual(out["fixes"], ["Add two lamps", "Size up the rug"])
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["model"], ENV["TASTE_REVIEWER_MODEL"])
        self.assertEqual(body["messages"][0]["content"][1]["text"], reviewer.REVIEW_PROMPT)
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer tml-test")

    def test_json_inside_text_and_bad_fields_are_cleaned(self):
        messy = "Sure! " + json.dumps({**GOOD, "overall": "8", "scores": {"scale": 9, "layout": "3"},
                                        "issues": ["a", "", "b", "c", "d"]})
        with mock.patch.dict(os.environ, ENV), mock.patch.object(reviewer.requests, "post", return_value=reply(messy)):
            out = reviewer.review_render(png())
        self.assertEqual(out["overall"], 8)
        self.assertEqual(out["scores"], {"layout": 3})       # 9 is out of range, dropped
        self.assertEqual(out["issues"], ["a", "b", "c"])       # empties dropped, max 3

    def test_failures_return_none(self):
        cases = [reply("not json"), reply(json.dumps({**GOOD, "overall": 0})), reply("oops", status=500)]
        for r in cases:
            with mock.patch.dict(os.environ, ENV), mock.patch.object(reviewer.requests, "post", return_value=r):
                self.assertIsNone(reviewer.review_render(png()))
        with mock.patch.dict(os.environ, ENV), \
                mock.patch.object(reviewer.requests, "post", side_effect=reviewer.requests.Timeout()):
            self.assertIsNone(reviewer.review_render(png()))


if __name__ == "__main__":
    unittest.main()
