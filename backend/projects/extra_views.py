"""看板增强视图：模板库、燃尽图、只读分享链接（独立模块，避免改动主 views 文件尾部）"""
import time
import uuid
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.db.models import F
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import notify  # noqa: F401  (保留扩展点)
from core.utils import get_client_ip
from core.validators import as_int
from projects.models import Board, BoardShareLink, Project, TaskCard
from projects.serializers import ProjectSerializer
from projects.views import _can_access, _log_activity

# #31：公开看板默认 7 天过期；按 IP 限流（免登录接口，不能靠登录态节流）
SHARE_DEFAULT_DAYS = 7
SHARE_PUBLIC_MAX_PER_MINUTE = 60
# 282：访问口令最短长度、错误阈值与锁定时长
SHARE_PASSWORD_MIN_LEN = 4
SHARE_FAIL_LIMIT = 3
SHARE_LOCK_SECONDS = 600
# 口令校验通过后发放的访问票据有效期（秒）
SHARE_PASS_TTL = 3600


# ============ 看板模板库 ============

BOARD_TEMPLATES = [
    {
        "key": "agile",
        "name": "敏捷开发",
        "description": "待办 / 进行中 / 待验收 / 完成，适合迭代冲刺",
        "columns": ["待办", "进行中", "待验收", "完成"],
        "sample": [
            ("梳理本迭代需求", "todo", "medium"),
            ("设计评审与排期", "doing", "high"),
            ("修复遗留缺陷", "todo", "low"),
        ],
    },
    {
        "key": "content",
        "name": "内容日历",
        "description": "选题 / 撰稿 / 审核 / 发布，适合内容团队",
        "columns": ["选题", "撰稿中", "待审核", "已发布"],
        "sample": [
            ("本周选题会", "todo", "medium"),
            ("撰写深度长文", "doing", "high"),
        ],
    },
    {
        "key": "simple",
        "name": "项目管理",
        "description": "待办 / 进行中 / 已完成，轻量三列",
        "columns": ["待办", "进行中", "已完成"],
        "sample": [("Kickoff 会议", "todo", "high")],
    },
    {
        "key": "bugfix",
        "name": "缺陷修复",
        "description": "待处理 / 修复中 / 待验证 / 已关闭",
        "columns": ["待处理", "修复中", "待验证", "已关闭"],
        "sample": [("复现并定位线上问题", "doing", "urgent")],
    },
]


class BoardTemplateListView(APIView):
    """列出预置看板模板"""

    def get(self, request):
        return Response({"list": BOARD_TEMPLATES, "total": len(BOARD_TEMPLATES)})


class ProjectFromTemplateView(APIView):
    """从模板一键创建项目（三列+样例卡）"""

    def post(self, request):
        key = request.data.get("key")
        tpl = next((t for t in BOARD_TEMPLATES if t["key"] == key), None)
        if not tpl:
            return Response({"message": "模板不存在"}, status=404)
        name = (request.data.get("name") or tpl["name"]).strip()
        project = Project.objects.create(
            name=name, description=tpl["description"], color=request.data.get("color", "#0ea5e9"), owner=request.user
        )
        project.members.add(request.user)
        for i, col in enumerate(tpl["columns"]):
            board = Board.objects.create(project=project, name=col, sort_order=i)
            if i == 0:
                for title, status_v, prio in tpl["sample"]:
                    TaskCard.objects.create(
                        board=board, title=title, status="todo", priority=prio, created_by=request.user
                    )
        _log_activity(project, request.user, "从模板创建项目", tpl["name"])
        return Response(ProjectSerializer(project).data, status=201)


# ============ 燃尽图 ============

