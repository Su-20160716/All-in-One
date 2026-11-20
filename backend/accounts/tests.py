"""注册接口：新增手机号 / 姓名 / 出生日期 / 地址字段的回归测试"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

User = get_user_model()


class RegisterProfileFieldTests(APITestCase):
    url = "/api/auth/register/"

    def _payload(self, **extra):
        data = {"username": "student01", "password": "test123456"}
        data.update(extra)
        return data

    def test_register_with_new_profile_fields(self):
        resp = self.client.post(
            self.url,
            self._payload(
                phone="13800138000",
                real_name="张三",
                birthday="2008-05-01",
                address="广东省 深圳市 南山区 科技园 1 号",
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        user = User.objects.get(username="student01")
        self.assertEqual(user.phone, "13800138000")
        self.assertEqual(user.real_name, "张三")
        self.assertEqual(user.birthday.isoformat(), "2008-05-01")
        self.assertEqual(user.address, "广东省 深圳市 南山区 科技园 1 号")
        self.assertEqual(resp.data["user"]["real_name"], "张三")
        self.assertEqual(resp.data["user"]["birthday"], "2008-05-01")

    def test_register_without_new_fields_still_works(self):
        """老客户端只传用户名 / 密码时仍可注册（字段均为选填）"""
        resp = self.client.post(self.url, self._payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertFalse(User.objects.get(username="student01").real_name)

    def test_register_rejects_invalid_phone(self):
        resp = self.client.post(self.url, self._payload(phone="12345"), format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("phone", resp.data["detail"])

    def test_register_rejects_future_birthday(self):
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        resp = self.client.post(self.url, self._payload(birthday=tomorrow), format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("birthday", resp.data["detail"])
