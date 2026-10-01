"""看板视图：项目、看板列、卡片拖拽、子任务、工时、评论、成员、活动、统计、我的任务"""
from datetime import timedelta

from django.db.models import Count as ModelsCount, Max as ModelsMax, Sum as ModelsSum, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from core.models import notify
from projects.models import (
    AcceptanceItem,
    Board,
    BoardShareLink,
    CardComment,
    CardDependency,
    CardTemplate,
    Milestone,
    Project,
    ProjectActivity,
    Subtask,
    TaskCard,
    WorkLog,
)
from projects.serializers import (
    AcceptanceItemSerializer,
    BoardSerializer,
    CardCommentSerializer,
    CardTemplateSerializer,
    MilestoneSerializer,
    ProjectActivitySerializer,
    ProjectSerializer,
    SubtaskSerializer,
    TaskCardSerializer,
    WorkLogSerializer,
)


def _can_access(user, project):
    return project.owner_id == user.id or project.members.filter(id=user.id).exists()


def _log_activity(project, user, action, target=""):
    ProjectActivity.objects.create(project=project, user=user, action=action, target=target)


def _card_of(user, pk):
    card = TaskCard.objects.filter(pk=pk).first()
    if not card or not _can_access(user, card.board.project):
        return None
    return card


# ============ 项目 ============

class ProjectListView(APIView):
    """项目列表（我创建 + 我参与的），支持归档/收藏/搜索筛选，创建项目"""

    def get(self, request):
        qs = Project.objects.filter(Q(owner=request.user) | Q(members=request.user)).distinct()
        arch = request.query_params.get("archived")
        if arch == "1":
            qs = qs.filter(is_archived=True)
        elif arch == "all":
            pass
        else:
            qs = qs.filter(is_archived=False)
        if request.query_params.get("star") == "1":
            qs = qs.filter(is_star=True)
        keyword = request.query_params.get("search")
        if keyword:
            qs = qs.filter(name__icontains=keyword)
        return Response({"list": ProjectSerializer(qs, many=True).data, "total": qs.count()})

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"message": "项目名不能为空"}, status=400)
        project = Project.objects.create(
            name=name,
            description=request.data.get("description", ""),
            color=request.data.get("color", "#0ea5e9"),
            owner=request.user,
        )
        for i, col in enumerate(["待办", "进行中", "已完成"]):
            Board.objects.create(project=project, name=col, sort_order=i)
        project.members.add(request.user)
        _log_activity(project, request.user, "创建了项目", project.name)
        return Response(ProjectSerializer(project).data, status=201)


class ProjectDetailView(APIView):
    def get_object(self, request, pk):
        project = Project.objects.filter(pk=pk).first()
        if not project or not _can_access(request.user, project):
            return None
        return project

    def get(self, request, pk):
        project = self.get_object(request, pk)
        if not project:
            return Response({"message": "项目不存在或无权访问"}, status=404)
        return Response(ProjectSerializer(project).data)

    def patch(self, request, pk):
        project = self.get_object(request, pk)
        if not project:
            return Response({"message": "项目不存在或无权访问"}, status=404)
        if project.owner_id != request.user.id and "is_star" not in request.data:
            return Response({"message": "仅项目创建者可编辑"}, status=403)
        for field in ("name", "description", "color", "is_archived", "is_star"):
            if field in request.data:
                setattr(project, field, request.data[field])
        project.save()
        _log_activity(project, request.user, "更新了项目", project.name)
        return Response(ProjectSerializer(project).data)

    def delete(self, request, pk):
        project = self.get_object(request, pk)
        if not project:
            return Response({"message": "项目不存在或无权访问"}, status=404)
        if project.owner_id != request.user.id:
            return Response({"message": "仅项目创建者可删除"}, status=403)
        project.delete()
        return Response({"message": "项目已删除"})


class ProjectStarView(APIView):
    """切换项目收藏"""

    def post(self, request, pk):
        project = Project.objects.filter(pk=pk).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        project.is_star = not project.is_star
        project.save(update_fields=["is_star"])
        return Response({"is_star": project.is_star})


class ProjectCloneView(APIView):
    """克隆项目（复制看板列结构，不复制卡片）"""

    def post(self, request, pk):
        src = Project.objects.filter(pk=pk).first()
        if not src or not _can_access(request.user, src):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        clone = Project.objects.create(
            name=f"{src.name}（副本）", description=src.description, color=src.color, owner=request.user
        )
        clone.members.add(request.user)
        for b in src.boards.all():
            Board.objects.create(project=clone, name=b.name, sort_order=b.sort_order)
        _log_activity(clone, request.user, "克隆了项目", src.name)
        return Response(ProjectSerializer(clone).data, status=201)


