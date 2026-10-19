from django.test import TestCase

from backoffice.ops import ops_snapshot


class OpsSnapshotTests(TestCase):
    def test_snapshot_includes_operational_health_summary(self):
        snapshot = ops_snapshot(days=30)

        self.assertIn("seller_health", snapshot)
        self.assertIn("pending_sellers", snapshot["seller_health"])
        self.assertIn("approved", snapshot["seller_health"])
        self.assertIn("review_queue", snapshot["attention"])
