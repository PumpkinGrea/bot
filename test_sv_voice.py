import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sv_voice


class VoiceTests(unittest.TestCase):
    def test_id_mapping_uses_japanese_urls_and_preserves_order(self):
        index = {"sample": {
            "metadata": {"common": {"card_id": 123}},
            "voices": [
                {"url": "Audio/FILTERED/card/chunk2.mp3", "en_url": "Audio/EN/card/chunk2.mp3"},
                {"url": "Audio/FILTERED/card/chunk0.mp3"},
                {"url": "Audio/FILTERED/card/chunk2.mp3"},
                {"url": "https://other.example/a.mp3"},
            ],
        }}
        self.assertEqual(sv_voice._voice_paths(index, {"card_id": 999, "base_card_id": 123}), [
            "Audio/FILTERED/card/chunk2.mp3", "Audio/FILTERED/card/chunk0.mp3",
        ])
        self.assertEqual(sv_voice._voice_paths(index, {"card_id": 888}), [])

    def test_ambiguous_name_does_not_download_or_choose_a_card(self):
        cards = {str(i): {"common": {"card_id": i, "base_card_id": i, "name": name}}
                 for i, name in enumerate(["测试骑士", "测试法师"])}
        with patch.object(sv_voice, "_get_cards", return_value=(cards, {}, {})), \
                patch.object(sv_voice, "_session") as session:
            audio, message = sv_voice.query_card_voice("测试")
        self.assertIsNone(audio)
        self.assertIn("2 张", message)
        session.assert_not_called()

    def test_cached_set_skips_download_and_encoding(self):
        card = {"common": {"card_id": 123, "base_card_id": 123, "name": "测试骑士"}}
        paths = ["Audio/FILTERED/card/chunk0.mp3"]
        index = {"sample": {"metadata": {"common": {"card_id": 123}},
                            "voices": [{"url": paths[0]}]}}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sv_voice, "_CACHE", Path(directory)), \
                patch.object(sv_voice, "_get_cards", return_value=({"123": card}, {}, {})), \
                patch.object(sv_voice, "_session"), \
                patch.object(sv_voice, "_index", return_value=index), \
                patch.object(sv_voice, "_encode") as encode:
            digest = sv_voice.hashlib.sha256(json.dumps(paths).encode()).hexdigest()[:24]
            expected = b"\x02#!SILK_V3test"
            (Path(directory) / f"jp-{digest}.silk").write_bytes(expected)
            audio, message = sv_voice.query_card_voice("测试骑士")
            self.assertEqual(audio, expected)
            self.assertIn("日语", message)
            encode.assert_not_called()


if __name__ == "__main__":
    unittest.main()