class ProjectMemberView(APIView):
    """成员：添加 / 移除 / 列表 / 候选"""

    def get(self, request, pk):
        project = Project.objects.filter(pk=pk).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        members = [
            {"id": u.id, "username": u.username, "display_name": u.display_name,
             "avatar": u.avatar.url if u.avatar else "", "is_owner": u.id == project.owner_id}
            for u in project.members.all()
        ]
        member_ids = list(project.members.values_list("id", flat=True))
        kw = request.query_params.get("q", "")
        cand = User.objects.filter(is_active=True, is_disabled=False).exclude(id__in=member_ids)
        if kw:
            cand = cand.filter(Q(username__icontains=kw) | Q(nickname__icontains=kw))
        candidates = [{"id": u.id, "display_name": u.display_name} for u in cand[:20]]
        return Response({"members": members, "candidates": candidates})

    def post(self, request, pk):
        project = Project.objects.filter(pk=pk).first()
        if not project or project.owner_id != request.user.id:
            return Response({"message": "仅项目创建者可管理成员"}, status=403)
        user_ids = request.data.get("user_ids") or []
        usernames = request.data.get("usernames") or []
        added = []
        users = User.objects.filter(Q(id__in=user_ids) | Q(username__in=usernames))
        for u in users:
            project.members.add(u)
            added.append(u.display_name)
            notify(u, f"你被加入项目「{project.name}」", category="project", link=f"/projects/{project.id}")
        _log_activity(project, request.user, "添加了成员", "、".join(added))
        return Response({"message": f"已添加 {len(added)} 名成员", "member_names": added})

    def delete(self, request, pk):
        project = Project.objects.filter(pk=pk).first()
        if not project or project.owner_id != request.user.id:
            return Response({"message": "仅项目创建者可管理成员"}, status=403)
        user_id = request.query_params.get("user_id")
        user = project.members.filter(id=user_id).first()
        if user:
            project.members.remove(user)
            _log_activity(project, request.user, "移除了成员", user.display_name)
            return Response({"message": f"已移除 {user.display_name}"})
        return Response({"message": "成员不存在"}, status=404)


# ============ 看板列 ============

class BoardListView(APIView):
    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        boards = Board.objects.filter(project=project)
        result = []
        for b in boards:
            cards = TaskCard.objects.filter(board=b)
            result.append({**BoardSerializer(b).data, "cards": TaskCardSerializer(cards, many=True).data})
        return Response({"project": ProjectSerializer(project).data, "boards": result})

    def post(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"message": "列名不能为空"}, status=400)
        max_order = Board.objects.filter(project=project).aggregate(m=ModelsMax("sort_order"))["m"] or 0
        board = Board.objects.create(project=project, name=name, sort_order=max_order + 1)
        _log_activity(project, request.user, "新建了看板列", name)
        return Response(BoardSerializer(board).data, status=201)


class BoardReorderView(APIView):
    """看板列整体排序：传入有序 id 列表"""

    def post(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        order = request.data.get("orders") or []
        for i, bid in enumerate(order):
            Board.objects.filter(pk=bid, project=project).update(sort_order=i)
        return Response({"message": "列顺序已更新"})


class BoardDetailView(APIView):
    def get_object(self, request, board_id):
        return Board.objects.filter(pk=board_id, project__members=request.user).first() or Board.objects.filter(
            pk=board_id, project__owner=request.user
        ).first()

    def patch(self, request, board_id):
        board = self.get_object(request, board_id)
        if not board:
            return Response({"message": "看板列不存在"}, status=404)
        if "name" in request.data:
            board.name = request.data["name"].strip() or board.name
        if "sort_order" in request.data:
            board.sort_order = int(request.data["sort_order"])
        board.save()
        return Response(BoardSerializer(board).data)

    def delete(self, request, board_id):
        board = self.get_object(request, board_id)
        if not board:
            return Response({"message": "看板列不存在"}, status=404)
        project = board.project
        board.delete()
        _log_activity(project, request.user, "删除了看板列", board.name)
        return Response({"message": "看板列已删除"})


# ============ 任务卡片 ============

class CardListView(APIView):
    def post(self, request, board_id):
        board = Board.objects.filter(pk=board_id).first()
        if not board or not _can_access(request.user, board.project):
            return Response({"message": "看板列不存在或无权访问"}, status=404)
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"message": "标题不能为空"}, status=400)
        max_order = TaskCard.objects.filter(board=board).aggregate(m=ModelsMax("sort_order"))["m"] or 0
        card = TaskCard.objects.create(
            board=board, title=title, description=request.data.get("description", ""),
            priority=request.data.get("priority", "medium"), status=request.data.get("status", "todo"),
            due_date=request.data.get("due_date") or None,
            story_points=int(request.data.get("story_points", 0) or 0),
            sort_order=max_order + 1, created_by=request.user,
        )
        if request.data.get("labels"):
            card.labels = request.data["labels"][:10]
            card.save(update_fields=["labels"])
        assignee_ids = request.data.get("assignee_ids") or []
        if assignee_ids:
            card.assignees.set(User.objects.filter(id__in=assignee_ids))
            for u in card.assignees.all():
                if u.id != request.user.id:
                    notify(u, f"你被分配了新任务「{card.title}」", category="project", link=f"/projects/{board.project_id}")
        _log_activity(board.project, request.user, "创建了任务", card.title)
        return Response(TaskCardSerializer(card).data, status=201)


