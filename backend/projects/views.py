"""看板视图：项目、看板列、卡片拖拽、子任务、工时、评论、成员、活动、统计、我的任务"""
from datetime import timedelta
from django.db.models import Count as ModelsCount, Max as ModelsMax, Sum as ModelsSum, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from core.models import notify
from projects.models import Board, CardComment, Project, ProjectActivity, Subtask, TaskCard, WorkLog
from projects.serializers import (
    BoardSerializer,
    CardCommentSerializer,
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
