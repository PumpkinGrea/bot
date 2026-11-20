import unittest

from sv_cr_chart import summarize


def snapshot():
    return {"datasets": {"rankings": {
        "ranking_period_id": 17,
        "rankings": {
            str(23 + i): {
                "display_ranking": {"ranking_period_id": 17},
                "ranking": [{"user": {"class_rating": {
                    "rating": value, "max_rating": 9999,
                }}} for value in (1900 + i * 10, 2000, 2100)],
            } for i in range(7)
        },
    }}}


class CRStatisticsTests(unittest.TestCase):
    def test_website_baseline_and_inclusive_counts(self):
        rows, baseline, total = summarize(snapshot())
        self.assertEqual(baseline, 1960)
        self.assertEqual([r["count"] for r in rows], [2] * 6 + [3])
        self.assertEqual(total, 15)
        self.assertAlmostEqual(sum(r["pct"] for r in rows), 100)
        self.assertEqual(rows[0]["high"], 2100)  # current CR, not personal best

    def test_tied_entries_are_counted(self):
        data = snapshot()
        board = data["datasets"]["rankings"]["rankings"]["23"]
        board["ranking"].append(board["ranking"][-1])
        rows, _, total = summarize(data)
        self.assertEqual(rows[0]["count"], 3)
        self.assertEqual(total, 16)

    def test_mixed_seasons_are_rejected(self):
        data = snapshot()
        data["datasets"]["rankings"]["rankings"]["23"]["display_ranking"]["ranking_period_id"] = 16
        with self.assertRaises(ValueError):
            summarize(data)

    def test_empty_board_is_rejected(self):
        data = snapshot()
        data["datasets"]["rankings"]["rankings"]["23"]["ranking"] = []
        with self.assertRaises(ValueError):
            summarize(data)


if __name__ == "__main__":
    unittest.main()