class CardDetailView(APIView):
    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        data = TaskCardSerializer(card).data
        data["subtasks"] = SubtaskSerializer(card.subtasks.all(), many=True).data
        data["worklogs"] = WorkLogSerializer(card.worklogs.all(), many=True).data
        return Response(data)

    def patch(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        for f in ("title", "description", "priority"):
            if f in request.data:
                setattr(card, f, request.data[f])
        if "story_points" in request.data:
            card.story_points = int(request.data["story_points"] or 0)
        if "status" in request.data:
            new_status = request.data["status"]
            if new_status == "doing" and not card.started_at:
                card.started_at = timezone.now()
            if new_status == "done":
                card.completed_at = timezone.now()
            elif card.status == "done" and new_status != "done":
                card.completed_at = None
            card.status = new_status
        if "due_date" in request.data:
            card.due_date = request.data["due_date"] or None
        if "labels" in request.data and isinstance(request.data["labels"], list):
            card.labels = request.data["labels"][:10]
        if "board" in request.data:
            new_board = Board.objects.filter(pk=request.data["board"], project=card.board.project).first()
            if new_board:
                card.board = new_board
                card.sort_order = (TaskCard.objects.filter(board=new_board).aggregate(m=ModelsMax("sort_order"))["m"] or 0) + 1
        if "assignee_ids" in request.data:
            card.assignees.set(User.objects.filter(id__in=request.data["assignee_ids"]))
        card.save()
        _log_activity(card.board.project, request.user, "更新了任务", card.title)
        return Response(TaskCardSerializer(card).data)

    def delete(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        title, project = card.title, card.board.project
        card.delete()
        _log_activity(project, request.user, "删除了任务", title)
        return Response({"message": "任务已删除"})


class CardBatchView(APIView):
    """项目内批量任务：status / priority / assignees / delete / move"""

    def post(self, request):
        project_id = request.data.get("project_id")
        ids = request.data.get("card_ids") or []
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        qs = TaskCard.objects.filter(id__in=ids, board__project=project)
        action = request.data.get("action")
        if action == "delete":
            n = qs.delete()[0]
            return Response({"message": f"已删除 {n} 个任务"})
        if action == "status":
            v = request.data.get("status")
            update = {"status": v}
            if v == "done":
                update["completed_at"] = timezone.now()
            n = qs.update(**update)
            return Response({"message": f"已更新 {n} 个任务状态"})
        if action == "priority":
            n = qs.update(priority=request.data.get("priority", "medium"))
            return Response({"message": f"已更新 {n} 个任务优先级"})
        if action == "move":
            board = Board.objects.filter(pk=request.data.get("board_id"), project=project).first()
            if not board:
                return Response({"message": "目标列不存在"}, status=404)
            n = qs.update(board=board)
            return Response({"message": f"已移动 {n} 个任务"})
        if action == "assignees":
            users = User.objects.filter(id__in=request.data.get("user_ids") or [])
            for c in qs:
                c.assignees.set(users)
            return Response({"message": "已批量分配负责人"})
        return Response({"message": "未知操作"}, status=400)


class CardCopyView(APIView):
    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        max_order = TaskCard.objects.filter(board=card.board).aggregate(m=ModelsMax("sort_order"))["m"] or 0
        copy = TaskCard.objects.create(
            board=card.board, title=f"{card.title}（副本）", description=card.description,
            priority=card.priority, labels=card.labels, due_date=card.due_date,
            story_points=card.story_points, sort_order=max_order + 1, created_by=request.user,
        )
        copy.assignees.set(card.assignees.all())
        for st in card.subtasks.all():
            Subtask.objects.create(card=copy, title=st.title, is_done=False, sort_order=st.sort_order)
        return Response(TaskCardSerializer(copy).data, status=201)


class CardMoveView(APIView):
    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        target_board_id = request.data.get("board_id")
        target_index = int(request.data.get("index", 0))
        if target_board_id:
            target_board = Board.objects.filter(pk=target_board_id, project=card.board.project).first()
            if not target_board:
                return Response({"message": "目标列不存在"}, status=404)
            card.board = target_board
        card.sort_order = target_index
        card.save()
        siblings = list(TaskCard.objects.filter(board=card.board).exclude(pk=card.pk).order_by("sort_order", "id"))
        siblings.insert(min(target_index, len(siblings)), card)
        for i, c in enumerate(siblings):
            if c.sort_order != i:
                TaskCard.objects.filter(pk=c.pk).update(sort_order=i)
        _log_activity(card.board.project, request.user, "移动了任务", card.title)
        return Response({"message": "已移动", "card": TaskCardSerializer(card).data})


class CardSearchView(APIView):
    """项目内任务筛选/搜索：关键字/优先级/状态/负责人/标签/到期分桶"""

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        qs = TaskCard.objects.filter(board__project=project)
        kw = request.query_params.get("q")
        if kw:
            qs = qs.filter(Q(title__icontains=kw) | Q(description__icontains=kw))
        for f in ("priority", "status"):
            v = request.query_params.get(f)
            if v:
                qs = qs.filter(**{f: v})
        assignee = request.query_params.get("assignee")
        if assignee:
            qs = qs.filter(assignees__id=assignee)
        label = request.query_params.get("label")
        if label:
            qs = qs.filter(labels__contains=[label])
        due = request.query_params.get("due")
        today = timezone.now().date()
        if due == "overdue":
            qs = qs.filter(due_date__lt=today).exclude(status="done")
        elif due == "today":
            qs = qs.filter(due_date=today)
        elif due == "week":
            qs = qs.filter(due_date__gte=today, due_date__lte=today + timedelta(days=7))
        elif due == "nodate":
            qs = qs.filter(due_date__isnull=True)
        qs = qs.distinct()
        return Response({"list": TaskCardSerializer(qs, many=True).data, "total": qs.count()})


# ============ 子任务 ============

class SubtaskListView(APIView):
    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"message": "子任务标题不能为空"}, status=400)
        order = (card.subtasks.aggregate(m=ModelsMax("sort_order"))["m"] or 0) + 1
        assignee = User.objects.filter(pk=request.data.get("assignee_id")).first()
        st = Subtask.objects.create(card=card, title=title, sort_order=order, assignee=assignee)
        return Response(SubtaskSerializer(st).data, status=201)