class ProjectBurndownView(APIView):
    """燃尽图：随时间推移剩余故事点（重建自卡片创建/完成时间）"""

    def get(self, request, project_id):
        from django.utils import timezone

        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        cards = list(TaskCard.objects.filter(board__project=project))
        if not cards:
            return Response({"dates": [], "remaining": [], "ideal": [], "total": 0})
        start = min(c.created_at for c in cards).date()
        end = timezone.now().date()
        if start >= end:
            end = start + timedelta(days=1)
        days = []
        cur = start
        while cur <= end:
            days.append(cur)
            cur += timedelta(days=1)
        if len(days) > 60:
            days = days[-60:]
        total_points = sum(c.story_points or 1 for c in cards) or len(cards)
        remaining, ideal = [], []
        n = len(days)
        for i, d in enumerate(days):
            rem = 0
            for c in cards:
                if c.created_at.date() > d:
                    continue
                if c.completed_at and c.completed_at.date() <= d:
                    continue
                rem += c.story_points or 1
            remaining.append(rem)
            ideal.append(round(total_points * (n - 1 - i) / max(n - 1, 1), 1))
        return Response({
            "dates": [str(d) for d in days],
            "remaining": remaining,
            "ideal": ideal,
            "total": total_points,
        })


# ============ 看板只读分享 ============

