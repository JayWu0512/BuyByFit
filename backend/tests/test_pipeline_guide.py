"""Guide drawing must survive a degenerate placement box (it used to raise "x1 must be greater than or equal to x0").

Run: python -m unittest tests.test_pipeline_guide   (from backend/)
"""
import io
import unittest

from PIL import Image

from app.services.three_d.pipeline import guide_image


class GuideImageTest(unittest.TestCase):
    def test_inverted_and_empty_boxes_are_skipped(self):
        photo = Image.new("RGB", (640, 480), (200, 200, 200))
        items = [{"box": [100, 1000, 900, 1000]},   # zero width (a piece clamped against the right edge)
                 {"box": [100, 1000, 900, 980]},    # inverted: x0 > x1 (projected fully off the right side)
                 {"box": [200, 100, 600, 400]}]     # a normal box still gets drawn
        out = Image.open(io.BytesIO(guide_image(photo, items)))
        self.assertEqual(out.size, (640, 480))
        red = sum(1 for p in out.getdata() if p[0] > 200 and p[1] < 80 and p[2] < 80)
        self.assertGreater(red, 100)   # the valid box was drawn


class ExistingFurnitureTest(unittest.TestCase):
    """The user's furniture stays: new pieces may not stand on it, and the renderer is told to keep it."""

    CHAIR = {"label": "dining chair", "box_2d": [550, 150, 800, 300]}

    def test_a_piece_standing_where_a_chair_stands_is_blocked(self):
        from app.services.three_d.pipeline import _on_existing

        self.assertEqual(_on_existing([500, 160, 790, 290], [self.CHAIR]), "dining chair")
        self.assertIsNone(_on_existing([600, 120, 950, 330], [self.CHAIR]))   # in front of it (closer to camera)
        self.assertIsNone(_on_existing([500, 600, 790, 900], [self.CHAIR]))   # elsewhere
        self.assertIsNone(_on_existing([500, 160, 790, 290], []))

    def test_render_prompt_names_the_furniture_that_stays(self):
        from unittest import mock

        from app.services.three_d import pipeline

        items = [{"product": {"name": "Round table", "width_cm": 90, "depth_cm": 90, "height_cm": 75}, "box": [0, 0, 1, 1]}]
        with mock.patch.object(pipeline, "generate", return_value=b"png") as gen:
            pipeline.render(b"guide", items, [], [], "cozy", "3:4", "", ["dining chair", "pendant lamp"])
        prompt = gen.call_args.args[1][-1]
        self.assertIn("stays exactly where and as it is (dining chair, pendant lamp): never remove", prompt)
        self.assertNotIn("REPLACES", prompt)

    def test_render_prompt_states_an_explicit_swap(self):
        from unittest import mock

        from app.services.three_d import pipeline

        items = [{"product": {"name": "Round table", "width_cm": 90, "depth_cm": 90, "height_cm": 75}, "box": [0, 0, 1, 1], "pick": {"replaces": "dining table"}}]
        with mock.patch.object(pipeline, "generate", return_value=b"png") as gen:
            pipeline.render(b"guide", items, [], [], "cozy", "3:4", "", ["dining chair"])
        prompt = gen.call_args.args[1][-1]
        self.assertIn("Box 1 REPLACES the room's dining table", prompt)
        self.assertIn("other furniture stays exactly where and as it is (dining chair)", prompt)


class StylingIdeasTest(unittest.TestCase):
    """The styling ideas shown to the user come from the fine-tuned expert, never as product recommendations."""

    def test_ideas_that_ask_to_buy_or_replace_are_dropped(self):
        from unittest import mock

        from app.services.three_d import reviewer

        fixes = ["Warm the lighting with 2700K bulbs", "Buy a new rug", "Replace the sofa with a sectional",
                 "Select a more uniform set of seating",
                 "Group the wall frames tighter above the desk"]
        with mock.patch.object(reviewer, "review_render", return_value={"overall": 7, "fixes": fixes}) as rr:
            ideas = reviewer.style_suggestions(b"png")
        self.assertEqual(ideas, ["Warm the lighting with 2700K bulbs", "Group the wall frames tighter above the desk"])
        self.assertIn("The furniture is final", rr.call_args.args[1])
        self.assertIn("STYLE only", rr.call_args.args[1])

    def test_room_notes_brief_the_designer(self):
        from unittest import mock

        from app.services.three_d import pipeline, reviewer

        with mock.patch.object(reviewer, "review_render", return_value={
                "overall": 5, "issues": ["The saturated green walls fight the warm wood"],
                "fixes": ["Shift to a warm earthy palette", "Buy a new lamp from IKEA"]}):
            notes = reviewer.room_notes(b"photo")
        self.assertEqual(notes, ["The saturated green walls fight the warm wood", "Shift to a warm earthy palette"])
        with mock.patch.object(pipeline, "generate_json", return_value={}) as gj:
            pipeline.design(b"photo", "cozy", [], expert_notes=notes)
        prompt = gj.call_args.args[1][-1]
        self.assertIn("senior interior design expert reviewed this room", prompt)
        self.assertIn("- Shift to a warm earthy palette", prompt)
        with mock.patch.object(pipeline, "generate_json", return_value={}) as gj:
            pipeline.design(b"photo", "cozy", [])
        self.assertNotIn("design expert", gj.call_args.args[1][-1])

    def test_no_reviewer_means_no_ideas(self):
        from unittest import mock

        from app.services.three_d import reviewer

        with mock.patch.object(reviewer, "review_render", return_value=None):
            self.assertEqual(reviewer.style_suggestions(b"png"), [])
            self.assertEqual(reviewer.room_notes(b"photo"), [])


if __name__ == "__main__":
    unittest.main()
