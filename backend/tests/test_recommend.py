"""Contract-level tests for semantic recommendation result shaping."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.logic.recommend import recommend
from app.services.product.catalog_import import _as_text_array


class RecommendationTests(unittest.TestCase):
    def test_catalog_import_normalizes_json_and_legacy_scalar_lists(self) -> None:
        self.assertEqual(_as_text_array('["Chair", "Lounge"]'), ["Chair", "Lounge"])
        self.assertEqual(_as_text_array("Modern"), ["Modern"])
        self.assertEqual(_as_text_array(None), [])

    def test_recommend_uses_embedding_candidates_and_preserves_product_metadata(self) -> None:
        candidate = {
            "id": "abo:chair-1",
            "title": "Walnut Reading Chair",
            "brand": "North House",
            "product_type": "CHAIR",
            "price": None,
            "currency": None,
            "url": "https://example.com/chair-1",
            "image_urls": ["https://example.com/chair-1.jpg"],
            "model_3d_url": "https://example.com/chair-1.glb",
            "ar_model_url": "https://example.com/chair-1.usdz",
            "width_cm": 72,
            "depth_cm": 78,
            "height_cm": 83,
            "description": "A warm walnut chair for a quiet reading corner.",
            "material": "Walnut and linen",
            "color": "Brown",
            "style": [],
            "vibe_tags": ["warm", "quiet"],
            "caption": "Walnut Reading Chair in a reading room",
            "distance": 0.12,
        }

        with patch("app.services.logic.recommend.embed_query", return_value=[0.1, 0.2]) as embed_query, patch(
            "app.services.logic.recommend.similarity_search", return_value=[candidate]
        ) as similarity_search:
            results = recommend("a warm, quiet reading room", {}, limit=12)

        embed_query.assert_called_once_with("a warm, quiet reading room")
        similarity_search.assert_called_once_with([0.1, 0.2], limit=50)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["product_url"], candidate["url"])
        self.assertEqual(results[0]["image_urls"], candidate["image_urls"])
        self.assertEqual(results[0]["description"], candidate["description"])
        self.assertEqual(results[0]["material"], candidate["material"])
        self.assertEqual(results[0]["model_3d_url"], candidate["model_3d_url"])
        self.assertEqual(results[0]["ar_model_url"], candidate["ar_model_url"])
        self.assertGreater(results[0]["match_score"], 80)

    def test_recommend_applies_dimension_filters_after_vector_ranking(self) -> None:
        candidates = [
            {
                "id": "too-wide",
                "title": "Wide Sofa",
                "product_type": "SOFA",
                "width_cm": 240,
                "depth_cm": 95,
                "image_urls": [],
                "vibe_tags": [],
                "distance": 0.05,
            },
            {
                "id": "fits",
                "title": "Compact Sofa",
                "product_type": "SOFA",
                "width_cm": 160,
                "depth_cm": 85,
                "image_urls": [],
                "vibe_tags": [],
                "distance": 0.18,
            },
        ]

        with patch("app.services.logic.recommend.embed_query", return_value=[0.1]), patch(
            "app.services.logic.recommend.similarity_search", return_value=candidates
        ):
            results = recommend("soft Scandinavian sofa", {"max_width_cm": 180}, limit=12)

        self.assertEqual([product["id"] for product in results], ["fits"])


if __name__ == "__main__":
    unittest.main()
