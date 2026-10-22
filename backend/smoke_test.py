"""综合冒烟测试：真实调用各模块 API，覆盖 100+ 新增/既有功能的全链路。
运行：venv/Scripts/python smoke_test.py
"""
import io
import os
import django
import hashlib
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from rest_framework.test import APIClient  # noqa: E402

passed, failed = [], []


def check(name, cond, extra=""):
    if cond:
        passed.append(name)
        print(f"  ✓ {name}")
    else:
        failed.append(name)
        print(f"  ✗ {name} {extra}")


def register(client, username, password="test123", **extra):
    return client.post("/api/auth/register/", {"username": username, "password": password, **extra}, format="json")


def auth_client(token):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return c


def main():
    ts = int(time.time())
    uname = f"tester{ts}"

    # ---------- 1. 账号 / 认证 ----------
    c = APIClient()
    r = register(c, uname, nickname="测试员")
    check("注册", r.status_code == 201, str(r.status_code))
    access, refresh = r.data.get("access"), r.data.get("refresh")
    c = auth_client(access)

    r = APIClient().post("/api/auth/login/", {"username": "admin", "password": "admin123"}, format="json")
    check("登录返回用户信息", r.status_code == 200 and r.data.get("user", {}).get("username") == "admin")
    ca = auth_client(r.data["access"])

    r = c.get("/api/auth/username-check/", {"username": "zzz_unique_xyz"})
    check("用户名可用性校验", r.status_code == 200 and r.data.get("available") is True)
    r = c.post("/api/auth/logout/", {"refresh": refresh}, format="json")
    check("登出(黑名单)", r.status_code == 200)
    r = c.patch("/api/auth/profile/", {"bio": "简介"}, format="json")
    check("修改资料", r.status_code == 200 and r.data["user"]["bio"] == "简介")
    new_uname = f"renamed{ts}"
    r = c.post("/api/auth/profile/change-username/", {"username": new_uname}, format="json")
    check("修改用户名", r.status_code == 200 and r.data["user"]["username"] == new_uname)
    r = c.delete("/api/auth/profile/avatar/")
    check("删除头像", r.status_code == 200)
    r = c.get("/api/auth/profile/export/")
    check("个人数据导出", r.status_code == 200 and "profile" in r.data)
    r = c.post("/api/auth/heartbeat/", {}, format="json")
    check("在线心跳", r.status_code == 200 and r.data.get("ok"))
    r = c.get("/api/auth/profile/login-history/")
    check("登录历史", r.status_code == 200 and r.data.get("total", 0) >= 1)
    r = c.get("/api/auth/directory/")
    check("用户名录", r.status_code == 200 and r.data.get("total", 0) >= 1)
    r = c.get("/api/auth/me/permissions/")
    check("我的权限点", r.status_code == 200 and "permissions" in r.data)

    # 改密 / 注销（独立用户，避免影响主流程）
    ct = APIClient()
    rr = register(ct, f"throw{ts}")
    ct = auth_client(rr.data["access"])
    r = ct.post("/api/auth/profile/change-password/", {"old_password": "test123", "new_password": "newpass456"}, format="json")
    check("修改密码", r.status_code == 200)
    # B12：改密后旧 token 立即失效是预期行为 —— 重新登录拿新凭证再走注销
    r = APIClient().post("/api/auth/login/", {"username": f"throw{ts}", "password": "newpass456"}, format="json")
    check("改密后重新登录", r.status_code == 200)
    ct = auth_client(r.data["access"])
    r = ct.post("/api/auth/profile/deactivate/", {"password": "newpass456"}, format="json")
    check("注销账号", r.status_code == 200)

    # 管理员用户/角色
    r = ca.get("/api/auth/admin/users/")
    check("管理员用户列表", r.status_code == 200 and r.data.get("total", 0) >= 2)
    r = ca.get("/api/auth/admin/users/", {"status": "active"})
    check("用户状态筛选", r.status_code == 200)
    r = ca.post("/api/auth/admin/users/create/", {"username": f"made{ts}", "password": "made123456"}, format="json")
    check("管理员创建用户", r.status_code == 201)
    made_id = r.data["user"]["id"]
    r = ca.post(f"/api/auth/admin/users/{made_id}/reset-password/", {"new_password": "reset123456"}, format="json")
    check("管理员重置密码", r.status_code == 200)
    r = ca.post("/api/auth/admin/users/batch/", {"action": "disable", "user_ids": [made_id]}, format="json")
    check("批量禁用用户", r.status_code == 200)
    r = ca.post("/api/auth/admin/users/batch/", {"action": "enable", "user_ids": [made_id]}, format="json")
    check("批量启用用户", r.status_code == 200)
    r = ca.patch(f"/api/auth/admin/users/{made_id}/", {"storage_quota_mb": 512}, format="json")
    check("管理员编辑用户", r.status_code == 200 and r.data["user"]["storage_quota_mb"] == 512)
    r = ca.get("/api/auth/admin/roles/")
    check("角色列表", r.status_code == 200 and r.data.get("total", 0) >= 2)
    r = ca.post("/api/auth/admin/roles/", {"name": f"自定义{ts}", "code": f"role{ts}"}, format="json")
    check("创建角色", r.status_code == 201)
    r = ca.get("/api/auth/admin/permissions/", {"grouped": "1"})
    check("权限点分组", r.status_code == 200 and "grouped" in r.data)
    r = ca.get("/api/auth/admin/online/")
    check("在线用户", r.status_code == 200 and "list" in r.data)

    # ---------- 2. 核心：通知/公告/日志/搜索/设置/健康 ----------
    r = c.get("/api/core/notifications/")
    check("通知列表", r.status_code == 200)
    r = c.get("/api/core/notifications/unread-count/", {"grouped": "1"})
    check("未读分组计数", r.status_code == 200 and "grouped" in r.data)
    r = c.post("/api/core/notifications/read/", {}, format="json")
    check("通知全部已读", r.status_code == 200)
    r = c.post("/api/core/notifications/delete/", {"scope": "read"}, format="json")
    check("清空已读通知", r.status_code == 200)
    r = c.get("/api/core/notifications/settings/")
    check("通知偏好读取", r.status_code == 200)
    r = c.post("/api/core/notifications/settings/", {"settings": {"message": False}}, format="json")
    check("通知偏好更新", r.status_code == 200)
    r = ca.post("/api/core/admin/announcements/", {"title": "测试公告", "content": "内容", "level": "important"}, format="json")
    check("发布公告", r.status_code == 201)
    ann_id = r.data["id"]
    r = c.get("/api/core/announcements/")
    check("公告列表", r.status_code == 200 and r.data.get("total", 0) >= 1)
    r = c.post(f"/api/core/announcements/{ann_id}/read/", {}, format="json")
    check("公告标记已读", r.status_code == 200)
    r = ca.patch(f"/api/core/admin/announcements/{ann_id}/", {"is_pinned": True}, format="json")
    check("公告更新", r.status_code == 200 and r.data["is_pinned"] is True)
    r = c.get("/api/core/my-logs/")
    check("我的操作日志", r.status_code == 200)
    r = ca.get("/api/core/logs/")
    check("管理员操作日志", r.status_code == 200 and r.data.get("total", 0) > 0)
    r = ca.get("/api/core/logs/stats/")
    check("日志聚合统计", r.status_code == 200 and "by_module" in r.data)
    r = ca.get("/api/core/logs/export/")
    check("日志导出CSV", r.status_code == 200 and r["Content-Type"].startswith("text/csv"))
    r = c.get("/api/core/search/", {"q": "测试"})
    check("全局搜索", r.status_code == 200 and "files" in r.data)
    r = APIClient().get("/api/core/health/")
    check("健康检查", r.status_code == 200 and r.data.get("db") is True)
    r = APIClient().get("/api/core/settings/public/")
    check("公开站点设置", r.status_code == 200)
    r = ca.post("/api/core/admin/settings/", {"settings": {"site_name": "协作平台"}}, format="json")
    check("管理员站点设置", r.status_code == 200)

    # ---------- 3. 文件 ----------
    r = c.post("/api/files/folders/", {"name": "项目资料"}, format="json")
    check("创建文件夹", r.status_code == 201)
    folder_id = r.data["id"]
    r = c.get("/api/files/folders/tree/")
    check("文件夹树", r.status_code == 200 and isinstance(r.data["tree"], list))
    r = c.get(f"/api/files/folders/{folder_id}/breadcrumb/")
    check("文件夹面包屑", r.status_code == 200 and r.data["breadcrumbs"][-1]["name"] == "项目资料")
    r = c.patch(f"/api/files/folders/{folder_id}/", {"color": "blue"}, format="json")
    check("文件夹改色", r.status_code == 200 and r.data["color"] == "blue")

    content = b"Hello All-in-One Platform! " * 1000
    sha1 = hashlib.sha1(content).hexdigest()
    half = len(content) // 2
    r = c.post("/api/files/upload/init/", {"filename": "hello.txt", "folder_id": folder_id, "file_size": len(content),
                                          "chunk_size": half + 1, "total_chunks": 2, "sha1": sha1}, format="json")
    check("分片上传初始化", r.status_code == 200 and r.data.get("sec_pass") is False, str(r.data)[:120])
    upload_id = r.data.get("upload_id")
    r = c.get("/api/files/upload/status/", {"upload_id": upload_id})
    check("上传进度查询", r.status_code == 200 and r.data["total_chunks"] == 2)
    for i, part in enumerate([content[:half], content[half:]]):
        rr = c.post("/api/files/upload/chunk/", {"upload_id": upload_id, "index": i, "chunk": io.BytesIO(part)}, format="multipart")
        check(f"上传分片{i}", rr.status_code == 200)
    r = c.post("/api/files/upload/complete/", {"upload_id": upload_id}, format="json")
    check("分片合并", r.status_code == 200 and r.data["file"]["kind"] == "text", str(r.data)[:150])
    file_id = r.data["file"]["id"]
    r = c.post("/api/files/upload/init/", {"filename": "h2.txt", "folder_id": folder_id, "file_size": len(content),
                                          "chunk_size": half + 1, "total_chunks": 2, "sha1": sha1}, format="json")
    check("秒传命中", r.status_code == 200 and r.data.get("sec_pass") is True)
    r = c.post("/api/files/create-text/", {"name": "在线笔记.txt", "content": "abc", "folder": folder_id}, format="json")
    check("在线新建文本", r.status_code == 201)
    text_id = r.data["id"]
    r = c.post(f"/api/files/{text_id}/save-text/", {"content": "abcd更新"}, format="json")
    check("在线保存文本", r.status_code == 200 and r.data["file"]["size"] >= 7)
    r = c.get(f"/api/files/{file_id}/preview/")
    check("文本预览", r.status_code == 200 and "All-in-One" in r.data.get("content", ""))
    r = c.post(f"/api/files/{file_id}/star/", {}, format="json")
    check("收藏切换", r.status_code == 200 and r.data["is_star"] is True)
    r = c.patch(f"/api/files/{file_id}/", {"description": "重要"}, format="json")
    check("文件备注", r.status_code == 200 and r.data["description"] == "重要")
    r = c.post(f"/api/files/{file_id}/copy/", {}, format="json")
    check("文件复制", r.status_code == 201 and "副本" in r.data["name"])
    copy_id = r.data["id"]
    r = c.get("/api/files/starred/")
    check("收藏列表", r.status_code == 200 and r.data["total"] >= 1)
    r = c.get("/api/files/recent/")
    check("最近访问", r.status_code == 200 and r.data["total"] >= 1)
    r = c.get("/api/files/analysis/")
    check("存储分析", r.status_code == 200 and "by_kind" in r.data and "quota_used_pct" in r.data)
    r = c.post("/api/files/batch/", {"action": "star", "file_ids": [text_id]}, format="json")
    check("批量收藏", r.status_code == 200)
    r = c.post("/api/files/batch-download/", {"file_ids": [file_id, text_id]}, format="json")
    check("打包下载zip", r.status_code == 200 and r["Content-Type"] == "application/zip")
    r = c.post("/api/files/batch/", {"action": "trash", "file_ids": [copy_id]}, format="json")
    check("批量删除进回收站", r.status_code == 200)
    r = c.post("/api/files/trash/action/", {"action": "restore", "file_ids": [copy_id]}, format="json")
    check("回收站还原到原目录", r.status_code == 200)
    r = c.post("/api/files/batch/", {"action": "delete_forever", "file_ids": [copy_id]}, format="json")
    check("批量彻底删除", r.status_code == 200)
    r = c.post("/api/files/trash/auto-clean/", {}, format="json")
    check("回收站到期清理", r.status_code == 200)

    r = c.post("/api/files/shares/create/", {"file_id": file_id, "permission": "download", "expire_hours": 2,
                                             "password": "pw", "max_downloads": 5}, format="json")
    check("创建带密码共享", r.status_code == 201 and r.data["has_password"] is True)
    token = r.data["token"]
    anon = APIClient()
    r = anon.get(f"/share/{token}/")
    check("共享需密码", r.status_code == 401 and r.data.get("need_password"))
    r = anon.get(f"/share/{token}/", {"password": "pw"})
    check("密码正确可访问", r.status_code == 200 and r.data.get("name") == "hello.txt")
    r = c.get("/api/files/shares/", {"status": "active"})
    check("共享链接筛选", r.status_code == 200 and r.data["total"] >= 1)
    r = c.patch(f"/api/files/shares/{token}/", {"permission": "view"}, format="json")
    check("共享链接更新", r.status_code == 200 and r.data["permission"] == "view")
    r = c.patch(f"/api/files/shares/{token}/", {"is_revoked": True}, format="json")
    check("共享链接失效", r.status_code == 200 and r.data["is_revoked"] is True)

    # ---------- 4. 笔记 ----------
    r = c.post("/api/notes/", {"title": "第一篇", "content": "# 标题\n正文", "tags": ["工作"]}, format="json")
    check("创建笔记", r.status_code == 201)
    note_id = r.data["id"]
    r = c.patch(f"/api/notes/{note_id}/", {"content": "# 标题\n更新内容"}, format="json")
    check("更新笔记产生版本", r.status_code == 200 and r.data["version"] == 2)
    r = c.get(f"/api/notes/{note_id}/versions/")
    check("版本历史", r.status_code == 200 and r.data["total"] >= 1)
    r = c.get(f"/api/notes/{note_id}/versions/diff/", {"from": 1, "to": 1})
    check("版本对比", r.status_code == 200 and "diff" in r.data)
    r = c.post(f"/api/notes/{note_id}/rollback/1/", {}, format="json")
    check("版本回滚", r.status_code == 200)
    r = c.get(f"/api/notes/{note_id}/outline/")
    check("笔记大纲", r.status_code == 200 and r.data["outline"][0]["level"] == 1)
    r = c.get("/api/notes/tree/")
    check("笔记树", r.status_code == 200 and isinstance(r.data["tree"], list))
    r = c.post("/api/notes/tags/", {"name": "灵感", "color": "red"}, format="json")
    check("新建标签", r.status_code == 201)
    tag_id = r.data["id"]
    r = c.get("/api/notes/tags/")
    check("标签列表(含用量)", r.status_code == 200 and r.data["total"] >= 1)
    r = c.patch(f"/api/notes/tags/{tag_id}/", {"name": "灵感2"}, format="json")
    check("标签重命名", r.status_code == 200 and r.data["name"] == "灵感2")
    r = c.get("/api/notes/stats/")
    check("笔记统计", r.status_code == 200 and "total_words" in r.data)
    r = c.get("/api/notes/templates/")
    check("笔记模板列表", r.status_code == 200 and len(r.data["list"]) >= 5)
    r = c.post("/api/notes/from-template/", {"key": "meeting"}, format="json")
    check("从模板创建", r.status_code == 201 and "会议" in r.data["title"])
    tpl_note = r.data["id"]
    r = c.post(f"/api/notes/{note_id}/copy/", {}, format="json")
    check("笔记复制", r.status_code == 201)
    r = c.post("/api/notes/batch/", {"action": "favorite", "note_ids": [tpl_note]}, format="json")
    check("笔记批量收藏", r.status_code == 200)
    r = c.get(f"/api/notes/{note_id}/export/")
    check("导出单篇MD", r.status_code == 200 and r["Content-Type"].startswith("text/markdown"))
    r = c.get("/api/notes/export-all/")
    check("导出全部zip", r.status_code == 200 and r["Content-Type"] == "application/zip")
    r = c.delete(f"/api/notes/{tpl_note}/")
    check("笔记软删除", r.status_code == 200)
    r = c.get("/api/notes/trash/")
    check("笔记回收站", r.status_code == 200 and r.data["total"] >= 1)
    r = c.post("/api/notes/batch/", {"action": "restore", "note_ids": [tpl_note]}, format="json")
    check("笔记回收站恢复", r.status_code == 200)
    r = c.delete(f"/api/notes/tags/{tag_id}/")
    check("标签删除", r.status_code == 200)

    # ---------- 5. 项目看板 ----------
    r = c.post("/api/projects/", {"name": "测试项目", "description": "d"}, format="json")
    check("创建项目(默认三列)", r.status_code == 201)
    pid = r.data["id"]
    r = c.get(f"/api/projects/{pid}/boards/")
    check("看板三列", r.status_code == 200 and len(r.data["boards"]) == 3)
    boards = r.data["boards"]
    bid = boards[0]["id"]
    r = c.post(f"/api/projects/{pid}/boards/", {"name": "验收"}, format="json")
    check("新增看板列", r.status_code == 201)
    new_bid = r.data["id"]
    order = [b["id"] for b in boards] + [new_bid]
    r = c.post(f"/api/projects/{pid}/boards/reorder/", {"orders": order[::-1]}, format="json")
    check("看板列排序", r.status_code == 200)
    r = c.post(f"/api/projects/boards/{bid}/cards/", {"title": "写文档", "priority": "high", "story_points": 5}, format="json")
    check("创建任务", r.status_code == 201)
    card_id = r.data["id"]
    r = c.patch(f"/api/projects/cards/{card_id}/", {"status": "doing"}, format="json")
    check("任务开始(记录started_at)", r.status_code == 200 and r.data["started_at"] is not None)
    r = c.post(f"/api/projects/cards/{card_id}/subtasks/", {"title": "子任务1"}, format="json")
    check("创建子任务", r.status_code == 201)
    sid = r.data["id"]
    r = c.patch(f"/api/projects/cards/{card_id}/subtasks/{sid}/", {"is_done": True}, format="json")
    check("完成子任务", r.status_code == 200 and r.data["is_done"] is True)
    r = c.post(f"/api/projects/cards/{card_id}/worklogs/", {"minutes": 30, "note": "开发"}, format="json")
    check("登记工时", r.status_code == 201)
    r = c.get(f"/api/projects/cards/{card_id}/worklogs/")
    check("工时汇总", r.status_code == 200 and r.data["total_minutes"] == 30)
    r = c.post(f"/api/projects/cards/{card_id}/comments/", {"content": "加油"}, format="json")
    check("发表评论", r.status_code == 201)
    cmid = r.data["id"]
    r = c.patch(f"/api/projects/cards/{card_id}/comments/{cmid}/", {"content": "改一下"}, format="json")
    check("编辑评论", r.status_code == 200 and r.data["content"] == "改一下")
    r = c.post(f"/api/projects/cards/{card_id}/copy/", {}, format="json")
    check("复制任务(带子任务)", r.status_code == 201 and r.data["subtask_total"] >= 1)
    copy_card = r.data["id"]
    doing_bid = boards[1]["id"]
    r = c.post(f"/api/projects/cards/{card_id}/move/", {"board_id": doing_bid, "index": 0}, format="json")
    check("拖拽移动卡片", r.status_code == 200 and r.data["card"]["board"] == doing_bid)
    r = c.patch(f"/api/projects/cards/{card_id}/", {"status": "done"}, format="json")
    check("任务完成(completed_at)", r.status_code == 200 and r.data["completed_at"] is not None)
    r = c.get(f"/api/projects/{pid}/search/", {"q": "文档"})
    check("项目内任务搜索", r.status_code == 200 and r.data["total"] >= 1)
    r = c.get(f"/api/projects/{pid}/search/", {"priority": "high"})
    check("任务优先级筛选", r.status_code == 200)
    r = c.post("/api/projects/cards/batch/", {"project_id": pid, "action": "priority", "card_ids": [copy_card], "priority": "low"}, format="json")
    check("任务批量改优先级", r.status_code == 200)
    r = c.get(f"/api/projects/{pid}/stats/")
    check("项目统计", r.status_code == 200 and "by_status" in r.data)
    r = c.get(f"/api/projects/{pid}/calendar/")
    check("任务日历聚合", r.status_code == 200 and "days" in r.data)
    r = c.get("/api/projects/my-tasks/")
    check("我的任务(跨项目)", r.status_code == 200 and "counts" in r.data)
    r = c.post(f"/api/projects/{pid}/members/", {"user_ids": [made_id]}, format="json")
    check("添加项目成员", r.status_code == 200)
    r = c.delete(f"/api/projects/{pid}/members/?user_id={made_id}")
    check("移除项目成员", r.status_code == 200)
    r = c.post(f"/api/projects/{pid}/clone/", {}, format="json")
    check("克隆项目", r.status_code == 201 and r.data["board_count"] == 4)
    r = c.post(f"/api/projects/{pid}/star/", {}, format="json")
    check("项目收藏", r.status_code == 200)
    r = c.get(f"/api/projects/{pid}/activities/")
    check("项目活动流", r.status_code == 200 and r.data["total"] >= 1)
    r = c.delete(f"/api/projects/cards/{copy_card}/comments/{cmid}/") if False else None
    r = c.delete("/api/projects/cards/batch/", ) if False else None

    # ---------- 6. IM ----------
    r = c.post("/api/im/sessions/create/", {"type": "direct", "member_ids": [1]}, format="json")
    check("创建单聊(兼容direct)", r.status_code in (200, 201), str(r.status_code))
    sid = r.data["id"]
    r = c.post(f"/api/im/sessions/{sid}/send/", {"content": "你好管理员", "msg_type": "text"}, format="json")
    check("发送消息", r.status_code == 201 and r.data["msg_type"] == "text")
    msg_id = r.data["id"]
    r = c.get(f"/api/im/sessions/{sid}/messages/")
    check("消息历史", r.status_code == 200 and r.data["total"] >= 1)
    r = c.post(f"/api/im/sessions/{sid}/setting/", {"is_muted": True, "is_pinned": True, "draft": "草稿", "mark_read": True}, format="json")
    check("会话免打扰/置顶/草稿/已读", r.status_code == 200 and r.data["is_pinned"] is True)
    r = c.post(f"/api/im/messages/{msg_id}/recall/", {}, format="json")
    check("撤回消息", r.status_code == 200)
    r = c.post(f"/api/im/sessions/{sid}/send/", {"content": "再发一条"}, format="json")
    msg2 = r.data["id"]
    r = c.post(f"/api/im/messages/{msg2}/delete/", {}, format="json")
    check("消息对自己删除", r.status_code == 200)
    r = c.post("/api/im/sessions/", {"type": "group", "name": "项目群", "member_ids": [made_id]}, format="json")
    check("创建群聊", r.status_code == 201)
    gid = r.data["id"]
    r = c.post(f"/api/im/sessions/{sid}/send/", {"content": "转发我"}, format="json")
    fwd_msg = r.data["id"]
    r = c.post(f"/api/im/messages/{fwd_msg}/forward/", {"session_ids": [gid]}, format="json")
    check("转发消息", r.status_code == 200 and len(r.data["message_ids"]) == 1)
    r = c.get("/api/im/sessions/search-messages/", {"q": "你好"})
    check("全局消息搜索", r.status_code == 200)
    r = c.get("/api/im/sessions/unread-summary/")
    check("未读汇总", r.status_code == 200 and "per_session" in r.data)
    r = c.post(f"/api/im/sessions/{gid}/transfer/", {"user_id": made_id}, format="json")
    check("转让群主", r.status_code == 200)
    r = ca.post(f"/api/im/sessions/{gid}/leave/", {}, format="json")  # admin 非成员，预期404
    check("非成员退群被拒", r.status_code == 404)
    # 群主(c)解散群
    r = c.post(f"/api/im/sessions/{gid}/leave/", {}, format="json")
    check("群主解散群聊", r.status_code == 200)

    # ---------- 7. 工具 ----------
    r = c.get("/api/tools/catalog/")
    check("工具目录(>=30)", r.status_code == 200 and r.data["total"] >= 30, str(r.data.get("total")))
    r = c.post("/api/tools/run/", {"tool": "json-format", "text": '{"b":1,"a":2}'}, format="json")
    check("统一运行JSON格式化", r.status_code == 200 and '"a": 2' in r.data["result"]["result"])
    r = c.post("/api/tools/hash/", {"text": "abc", "alg": "md5"}, format="json")
    check("直达工具路径(MD5)", r.status_code == 200 and r.data["result"]["md5"] == "900150983cd24fb0d6963f7d28e17f72")
    r = c.post("/api/tools/run/", {"tool": "text-dedupe", "text": "a\na\nb"}, format="json")
    check("文本去重", r.status_code == 200 and r.data["result"]["removed"] == 1)
    r = c.post("/api/tools/run/", {"tool": "number-base", "value": "255", "from_base": 10}, format="json")
    check("进制转换", r.status_code == 200 and r.data["result"]["16"] == "FF")
    r = c.post("/api/tools/run/", {"tool": "morse", "text": "SOS", "mode": "encode"}, format="json")
    morse = r.data["result"]["result"]
    r2 = c.post("/api/tools/run/", {"tool": "morse", "text": morse, "mode": "decode"}, format="json")
    check("摩斯编解码", r.status_code == 200 and r2.data["result"]["result"] == "SOS")
    from rest_framework_simplejwt.tokens import RefreshToken
    from django.contrib.auth import get_user_model
    tok = str(RefreshToken.for_user(get_user_model().objects.get(username=new_uname)))
    r = c.post("/api/tools/run/", {"tool": "jwt-decode", "token": tok}, format="json")
    check("JWT解析", r.status_code == 200 and int(r.data["result"]["payload"]["user_id"]) >= 1)
    r = c.post("/api/tools/run/", {"tool": "password-strength", "password": "Abc12345!@"}, format="json")
    check("密码强度", r.status_code == 200 and r.data["result"]["score"] >= 4)
    r = c.post("/api/tools/run/", {"tool": "luhn", "number": "49927398716"}, format="json")
    check("银行卡Luhn校验", r.status_code == 200 and r.data["result"]["valid"] is True)
    # 构造合法身份证
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    checks_code = ["1", "0", "X", "9", "8", "7", "6", "5", "4", "3", "2"]
    prefix = "11010519900307"
    s = sum(int(prefix[i]) * weights[i] for i in range(14)) + int("23"[0]) * weights[14] + int("23"[1]) * weights[15]
    # 直接用 17 位 11010519900307231 计算
    body = "11010519900307231"
    s = sum(int(body[i]) * weights[i] for i in range(17))
    valid_id = body + checks_code[s % 11]
    r = c.post("/api/tools/run/", {"tool": "idcard", "idcard": valid_id}, format="json")
    check("身份证校验", r.status_code == 200 and r.data["result"]["valid"] is True, str(r.data))
    r = c.post("/api/tools/run/", {"tool": "date-diff", "start": "2026-01-01", "end": "2026-01-11"}, format="json")
    check("日期相差", r.status_code == 200 and r.data["result"]["days"] == 10)
    r = c.post("/api/tools/run/", {"tool": "unit-convert", "value": 1, "from": "m", "to": "cm", "table": "length"}, format="json")
    check("单位换算", r.status_code == 200 and r.data["result"]["result"] == 100)
    r = c.post("/api/tools/run/", {"tool": "color-palette", "hex": "#0ea5e9"}, format="json")
    check("配色生成", r.status_code == 200 and len(r.data["result"]["palette"]) == 5)
    r = c.post("/api/tools/run/", {"tool": "regex-test", "pattern": r"\d+", "text": "a1b22"}, format="json")
    check("正则匹配", r.status_code == 200 and r.data["result"]["count"] == 2)
    r = c.post("/api/tools/run/", {"tool": "text-count", "text": "你好 world"}, format="json")
    check("文本统计", r.status_code == 200 and r.data["result"]["cjk"] == 2)
    r = c.post("/api/tools/run/", {"tool": "rot13", "text": "hello"}, format="json")
    check("ROT13", r.status_code == 200 and r.data["result"]["result"] == "uryyb")

    # ---------- 8. Dashboard ----------
    r = c.get("/api/dashboard/stats/")
    check("个人统计", r.status_code == 200 and "files" in r.data)
    r = c.get("/api/dashboard/personal-trend/")
    check("个人14天趋势", r.status_code == 200 and len(r.data["labels"]) == 14)
    r = c.get("/api/dashboard/my-task-distribution/")
    check("我的任务分布", r.status_code == 200 and "by_status" in r.data)
    r = c.get("/api/dashboard/file-type-distribution/")
    check("文件类型分布", r.status_code == 200 and "list" in r.data)
    r = c.get("/api/dashboard/todo-aggregate/")
    check("待办聚合", r.status_code == 200 and "overdue" in r.data)
    r = ca.get("/api/dashboard/admin/global/")
    check("管理员全局统计", r.status_code == 200 and r.data.get("users", 0) >= 2)
    r = ca.get("/api/dashboard/admin/trend/")
    check("管理员操作趋势", r.status_code == 200 and len(r.data["labels"]) == 14)
    r = ca.get("/api/dashboard/admin/user-growth/")
    check("用户增长30天", r.status_code == 200 and len(r.data["labels"]) == 30)
    r = ca.get("/api/dashboard/admin/module-usage/")
    check("模块使用排行", r.status_code == 200 and "by_module" in r.data)

    # ---------- 9. 权限拒绝 ----------
    r = c.get("/api/auth/admin/users/")
    check("普通用户访问后台被拒", r.status_code == 403)

    print(f"\n结果：通过 {len(passed)} 项，失败 {len(failed)} 项")
    if failed:
        print("失败项：", failed)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