class SubtaskDetailView(APIView):
    def _get(self, request, pk, sid):
        return Subtask.objects.filter(pk=sid, card_id=pk, card__board__project__members=request.user).first() or \
            Subtask.objects.filter(pk=sid, card_id=pk, card__board__project__owner=request.user).first()

    def patch(self, request, pk, sid):
        st = self._get(request, pk, sid)
        if not st:
            return Response({"message": "子任务不存在"}, status=404)
        if "title" in request.data:
            st.title = request.data["title"].strip() or st.title
        if "is_done" in request.data:
            st.is_done = bool(request.data["is_done"])
        if "assignee_id" in request.data:
            st.assignee = User.objects.filter(pk=request.data["assignee_id"]).first()
        st.save()
        return Response(SubtaskSerializer(st).data)

    def delete(self, request, pk, sid):
        st = self._get(request, pk, sid)
        if not st:
            return Response({"message": "子任务不存在"}, status=404)
        st.delete()
        return Response({"message": "子任务已删除"})


# ============ 工时 ============

class WorkLogListView(APIView):
    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        return Response({"list": WorkLogSerializer(card.worklogs.all(), many=True).data,
                         "total_minutes": card.worklogs.aggregate(s=ModelsSum("minutes"))["s"] or 0})

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        minutes = int(request.data.get("minutes", 0) or 0)
        if minutes <= 0:
            return Response({"message": "工时必须大于 0 分钟"}, status=400)
        wl = WorkLog.objects.create(card=card, user=request.user, minutes=minutes, note=request.data.get("note", "")[:200])
        return Response(WorkLogSerializer(wl).data, status=201)


class WorkLogDetailView(APIView):
    def delete(self, request, pk, wid):
        wl = WorkLog.objects.filter(pk=wid, card_id=pk, user=request.user).first()
        if not wl:
            return Response({"message": "工时记录不存在"}, status=404)
        wl.delete()
        return Response({"message": "工时记录已删除"})


# ============ 评论 ============

class CardCommentListView(APIView):
    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        qs = card.comments.all()
        return Response({"list": CardCommentSerializer(qs, many=True, context={"request": request}).data, "total": qs.count()})

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        content = (request.data.get("content") or "").strip()
        if not content:
            return Response({"message": "评论内容不能为空"}, status=400)
        comment = CardComment.objects.create(card=card, author=request.user, content=content)
        # 通知负责人
        for u in card.assignees.exclude(id=request.user.id):
            notify(u, f"任务「{card.title}」有新评论", category="project", link=f"/projects/{card.board.project_id}")
        _log_activity(card.board.project, request.user, "评论了任务", card.title)
        return Response(CardCommentSerializer(comment, context={"request": request}).data, status=201)


class CardCommentDetailView(APIView):
    """评论编辑 / 删除（作者或项目所有者）"""

    def _get(self, request, pk, cid):
        c = CardComment.objects.filter(pk=cid, card_id=pk).first()
        if not c:
            return None
        project = c.card.board.project
        if request.user.id != c.author_id and request.user.id != project.owner_id:
            return False
        return c

    def patch(self, request, pk, cid):
        c = self._get(request, pk, cid)
        if c is False:
            return Response({"message": "无权编辑该评论"}, status=403)
        if not c:
            return Response({"message": "评论不存在"}, status=404)
        content = (request.data.get("content") or "").strip()
        if content:
            c.content = content
            c.save(update_fields=["content", "updated_at"])
        return Response(CardCommentSerializer(c, context={"request": request}).data)

    def delete(self, request, pk, cid):
        c = self._get(request, pk, cid)
        if c is False:
            return Response({"message": "无权删除该评论"}, status=403)
        if not c:
            return Response({"message": "评论不存在"}, status=404)
        c.delete()
        return Response({"message": "评论已删除"})


# ============ 活动 / 统计 / 跨项目 ============

class ProjectActivityView(APIView):
    """项目活动流（分页 + 动作筛选）"""

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        qs = project.activities.all()
        action = request.query_params.get("action")
        if action:
            qs = qs.filter(action__icontains=action)
        return Response({"list": ProjectActivitySerializer(qs[:100], many=True).data, "total": qs.count()})


class ProjectStatsView(APIView):
    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        cards = TaskCard.objects.filter(board__project=project)
        by_board = list(cards.values("board__name", "board_id").annotate(c=ModelsCount("id")).order_by())
        by_priority = list(cards.values("priority").annotate(c=ModelsCount("id")).order_by())
        by_status = list(cards.values("status").annotate(c=ModelsCount("id")).order_by())
        by_assignee = list(
            cards.values("assignees__username", "assignees__nickname").annotate(c=ModelsCount("id")).order_by("-c")
        )
        overdue = cards.filter(due_date__lt=timezone.now().date(), status__in=["todo", "doing"]).count()
        total_points = cards.aggregate(s=ModelsSum("story_points"))["s"] or 0
        done_points = cards.filter(status="done").aggregate(s=ModelsSum("story_points"))["s"] or 0
        spent = cards.aggregate(s=ModelsSum("worklogs__minutes"))["s"] or 0
        return Response({
            "total": cards.count(),
            "done": cards.filter(status="done").count(),
            "doing": cards.filter(status="doing").count(),
            "todo": cards.filter(status="todo").count(),
            "overdue": overdue,
            "total_points": total_points,
            "done_points": done_points,
            "spent_minutes": spent,
            "by_board": by_board, "by_priority": by_priority, "by_status": by_status, "by_assignee": by_assignee,
            "activities": ProjectActivitySerializer(project.activities.all()[:20], many=True).data,
        })


