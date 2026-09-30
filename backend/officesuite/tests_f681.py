# -*- coding: utf-8 -*-
"""F681–F692 办公套件新增能力回归测试。

运行：python manage.py test officesuite.tests_f681
"""
import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

User = get_user_model()


class OfficeF681F692Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="f6tester", password="F6test#2026")
        cls.mate = User.objects.create_user(username="f6mate", password="F6test#2026")

    def setUp(self):
        self.c = Client()
        self.token = self.login("f6tester")

    def login(self, username):
        # 直接签发 JWT（accounts 的 TwoFactorSecret 缺迁移，走登录接口会在测试库 500）
        from rest_framework_simplejwt.tokens import RefreshToken
        user = User.objects.get(username=username)
        return str(RefreshToken.for_user(user).access_token)

    def api(self, method, path, data=None, token=None):
        h = {"HTTP_AUTHORIZATION": f"Bearer {token or self.token}"}
        if method == "get":
            return self.c.get(path, data or None, **h)
        if method == "post":
            return self.c.post(path, data=json.dumps(data or {}),
                               content_type="application/json", **h)
        raise AssertionError(method)

    def js(self, resp):
        return json.loads(resp.content.decode("utf-8"))

    # ---------- F681 日程冲突检测 ----------
    def test_calendar_conflict(self):
        base = {"title": "评审会", "kind": "meeting",
                "start_at": "2030-03-04 10:00", "end_at": "2030-03-04 11:00"}
        r = self.api("post", "/api/officesuite/calendar/event/create/", base)
        self.assertEqual(r.status_code, 200, r.content[:300])
        d = self.js(r)["data"]
        self.assertFalse(d["has_conflict"])

        # 重叠创建 → 返回提示但仍然创建（仅提示不阻断）
        r = self.api("post", "/api/officesuite/calendar/event/create/",
                     dict(base, title="临时对齐"))
        d = self.js(r)["data"]
        self.assertTrue(d["has_conflict"])
        self.assertGreaterEqual(d["conflict_count"], 1)

        # 预检接口（不落库）
        r = self.api("post", "/api/officesuite/calendar/conflict-check/",
                     {"start_at": "2030-03-04 10:30", "end_at": "2030-03-04 10:45"})
        self.assertEqual(r.status_code, 200, r.content[:300])
        d = self.js(r)["data"]
        self.assertTrue(d["has_conflict"])
        self.assertGreaterEqual(d["conflict_count"], 1)

    # ---------- F682 会议时长模板 ----------
    def test_duration_templates(self):
        r = self.api("get", "/api/officesuite/meeting/duration-templates/")
        self.assertEqual(r.status_code, 200, r.content[:300])
        d = self.js(r)["data"]
        self.assertIn(15, d["quick_minutes"])
        self.assertIn(30, d["quick_minutes"])
        self.assertIn(60, d["quick_minutes"])

        # 建会议室 + duration_minutes 自动算结束时间
        r = self.api("post", "/api/officesuite/meeting/room/create/",
                     {"name": "松柏厅", "capacity": 8})
        room = self.js(r)["data"]["id"]
        r = self.api("post", "/api/officesuite/meeting/book/", {
            "room_id": room, "title": "短会", "start_at": "2030-03-05 09:00",
            "duration_minutes": 15,
        })
        self.assertEqual(r.status_code, 200, r.content[:300])
        d = self.js(r)["data"]
        self.assertEqual(d["duration_minutes"], 15)
        self.assertTrue(d["end_at"].startswith("2030-03-05T09:15"))

        # 同时段再订 → 400 冲突提示
        r = self.api("post", "/api/officesuite/meeting/book/", {
            "room_id": room, "title": "冲突", "start_at": "2030-03-05 09:10",
            "duration_minutes": 15,
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("冲突", self.js(r)["error"])

        # 资源冲突预检
        r = self.api("post", "/api/officesuite/calendar/conflict-check/", {
            "start_at": "2030-03-05 09:10", "end_at": "2030-03-05 09:20",
            "resource": f"room:{room}",
        })
        d = self.js(r)["data"]
        self.assertEqual(d["resource_conflict_count"], 1)

    # ---------- F686 车辆预约冲突提示 ----------
    def test_vehicle_conflict(self):
        r = self.api("post", "/api/officesuite/vehicle/create/",
                     {"plate": "京A·00001", "model_name": "测试车"})
        vid = self.js(r)["data"]["id"]
        r = self.api("post", "/api/officesuite/vehicle/book/", {
            "vehicle_id": vid, "use_at": "2030-04-01 09:00",
            "return_at": "2030-04-01 12:00", "destination": "机场"})
        self.assertEqual(r.status_code, 200, r.content[:300])
        r = self.api("post", "/api/officesuite/vehicle/book/", {
            "vehicle_id": vid, "use_at": "2030-04-01 10:00",
            "return_at": "2030-04-01 11:00", "destination": "客户处"})
        d = self.js(r)["data"]
        self.assertTrue(d["has_conflict"])
        self.assertEqual(d["conflict_count"], 1)

    # ---------- F683 值班换班申请 ----------
    def test_duty_swap_request_flow(self):
        r = self.api("post", "/api/officesuite/duty/schedule/create/", {"name": "十月排班"})
        sid = self.js(r)["data"]["id"]
        r = self.api("post", "/api/officesuite/duty/shift/add/", {
            "schedule_id": sid, "duty_date": "2030-05-06",
            "member_name": "f6tester", "shift_name": "白班"})
        shift_id = self.js(r)["data"]["id"]

        r = self.api("post", "/api/officesuite/duty/swap-request/create/",
                     {"shift_id": shift_id, "to_name": "f6mate", "note": "出差"})
        self.assertEqual(r.status_code, 200, r.content[:300])
        req = self.js(r)["data"]
        self.assertEqual(req["status"], "pending")

        r = self.api("get", "/api/officesuite/duty/swap-request/list/")
        d = self.js(r)["data"]
        self.assertEqual(d["count"], 1)
        self.assertEqual(d["pending_outgoing"], 1)

        # 发起人不能替对方确认
        r = self.api("post", f"/api/officesuite/duty/swap-request/{req['id']}/confirm/")
        self.assertEqual(r.status_code, 400)

        # 对方确认
        mate_token = self.login("f6mate")
        r = self.api("get", "/api/officesuite/duty/swap-request/list/",
                     token=mate_token)
        self.assertEqual(self.js(r)["data"]["pending_incoming"], 1)
        r = self.api("post", f"/api/officesuite/duty/swap-request/{req['id']}/confirm/",
                     {"action": "accept"}, token=mate_token)
        self.assertEqual(r.status_code, 200, r.content[:300])
        d = self.js(r)["data"]
        self.assertEqual(d["status"], "accepted")
        self.assertEqual(d["swapped_to"], "f6mate")

        # 记录可查
        r = self.api("get", "/api/officesuite/duty/swap-request/list/",
                     {"status": "accepted"})
        self.assertEqual(self.js(r)["data"]["count"], 1)

    # ---------- F684 工单满意度评分 ----------
    def test_ticket_rate(self):
        r = self.api("post", "/api/officesuite/ticket/create/",
                     {"title": "打印机不工作", "description": "卡纸"})
        tid = self.js(r)["data"]["id"]

        # 未关闭不能评分
        r = self.api("post", f"/api/officesuite/ticket/{tid}/rate/", {"rating": 5})
        self.assertEqual(r.status_code, 400)

        r = self.api("post", f"/api/officesuite/ticket/{tid}/resolve/",
                     {"solution": "更换硒鼓"})
        self.assertEqual(r.status_code, 200, r.content[:300])

        r = self.api("post", f"/api/officesuite/ticket/{tid}/rate/",
                     {"rating": 4, "comment": "响应很快"})
        self.assertEqual(r.status_code, 200, r.content[:300])
        d = self.js(r)["data"]
        self.assertEqual(d["rating"], 4)

        r = self.api("get", "/api/officesuite/ticket/stats/")
        d = self.js(r)["data"]
        self.assertEqual(d["rating_count"], 1)
        self.assertEqual(d["avg_rating"], 4)

        # 非法星级 → 400
        r = self.api("post", f"/api/officesuite/ticket/{tid}/rate/", {"rating": 9})
        self.assertEqual(r.status_code, 400)

    # ---------- F685 工单轮询自动分配 ----------
    def test_ticket_auto_assign(self):
        r = self.api("post", "/api/officesuite/ticket/create/", {"title": "账号锁定"})
        self.assertEqual(r.status_code, 200, r.content[:300])
        r = self.api("post", "/api/officesuite/ticket/auto-assign/",
                     {"members": ["f6mate", "f6tester"]})
        self.assertEqual(r.status_code, 200, r.content[:300])
        d = self.js(r)["data"]
        self.assertEqual(d["assigned"], 1)
        self.assertIn(d["items"][0]["assignee"], ["f6mate", "f6tester"])
        self.assertEqual(d["items"][0]["load_after"], 1)

        # 没有待分配工单 → 400
        r = self.api("post", "/api/officesuite/ticket/auto-assign/")
        self.assertEqual(r.status_code, 400)

    # ---------- F687 点赞 / 收藏 ----------
    def test_wiki_like_star(self):
        r = self.api("post", "/api/officesuite/wiki/create/", {"title": "部署手册"})
        wid = self.js(r)["data"]["id"]
        r = self.api("post", f"/api/officesuite/wiki/{wid}/like/")
        d = self.js(r)["data"]
        self.assertTrue(d["liked"])
        self.assertEqual(d["like_count"], 1)
        r = self.api("post", f"/api/officesuite/wiki/{wid}/like/")
        self.assertFalse(self.js(r)["data"]["liked"])

        r = self.api("post", f"/api/officesuite/wiki/{wid}/star/")
        self.assertTrue(self.js(r)["data"]["starred"])
        r = self.api("post", f"/api/officesuite/wiki/{wid}/")
        d = self.js(r)["data"]
        self.assertTrue(d["starred"])
        self.assertEqual(d["star_count"], 1)

    # ---------- F688 知识库目录树 ----------
    def test_wiki_tree(self):
        r = self.api("post", "/api/officesuite/wiki/create/", {"title": "根页"})
        root = self.js(r)["data"]["id"]
        r = self.api("post", "/api/officesuite/wiki/create/",
                     {"title": "子页", "parent_id": root})
        self.assertEqual(r.status_code, 200, r.content[:300])

        r = self.api("get", "/api/officesuite/wiki/tree/")
        d = self.js(r)["data"]
        self.assertGreaterEqual(d["page_count"], 2)
        self.assertEqual(d["root_count"], 1)
        node = d["tree"][0]
        self.assertEqual(node["path"], ["根页"])
        self.assertEqual(node["child_count"], 1)
        self.assertEqual(node["children"][0]["path"], ["根页", "子页"])
        self.assertEqual(node["children"][0]["depth"], 1)

    # ---------- F689 待办重复规则 ----------
    def test_todo_repeat(self):
        r = self.api("post", "/api/officesuite/todo/create/",
                     {"title": "每日站会", "repeat_rule": "daily",
                      "repeat_until": "2030-12-31", "important": True})
        self.assertEqual(r.status_code, 200, r.content[:300])
        parent_id = self.js(r)["data"]["id"]

        r = self.api("post", "/api/officesuite/todo/repeat-scan/")
        self.assertEqual(r.status_code, 200, r.content[:300])
        d = self.js(r)["data"]
        self.assertEqual(d["created"], 1)
        self.assertEqual(d["items"][0]["parent"], parent_id)

        # 幂等：同日再扫不重复生成
        r = self.api("post", "/api/officesuite/todo/repeat-scan/")
        self.assertEqual(self.js(r)["data"]["created"], 0)

        # 非法规则 → 400
        r = self.api("post", "/api/officesuite/todo/create/",
                     {"title": "坏规则", "repeat_rule": "hourly"})
        self.assertEqual(r.status_code, 400)

    # ---------- F690 待办四象限 ----------
    def test_todo_quadrant(self):
        self.api("post", "/api/officesuite/todo/create/",
                 {"title": "线上事故", "priority": "urgent", "important": True})
        self.api("post", "/api/officesuite/todo/create/",
                 {"title": "年度规划", "important": True})
        self.api("post", "/api/officesuite/todo/create/",
                 {"title": "顺手回复邮件"})
        r = self.api("get", "/api/officesuite/todo/quadrant/")
        self.assertEqual(r.status_code, 200, r.content[:300])
        d = self.js(r)["data"]
        counts = d["counts"]
        self.assertEqual(counts["q1"], 1)
        self.assertEqual(counts["q2"], 1)
        self.assertEqual(counts["q4"], 1)
        self.assertEqual(d["total"], 3)
        self.assertEqual(d["quadrants"][0]["items"][0]["title"], "线上事故")

    # ---------- F691 人员忙闲查询 ----------
    def test_free_busy(self):
        r = self.api("get", "/api/officesuite/calendar/free-busy/", {
            "date": "2030-06-03", "names": "f6tester"})
        self.assertEqual(r.status_code, 200, r.content[:300])
        d = self.js(r)["data"]
        person = d["people"][0]
        self.assertEqual(person["status"], "free")
        self.assertEqual(person["free_minutes"], d["work_window"]["minutes"])

        # 有日程 → 出现忙碌段
        self.api("post", "/api/officesuite/calendar/event/create/", {
            "title": "周会", "start_at": "2030-06-03 10:00",
            "end_at": "2030-06-03 11:00", "attendees": ["f6tester"]})
        r = self.api("get", "/api/officesuite/calendar/free-busy/", {
            "date": "2030-06-03", "names": "f6tester"})
        person = self.js(r)["data"]["people"][0]
        self.assertEqual(person["status"], "partial")
        self.assertEqual(person["busy_minutes"], 60)
        self.assertLess(person["free_minutes"], d["work_window"]["minutes"])
        self.assertTrue(any(f["start"] == "09:00" for f in person["free"]))

    # ---------- F692 行动项完成率周统计 ----------
    def test_minutes_action_stats(self):
        from django.utils import timezone
        r = self.api("post", "/api/officesuite/minutes/create/", {
            "title": "周例会", "content": "行动：完成部署\nTODO：补文档",
            "meeting_at": timezone.localtime().strftime("%Y-%m-%d %H:%M")})
        mid = self.js(r)["data"]["id"]

        r = self.api("get", f"/api/officesuite/minutes/{mid}/action-items/")
        d = self.js(r)["data"]
        self.assertEqual(d["count"], 2)
        self.assertEqual(d["rate"], 0.0)

        line_no = d["action_items"][0]["line_no"]
        r = self.api("post", f"/api/officesuite/minutes/{mid}/action-items/toggle/",
                     {"line_no": line_no})
        d = self.js(r)["data"]
        self.assertTrue(d["item"]["done"])
        self.assertEqual(d["rate"], 50.0)

        r = self.api("get", "/api/officesuite/minutes/action-items/stats/")
        d = self.js(r)["data"]
        self.assertEqual(d["total"], 2)
        self.assertEqual(d["done"], 1)
        self.assertEqual(d["rate"], 50.0)
        self.assertEqual(len(d["series"]), 8)
        self.assertTrue(any(s["total"] == 2 for s in d["series"]))
