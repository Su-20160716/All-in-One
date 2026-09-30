"""看板增强视图：模板库、燃尽图、只读分享链接（独立模块，避免改动主 views 文件尾部）"""
from datetime import timedelta

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import notify  # noqa: F401  (保留扩展点)
from projects.models import Board, BoardShareLink, Project, TaskCard
from projects.serializers import BoardSerializer, ProjectSerializer, TaskCardSerializer
from projects.views import _can_access, _log_activity


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
    """为项目生成只读分享链接"""

    def post(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        if project.owner_id != request.user.id:
            return Response({"message": "仅项目创建者可生成分享链接"}, status=403)
        link = BoardShareLink.objects.create(project=project, token=BoardShareLink.make_token(), created_by=request.user)
        return Response({"token": link.token, "url": f"/share/board/{link.token}/", "created_at": link.created_at}, status=201)


class BoardShareRevokeView(APIView):
    """撤销分享链接"""

    def delete(self, request, project_id, token):
        link = BoardShareLink.objects.filter(token=token, project_id=project_id, created_by=request.user).first()
        if not link:
            return Response({"message": "链接不存在"}, status=404)
        link.is_revoked = True
        link.save(update_fields=["is_revoked"])
        return Response({"message": "链接已撤销"})


class BoardSharePublicView(APIView):
    """公开只读看板（免登录）"""

    permission_classes = [AllowAny]

    def get(self, request, token):
        link = BoardShareLink.objects.filter(token=token).first()
        if not link or link.is_expired:
            return Response({"message": "分享链接不存在或已失效"}, status=404)
        link.view_count += 1
        link.save(update_fields=["view_count"])
        project = link.project
        boards = []
        for b in project.boards.all():
            cards = TaskCard.objects.filter(board=b)
            boards.append({**BoardSerializer(b).data, "cards": TaskCardSerializer(cards, many=True).data})
        return Response({
            "project": {"id": project.id, "name": project.name, "color": project.color, "description": project.description},
            "boards": boards,
        })
