"""Room storage (local + bucket fallback) and the restyle feedback endpoint. No network: the bucket is faked.

Run: python -m unittest tests.test_rooms_storage   (from backend/)
"""
import asyncio
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException, UploadFile
from PIL import Image
from pydantic import ValidationError

from app.api.v1 import rooms
from app.services.three_d import storage

ROOM = "a" * 32
JOB = "b" * 12


def jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (180, 160, 140)).save(buf, "JPEG")
    return buf.getvalue()


class StorageCase(unittest.TestCase):
    """Local folder in a temp dir, plus an in-memory bucket behind storage._upload / storage._download."""

    bucket_on = True

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "rooms"
        self.objects = {}
        patches = [mock.patch.object(storage, "ROOT", self.root),
                   mock.patch.object(storage, "BUCKET", "test-bucket" if self.bucket_on else ""),
                   mock.patch.object(storage, "_upload", lambda r, n, d: self.objects.__setitem__(f"{r}/{n}", d)),
                   mock.patch.object(storage, "_download", lambda r, n: self.objects.get(f"{r}/{n}"))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class BucketStorageTest(StorageCase):
    def test_save_writes_locally_and_to_bucket(self):
        storage.save(ROOM, "photo.jpg", b"jpg-bytes")
        self.assertEqual((self.root / ROOM / "photo.jpg").read_bytes(), b"jpg-bytes")
        self.assertEqual(self.objects[f"{ROOM}/photo.jpg"], b"jpg-bytes")

    def test_files_come_back_from_bucket_after_restart(self):
        storage.save(ROOM, "photo.jpg", b"p")
        storage.save(ROOM, "scene.json", "{}")
        storage.save(ROOM, f"render_{JOB}.png", b"r")
        for f in (self.root / ROOM).iterdir():  # a new Cloud Run instance: empty disk
            f.unlink()
        self.assertEqual(storage.room_file(ROOM, f"render_{JOB}.png").read_bytes(), b"r")
        self.assertIsNotNone(storage.room_dir(ROOM))  # photo + scene restored for a new restyle
        self.assertIsNone(storage.room_file(ROOM, "nope.png"))

    def test_bucket_failure_does_not_fail_the_write(self):
        def boom(*_):
            raise RuntimeError("bucket down")

        with mock.patch.object(storage, "_upload", boom), self.assertLogs(storage.log, "ERROR"):
            self.assertEqual(storage.save(ROOM, "photo.jpg", b"p").read_bytes(), b"p")

    def test_bad_names_are_rejected(self):
        with self.assertRaises(ValueError):
            storage.save(ROOM, "../etc.png", b"x")
        self.assertIsNone(storage.room_file(ROOM, "../../secret.json"))
        self.assertIsNone(storage.room_dir("not-a-room"))

    def test_create_room_saves_photo_and_scene(self):
        upload = UploadFile(file=io.BytesIO(jpeg()), filename="room.jpg")
        room_id = asyncio.run(
            rooms.create_room(photo=upload, pitch_deg=None, room_width_cm=None, room_depth_cm=None)
        )["room_id"]
        self.assertIn(f"{room_id}/photo.jpg", self.objects)
        self.assertIn(f"{room_id}/scene.json", self.objects)

    def test_feedback_is_saved_for_an_existing_render(self):
        storage.save(ROOM, f"render_{JOB}.png", b"r")
        body = rooms.FeedbackIn(verdict="bad", issues=["floating", "removed_existing", "floating"], note="  bed vanished ")
        self.assertEqual(rooms.create_feedback(ROOM, JOB, body), {"ok": True})
        saved = json.loads(self.objects[f"{ROOM}/feedback_{JOB}.json"])
        self.assertEqual(saved["verdict"], "bad")
        self.assertEqual(saved["issues"], ["floating", "removed_existing"])
        self.assertEqual(saved["note"], "bed vanished")
        self.assertEqual(saved["job_id"], JOB)

    def test_feedback_needs_a_real_render(self):
        good = rooms.FeedbackIn(verdict="good")
        for room_id, job_id in ((ROOM, JOB), (ROOM, "XYZ"), ("nope", JOB)):
            with self.assertRaises(HTTPException) as ctx:
                rooms.create_feedback(room_id, job_id, good)
            self.assertEqual(ctx.exception.status_code, 404)

    def test_feedback_body_is_validated(self):
        with self.assertRaises(ValidationError):
            rooms.FeedbackIn(verdict="meh")
        with self.assertRaises(ValidationError):
            rooms.FeedbackIn(verdict="bad", issues=["ugly"])
        with self.assertRaises(ValidationError):
            rooms.FeedbackIn(verdict="bad", note="x" * 501)

    def test_json_files_are_not_served(self):
        storage.save(ROOM, f"feedback_{JOB}.json", "{}")
        with self.assertRaises(HTTPException) as ctx:
            rooms.get_room_file(ROOM, f"feedback_{JOB}.json")
        self.assertEqual(ctx.exception.status_code, 404)


class TraceTest(StorageCase):
    def test_a_failed_run_still_leaves_its_trace(self):
        from app.services.three_d import pipeline

        storage.save(ROOM, "photo.jpg", jpeg())
        storage.save(ROOM, "scene.json", json.dumps({"pitch_deg": 10, "source": "defaults", "width": 64, "height": 48,
                                                     "fov_deg": 70, "camera_height_m": 1.4}))
        with mock.patch.object(pipeline, "Camera"), \
                mock.patch.object(pipeline, "design", side_effect=RuntimeError("Vertex quota")):
            with self.assertRaises(RuntimeError):
                pipeline.run(ROOM, JOB, "cozy bedroom", [{"id": "p1"}])
        trace = json.loads(self.objects[f"{ROOM}/trace_{JOB}.json"])
        self.assertEqual(trace["status"], "error")
        self.assertIn("Vertex quota", trace["error"])
        self.assertEqual(trace["brief"], "cozy bedroom")


class LocalOnlyStorageTest(StorageCase):
    bucket_on = False

    def test_without_bucket_nothing_is_uploaded(self):
        storage.save(ROOM, "photo.jpg", b"p")
        self.assertEqual(self.objects, {})
        (self.root / ROOM / "photo.jpg").unlink()
        self.assertIsNone(storage.room_file(ROOM, "photo.jpg"))


if __name__ == "__main__":
    unittest.main()
