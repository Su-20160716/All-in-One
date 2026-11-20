# -*- coding: utf-8 -*-
"""核心平台工具回归测试。"""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from core.platform import health_card

User = get_user_model()


class HealthCardTests(TestCase):
    """后端体检卡（/api/core/admin/health-card/）。"""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="healthadmin", password="Health#2026", is_staff=True,
        )

    def test_migration_probe_uses_real_column_names(self):
        """django_migrations 的列是 app/name/applied。

        历史实现查询 app_label/applied_at，SQLite 会报 no such column 并被
        except 静默吞掉，体检卡的迁移信息永远为空。
        """
        data = health_card(force=True)
        self.assertGreater(data["migration"]["count"], 0, "迁移数量探测失败")
        latest = data["migration"]["latest"]
        self.assertIsNotNone(latest, "最新迁移探测失败")
        self.assertTrue(latest["app"] and latest["name"] and latest["applied_at"])

    def test_endpoint_ok_for_admin(self):
        c = APIClient()
        c.force_authenticate(user=self.admin)
        r = c.get("/api/core/admin/health-card/?fresh=1")
        self.assertEqual(r.status_code, 200, r.content[:300])
        body = json.loads(r.content.decode())
        payload = body.get("data", body)
        self.assertIn("migration", payload)
        self.assertGreater(payload["migration"]["count"], 0)