class ProjectCalendarView(APIView):
    """按截止日期聚合任务（日历/甘特数据）"""

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        cards = TaskCard.objects.filter(board__project=project).exclude(due_date__isnull=True)
        days = {}
        for c in cards:
            key = str(c.due_date)
            days.setdefault(key, []).append({"id": c.id, "title": c.title, "status": c.status, "priority": c.priority})
        return Response({"days": days})


class MyTasksView(APIView):
    """跨项目「我的任务」：分配给我 / 我创建，支持状态与到期分桶"""

    def get(self, request):
        scope = request.query_params.get("scope", "assigned")
        if scope == "created":
            qs = TaskCard.objects.filter(created_by=request.user)
        else:
            qs = TaskCard.objects.filter(assignees=request.user)
        qs = qs.filter(board__project__is_archived=False)
        status_f = request.query_params.get("status")
        if status_f:
            qs = qs.filter(status=status_f)
        today = timezone.now().date()
        bucket = request.query_params.get("bucket")
        if bucket == "overdue":
            qs = qs.filter(due_date__lt=today).exclude(status="done")
        elif bucket == "today":
            qs = qs.filter(due_date=today)
        elif bucket == "week":
            qs = qs.filter(due_date__gte=today, due_date__lte=today + timedelta(days=7))
        elif bucket == "nodate":
            qs = qs.filter(due_date__isnull=True)
        qs = qs.select_related("board", "board__project").distinct().order_by("due_date", "-id")
        data = []
        for c in qs[:200]:
            d = TaskCardSerializer(c).data
            d["project_id"] = c.board.project_id
            d["project_name"] = c.board.project.name
            data.append(d)
        # 分桶计数
        all_mine = TaskCard.objects.filter(assignees=request.user).exclude(status="done")
        counts = {
            "all": TaskCard.objects.filter(assignees=request.user).count(),
            "open": all_mine.count(),
            "overdue": all_mine.filter(due_date__lt=today).count(),
            "today": all_mine.filter(due_date=today).count(),
            "week": all_mine.filter(due_date__gte=today, due_date__lte=today + timedelta(days=7)).count(),
            "done": TaskCard.objects.filter(assignees=request.user, status="done").count(),
        }
        return Response({"list": data, "total": len(data), "counts": counts})


# ===========================================================================
# 看板增强 F583–F598（纯新增，不改动上方既有接口）
# ===========================================================================

def _board_of(user, board_id):
    board = Board.objects.filter(pk=board_id).first()
    if not board or not _can_access(user, board.project):
        return None
    return board


def _parse_date(value):
    """把 YYYY-MM-DD 字符串解析为 date，非法则返回 None（避免写入时报 500）"""
    if not value:
        return None
    from datetime import datetime as _dt

    try:
        return _dt.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


class CardCountdownView(APIView):
    """F583 卡片倒计时徽章：返回剩余天数与告警级别"""

    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        if not card.due_date:
            return Response({"has_due": False, "level": "none", "text": "未设置截止日期",
                             "card_id": card.id, "code": card.code})
        today = timezone.localdate()
        days = (card.due_date - today).days
        if card.status == "done":
            level, text = "done", "已完成"
        elif days < 0:
            level, text = "overdue", f"已逾期 {abs(days)} 天"
        elif days == 0:
            level, text = "danger", "今天到期"
        elif days <= 2:
            level, text = "warning", f"还剩 {days} 天"
        else:
            level, text = "normal", f"还剩 {days} 天"
        return Response({
            "has_due": True, "card_id": card.id, "code": card.code,
            "due_date": str(card.due_date), "days_left": days,
            "overdue": days < 0 and card.status != "done",
            "level": level, "text": text, "status": card.status,
        })


class CardChecklistView(APIView):
    """F584 checklist 独立视图：列出/新增检查清单项及完成度"""

    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        items = card.subtasks.all()
        total = items.count()
        done = items.filter(is_done=True).count()
        return Response({
            "card_id": card.id, "code": card.code, "title": card.title,
            "list": SubtaskSerializer(items, many=True).data,
            "total": total, "done": done,
            "progress": round(done / total * 100) if total else 0,
        })

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"message": "清单项不能为空"}, status=400)
        order = (card.subtasks.aggregate(m=ModelsMax("sort_order"))["m"] or 0) + 1
        assignee = User.objects.filter(pk=request.data.get("assignee_id")).first()
        st = Subtask.objects.create(card=card, title=title, sort_order=order, assignee=assignee)
        return Response(SubtaskSerializer(st).data, status=201)


class BoardWipView(APIView):
    """F585 列 WIP 上限：查询/设置某列在制品上限并提示超限"""

    def get(self, request, board_id):
        board = _board_of(request.user, board_id)
        if not board:
            return Response({"message": "看板列不存在或无权访问"}, status=404)
        cards = board.cards.all()
        total = cards.count()
        active = cards.exclude(status="done").count()
        limit = board.wip_limit or 0
        over = bool(limit and active > limit)
        return Response({
            "board_id": board.id, "name": board.name, "wip_limit": limit,
            "card_count": total, "active_count": active, "over": over,
            "message": f"超限：{active}/{limit}，请先完成或移出部分卡片" if over else "正常",
        })

    def post(self, request, board_id):
        board = _board_of(request.user, board_id)
        if not board:
            return Response({"message": "看板列不存在或无权访问"}, status=404)
        try:
            limit = int(request.data.get("wip_limit", 0) or 0)
        except (TypeError, ValueError):
            return Response({"message": "wip_limit 必须为整数"}, status=400)
        board.wip_limit = max(limit, 0)
        board.save(update_fields=["wip_limit"])
        active = board.cards.exclude(status="done").count()
        over = bool(board.wip_limit and active > board.wip_limit)
        return Response({"message": "已更新 WIP 上限", "board_id": board.id, "wip_limit": board.wip_limit,
                         "active_count": active, "over": over})