class BoardShareCreateView(APIView):
    """为项目生成只读分享链接（可选访问口令）"""

    def post(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        if project.owner_id != request.user.id:
            return Response({"message": "仅项目创建者可生成分享链接"}, status=403)
        # #31：链接必须有默认有效期（7 天），不能撤销前长期可读
        days = as_int(request.data.get("expires_in_days"), default=SHARE_DEFAULT_DAYS,
                      field="expires_in_days", minimum=1, maximum=30)
        # 282：可选访问口令，只存哈希；公开视图读取前必须校验
        raw_pwd = str(request.data.get("password") or "")
        if raw_pwd and len(raw_pwd) < SHARE_PASSWORD_MIN_LEN:
            return Response({"message": f"访问口令至少 {SHARE_PASSWORD_MIN_LEN} 位"}, status=400)
        link = BoardShareLink.objects.create(
            project=project, token=BoardShareLink.make_token(), created_by=request.user,
            expire_at=timezone.now() + timedelta(days=days),
            password_hash=make_password(raw_pwd) if raw_pwd else "",
        )
        return Response({
            "token": link.token, "url": f"/share/board/{link.token}/",
            "created_at": link.created_at, "expire_at": link.expire_at,
            "has_password": bool(link.password_hash),
        }, status=201)


class BoardShareRevokeView(APIView):
    """撤销分享链接"""

    def delete(self, request, project_id, token):
        link = BoardShareLink.objects.filter(token=token, project_id=project_id, created_by=request.user).first()
        if not link:
            return Response({"message": "链接不存在"}, status=404)
        link.is_revoked = True
        link.save(update_fields=["is_revoked"])
        return Response({"message": "链接已撤销"})


def _public_rate_limited(request) -> bool:
    """#31：匿名公开接口按客户端 IP 每分钟限流（cache 计数，跨进程失效不外抛）。"""
    ip = get_client_ip(request) or "unknown"
    bucket = f"board_share_rl:{ip}:{int(time.time()) // 60}"
    try:
        try:
            hits = cache.incr(bucket)
        except ValueError:  # 键不存在或后端不支持 incr
            cache.set(bucket, 1, 70)
            hits = 1
        return hits > SHARE_PUBLIC_MAX_PER_MINUTE
    except Exception:  # cache 不可用时放行，不阻断公开看板
        return False


def _share_lock_remaining(request) -> int:
    """282：当前 IP 的口令锁定剩余秒数（0 表示未锁定）"""
    ip = get_client_ip(request) or "unknown"
    try:
        until = cache.get(f"board_share_lock:{ip}")
    except Exception:
        return 0
    return max(int(until - time.time()), 0) if until else 0


def _share_record_failure(request) -> bool:
    """282：记录一次口令错误；同 IP 累计 3 次即锁 10 分钟，返回是否已锁定"""
    ip = get_client_ip(request) or "unknown"
    fail_key = f"board_share_fail:{ip}"
    try:
        try:
            hits = cache.incr(fail_key)
        except ValueError:
            cache.set(fail_key, 1, SHARE_LOCK_SECONDS)
            hits = 1
        if hits >= SHARE_FAIL_LIMIT:
            cache.set(f"board_share_lock:{ip}", int(time.time()) + SHARE_LOCK_SECONDS, SHARE_LOCK_SECONDS)
            cache.delete(fail_key)
            return True
    except Exception:
        return False
    return False


def _share_pass_key(token, access_key) -> str:
    return f"board_share_pass:{token}:{access_key}"


def _share_access_granted(request, token) -> bool:
    """282：公开视图读取前校验口令票据（access_key 查询参数或 X-Share-Key 头）"""
    access_key = (request.query_params.get("access_key")
                  or request.headers.get("X-Share-Key") or "").strip()
    if not access_key:
        return False
    try:
        return bool(cache.get(_share_pass_key(token, access_key)))
    except Exception:
        return False


class BoardShareVerifyView(APIView):
    """282：公开看板口令校验，成功返回短期访问票据（access_key）"""

    permission_classes = [AllowAny]

    def post(self, request, token):
        if _public_rate_limited(request):
            return Response({"message": "访问过于频繁，请稍后再试"}, status=429)
        remain = _share_lock_remaining(request)
        if remain:
            return Response({"message": f"口令错误次数过多，请 {remain} 秒后再试",
                             "locked": True, "retry_after": remain}, status=429)
        link = BoardShareLink.objects.filter(token=token).first()
        if not link or link.is_expired:
            return Response({"message": "分享链接不存在或已失效"}, status=404)
        if not link.password_hash:
            return Response({"message": "该分享无需口令", "ok": True, "need_password": False})
        password = str(request.data.get("password") or "")
        if not password:
            return Response({"message": "请输入访问口令", "need_password": True}, status=400)
        if not check_password(password, link.password_hash):
            if _share_record_failure(request):
                return Response({"message": f"口令错误次数过多，请 {SHARE_LOCK_SECONDS} 秒后再试",
                                 "locked": True, "retry_after": SHARE_LOCK_SECONDS}, status=429)
            return Response({"message": "口令不正确", "need_password": True}, status=403)
        access_key = uuid.uuid4().hex
        try:
            cache.set(_share_pass_key(token, access_key), 1, SHARE_PASS_TTL)
        except Exception:
            pass
        return Response({"ok": True, "access_key": access_key, "expires_in": SHARE_PASS_TTL})


class BoardSharePublicView(APIView):
    """公开只读看板（免登录；设了口令需先调用 verify 换 access_key）"""

    permission_classes = [AllowAny]

    def get(self, request, token):
        if _public_rate_limited(request):
            return Response({"message": "访问过于频繁，请稍后再试"}, status=429)
        link = BoardShareLink.objects.filter(token=token).first()
        if not link or link.is_expired:
            return Response({"message": "分享链接不存在或已失效"}, status=404)
        # 282：设了口令的链接必须先校验通过才返回数据
        if link.password_hash:
            remain = _share_lock_remaining(request)
            if remain:
                return Response({"message": f"口令错误次数过多，请 {remain} 秒后再试",
                                 "locked": True, "retry_after": remain}, status=429)
            if not _share_access_granted(request, token):
                return Response({"message": "该看板已设置访问口令，请先校验口令",
                                 "need_password": True}, status=401)
        # #59：浏览计数用 F() 原子自增，避免 read-modify-write 丢更新
        BoardShareLink.objects.filter(pk=link.pk).update(view_count=F("view_count") + 1)
        project = link.project
        # #31：免登录只输出「列名 + 卡片标题/状态」，不再暴露描述、负责人、
        # 截止时间等可拼出人员画像的字段。
        boards = []
        for b in project.boards.all().only("id", "name", "sort_order"):
            cards = TaskCard.objects.filter(board=b).only("id", "title", "status").order_by("sort_order", "id")
            boards.append({
                "id": b.id, "name": b.name, "sort_order": b.sort_order,
                "cards": [{"id": c.id, "title": c.title, "status": c.status} for c in cards],
            })
        return Response({
            "project": {"name": project.name, "color": project.color},
            "boards": boards,
            "expire_at": link.expire_at,
        })