class CardTimelineView(APIView):
    """F586 卡片活动时间线：创建/开始/完成/评论/工时/项目动态聚合"""

    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        events = []

        def add(kind, at, text, user=""):
            if at:
                events.append({"type": kind, "at": at.isoformat(), "text": text, "user": user})

        add("created", card.created_at, "创建了卡片", card.created_by.display_name if card.created_by else "")
        add("started", card.started_at, "开始处理", "")
        add("completed", card.completed_at, "完成了卡片", "")
        for c in card.comments.all():
            add("comment", c.created_at, c.content[:200], c.author.display_name if c.author else "")
        for w in card.worklogs.all():
            add("worklog", w.created_at, f"登记工时 {w.minutes} 分钟" + (f"：{w.note}" if w.note else ""),
                w.user.display_name if w.user else "")
        for a in card.board.project.activities.filter(target=card.title)[:50]:
            add("activity", a.created_at, a.action, a.user.display_name if a.user else "系统")
        events.sort(key=lambda e: e["at"], reverse=True)
        return Response({"card_id": card.id, "code": card.code, "title": card.title,
                         "list": events, "total": len(events)})


class ProjectWeeklyReportView(APIView):
    """F587 看板周报：近 7 天新增/完成/剩余三线数据"""

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        try:
            span = min(max(int(request.query_params.get("days", 7)), 1), 30)
        except (TypeError, ValueError):
            span = 7
        today = timezone.localdate()
        days = [today - timedelta(days=i) for i in range(span - 1, -1, -1)]
        cards = list(TaskCard.objects.filter(board__project=project))
        created_series, completed_series, remaining_series = [], [], []
        for d in days:
            created_series.append(sum(1 for c in cards if c.created_at.date() == d))
            completed_series.append(sum(1 for c in cards if c.completed_at and c.completed_at.date() == d))
            remaining_series.append(sum(
                1 for c in cards
                if c.created_at.date() <= d and not (c.completed_at and c.completed_at.date() <= d)
            ))
        return Response({
            "dates": [str(d) for d in days],
            "created": created_series,
            "completed": completed_series,
            "remaining": remaining_series,
            "summary": {
                "created": sum(created_series),
                "completed": sum(completed_series),
                "open_now": remaining_series[-1] if remaining_series else 0,
                "total": len(cards),
            },
        })


class CardDependencyView(APIView):
    """F588 卡片依赖：查询/新增/移除阻塞关系"""

    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        deps = card.dependencies.select_related("blocked_by")
        blocks = card.blocks.select_related("card")
        blockers = [{"id": d.blocked_by_id, "code": d.blocked_by.code, "title": d.blocked_by.title,
                     "status": d.blocked_by.status} for d in deps]
        return Response({
            "card_id": card.id, "code": card.code,
            "blocked_by": blockers,
            "blocking": [{"id": b.card_id, "code": b.card.code, "title": b.card.title,
                          "status": b.card.status} for b in blocks],
            "is_blocked": any(b["status"] != "done" for b in blockers),
        })

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        ids = request.data.get("blocked_by_ids")
        if ids is None:
            ids = [request.data.get("blocked_by_id")] if request.data.get("blocked_by_id") else []
        project_id = card.board.project_id
        added = []
        for bid in ids:
            if not bid or int(bid) == card.id:
                continue
            other = TaskCard.objects.filter(pk=bid, board__project_id=project_id).first()
            if not other:
                continue
            CardDependency.objects.get_or_create(card=card, blocked_by=other)
            added.append(other.id)
        return Response({"message": f"已添加 {len(added)} 条依赖", "added": added}, status=201)

    def delete(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        bid = request.query_params.get("blocked_by_id")
        if not bid:
            return Response({"message": "缺少 blocked_by_id"}, status=400)
        deleted = card.dependencies.filter(blocked_by_id=bid).delete()[0]
        return Response({"message": f"已移除 {deleted} 条依赖"})


class ProjectMilestoneView(APIView):
    """F589 里程碑：列表 / 新建"""

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        qs = project.milestones.all()
        today = timezone.localdate()
        data = MilestoneSerializer(qs, many=True).data
        for d in data:
            d["overdue"] = bool(d["due_date"] and d["status"] != "done" and str(today) > d["due_date"])
        return Response({"list": data, "total": len(data)})

    def post(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"message": "里程碑名称不能为空"}, status=400)
        ms = Milestone.objects.create(
            project=project, name=name, description=request.data.get("description", ""),
            due_date=_parse_date(request.data.get("due_date")),
            status=request.data.get("status", "planned"),
        )
        _log_activity(project, request.user, "新建了里程碑", name)
        return Response(MilestoneSerializer(ms).data, status=201)


class MilestoneDetailView(APIView):
    """F589 里程碑：更新 / 删除"""

    def _get(self, request, pk):
        ms = Milestone.objects.filter(pk=pk).first()
        if not ms or not _can_access(request.user, ms.project):
            return None
        return ms

    def patch(self, request, pk):
        ms = self._get(request, pk)
        if not ms:
            return Response({"message": "里程碑不存在或无权访问"}, status=404)
        for f in ("name", "description", "status"):
            if f in request.data:
                setattr(ms, f, request.data[f])
        if "due_date" in request.data:
            ms.due_date = _parse_date(request.data["due_date"])
        ms.save()
        return Response(MilestoneSerializer(ms).data)

    def delete(self, request, pk):
        ms = self._get(request, pk)
        if not ms:
            return Response({"message": "里程碑不存在或无权访问"}, status=404)
        ms.delete()
        return Response({"message": "里程碑已删除"})


class CardEstimateView(APIView):
    """F590 工时估算与累计：预估 vs 实际"""

    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        spent = card.worklogs.aggregate(s=ModelsSum("minutes"))["s"] or 0
        estimated = card.estimated_minutes or 0
        return Response({
            "card_id": card.id, "code": card.code, "story_points": card.story_points,
            "estimated_minutes": estimated, "spent_minutes": spent,
            "remaining_minutes": max(estimated - spent, 0), "over": bool(estimated and spent > estimated),
            "progress": round(spent / estimated * 100) if estimated else 0,
        })

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        try:
            minutes = int(request.data.get("estimated_minutes", 0) or 0)
        except (TypeError, ValueError):
            return Response({"message": "estimated_minutes 必须为整数"}, status=400)
        card.estimated_minutes = max(minutes, 0)
        card.save(update_fields=["estimated_minutes"])
        return Response({"message": "已更新预估工时", "estimated_minutes": card.estimated_minutes})


class ProjectWorkloadView(APIView):
    """F591 成员工作量分布"""

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        today = timezone.localdate()
        cards = TaskCard.objects.filter(board__project=project)
        rows = []
        for u in project.members.all():
            mine = cards.filter(assignees=u).distinct()
            open_qs = mine.exclude(status="done")
            spent = WorkLog.objects.filter(card__board__project=project, user=u).aggregate(s=ModelsSum("minutes"))["s"] or 0
            rows.append({
                "user_id": u.id, "display_name": u.display_name,
                "total": mine.count(), "open": open_qs.count(), "done": mine.filter(status="done").count(),
                "overdue": open_qs.filter(due_date__lt=today).count(),
                "open_points": open_qs.aggregate(s=ModelsSum("story_points"))["s"] or 0,
                "spent_minutes": spent,
            })
        max_open = max([r["open"] for r in rows], default=0)
        for r in rows:
            r["load_percent"] = round(r["open"] / max_open * 100) if max_open else 0
        rows.sort(key=lambda r: r["open"], reverse=True)
        return Response({"list": rows, "total": len(rows), "max_open": max_open})


class CardByNumberView(APIView):
    """F592/F596 通过项目内编号（C-n）定位卡片"""

    def get(self, request, project_id, number):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        card = TaskCard.objects.filter(board__project=project, number=number).first()
        if not card:
            return Response({"message": f"C-{number} 不存在"}, status=404)
        data = TaskCardSerializer(card).data
        data["project_id"] = project.id
        data["project_name"] = project.name
        return Response(data)


class CardBatchMoveView(APIView):
    """F593 批量移动卡片到目标列（保持传入顺序）"""

    def post(self, request):
        project_id = request.data.get("project_id")
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        board = Board.objects.filter(pk=request.data.get("board_id"), project=project).first()
        if not board:
            return Response({"message": "目标列不存在"}, status=404)
        ids = request.data.get("card_ids") or []
        cards = list(TaskCard.objects.filter(id__in=ids, board__project=project).order_by("sort_order", "id"))
        if not cards:
            return Response({"message": "没有可移动的卡片"}, status=400)
        start = request.data.get("index")
        if start is None:
            start = (TaskCard.objects.filter(board=board).aggregate(m=ModelsMax("sort_order"))["m"] or 0) + 1
        try:
            start = max(int(start), 0)
        except (TypeError, ValueError):
            start = 0
        moved = []
        for i, card in enumerate(cards):
            card.board = board
            card.sort_order = start + i
            card.save(update_fields=["board", "sort_order"])
            moved.append(card.id)
        _log_activity(project, request.user, "批量移动了任务", f"{len(moved)} 个 → {board.name}")
        return Response({"message": f"已移动 {len(moved)} 个任务", "moved": moved,
                         "board_id": board.id, "board_name": board.name})


class CardSaveTemplateView(APIView):
    """F594 把卡片保存为模板"""

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        name = (request.data.get("name") or card.title).strip()[:200]
        tpl = CardTemplate.objects.create(
            owner=request.user, name=name, title=card.title, description=card.description,
            priority=card.priority, labels=card.labels, story_points=card.story_points,
            estimated_minutes=card.estimated_minutes,
        )
        return Response(CardTemplateSerializer(tpl).data, status=201)


class CardTemplateListView(APIView):
    """F594 我的卡片模板：列表 / 新建"""

    def get(self, request):
        qs = CardTemplate.objects.filter(owner=request.user)
        return Response({"list": CardTemplateSerializer(qs, many=True).data, "total": qs.count()})

    def post(self, request):
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"message": "标题不能为空"}, status=400)
        tpl = CardTemplate.objects.create(
            owner=request.user, name=(request.data.get("name") or title)[:200], title=title,
            description=request.data.get("description", ""), priority=request.data.get("priority", "medium"),
            labels=request.data.get("labels") or [], story_points=int(request.data.get("story_points", 0) or 0),
            estimated_minutes=int(request.data.get("estimated_minutes", 0) or 0),
        )
        return Response(CardTemplateSerializer(tpl).data, status=201)


class CardTemplateApplyView(APIView):
    """F594 用模板在某列创建卡片"""

    def post(self, request, pk):
        tpl = CardTemplate.objects.filter(pk=pk, owner=request.user).first()
        if not tpl:
            return Response({"message": "模板不存在"}, status=404)
        board = _board_of(request.user, request.data.get("board_id"))
        if not board:
            return Response({"message": "看板列不存在或无权访问"}, status=404)
        max_order = TaskCard.objects.filter(board=board).aggregate(m=ModelsMax("sort_order"))["m"] or 0
        card = TaskCard.objects.create(
            board=board, title=request.data.get("title") or tpl.title, description=tpl.description,
            priority=tpl.priority, labels=tpl.labels, story_points=tpl.story_points,
            estimated_minutes=tpl.estimated_minutes, sort_order=max_order + 1, created_by=request.user,
        )
        _log_activity(board.project, request.user, "从模板创建了任务", card.title)
        return Response(TaskCardSerializer(card).data, status=201)


class CardDodView(APIView):
    """F595 验收清单 DoD：列表 / 新增"""

    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        items = card.acceptance_items.all()
        total = items.count()
        done = items.filter(is_done=True).count()
        return Response({
            "card_id": card.id, "code": card.code,
            "list": AcceptanceItemSerializer(items, many=True).data,
            "total": total, "done": done, "passed": bool(total) and done == total,
            "progress": round(done / total * 100) if total else 0,
        })

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        content = (request.data.get("content") or "").strip()
        if not content:
            return Response({"message": "验收项不能为空"}, status=400)
        order = (card.acceptance_items.aggregate(m=ModelsMax("sort_order"))["m"] or 0) + 1
        item = AcceptanceItem.objects.create(card=card, content=content[:300], sort_order=order)
        return Response(AcceptanceItemSerializer(item).data, status=201)


class CardDodDetailView(APIView):
    """F595 验收清单 DoD：勾选 / 删除"""

    def _get(self, request, pk, item_id):
        item = AcceptanceItem.objects.filter(pk=item_id, card_id=pk).first()
        if not item:
            return None
        if not _can_access(request.user, item.card.board.project):
            return None
        return item

    def patch(self, request, pk, item_id):
        item = self._get(request, pk, item_id)
        if not item:
            return Response({"message": "验收项不存在"}, status=404)
        if "content" in request.data and (request.data["content"] or "").strip():
            item.content = request.data["content"].strip()[:300]
        if "is_done" in request.data:
            item.is_done = bool(request.data["is_done"])
        item.save()
        return Response(AcceptanceItemSerializer(item).data)

    def delete(self, request, pk, item_id):
        item = self._get(request, pk, item_id)
        if not item:
            return Response({"message": "验收项不存在"}, status=404)
        item.delete()
        return Response({"message": "验收项已删除"})


class CardResolveView(APIView):
    """F596 #编号 互跳：解析文本中的 C-n 引用并返回对应卡片"""

    def post(self, request, project_id):
        import re

        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        text = request.data.get("text") or ""
        nums = [int(n) for n in re.findall(r"C-(\d+)", text, flags=re.IGNORECASE)]
        cards = TaskCard.objects.filter(board__project=project, number__in=nums)
        by_num = {c.number: c for c in cards}
        return Response({
            "numbers": nums,
            "list": [{"number": c.number, "code": c.code, "id": c.id, "title": c.title,
                      "board_id": c.board_id, "status": c.status} for n in nums if (c := by_num.get(n))],
        })


class ProjectStandupView(APIView):
    """F597 每日站会三栏：昨天完成 / 今天进行 / 阻塞"""

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        day_str = request.query_params.get("date")
        try:
            from datetime import datetime as _dt

            target = _dt.strptime(day_str, "%Y-%m-%d").date() if day_str else timezone.localdate()
        except (TypeError, ValueError):
            target = timezone.localdate()
        prev = target - timedelta(days=1)
        cards = list(TaskCard.objects.filter(board__project=project).select_related("board"))

        def brief(c):
            return {"id": c.id, "code": c.code, "title": c.title, "status": c.status,
                    "board_id": c.board_id, "board_name": c.board.name,
                    "assignee_names": [u.display_name for u in c.assignees.all()]}

        done_yesterday = [brief(c) for c in cards if c.completed_at and c.completed_at.date() == prev]
        doing_today = [brief(c) for c in cards if c.status == "doing"]
        blocked = []
        for c in cards:
            if c.status == "done":
                continue
            has_blocker = any(d.blocked_by.status != "done" for d in c.dependencies.select_related("blocked_by"))
            overdue = bool(c.due_date and c.due_date < target)
            if has_blocker or overdue:
                item = brief(c)
                item["reason"] = "被依赖阻塞" if has_blocker else "已逾期"
                blocked.append(item)
        return Response({
            "date": str(target),
            "done_yesterday": done_yesterday,
            "doing_today": doing_today,
            "blocked": blocked,
            "summary": {"done": len(done_yesterday), "doing": len(doing_today), "blocked": len(blocked)},
        })


class CardArchiveView(APIView):
    """F598 卡片归档 / 取消归档"""

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        if "is_archived" in request.data:
            card.is_archived = bool(request.data["is_archived"])
        else:
            card.is_archived = not card.is_archived
        card.save(update_fields=["is_archived"])
        _log_activity(card.board.project, request.user,
                      "归档了任务" if card.is_archived else "取消归档任务", card.title)
        return Response({"message": "已归档" if card.is_archived else "已取消归档",
                         "card_id": card.id, "is_archived": card.is_archived})


class ProjectArchivedCardsView(APIView):
    """F598 已归档卡片列表"""

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        qs = TaskCard.objects.filter(board__project=project, is_archived=True)
        return Response({"list": TaskCardSerializer(qs, many=True).data, "total": qs.count()})
