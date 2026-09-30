# -*- coding: utf-8 -*-
"""代码工坊路由（v6）。

约定与 devtools / dataintel / officesuite 一致：
- `SUBSYSTEMS` 描述能力分组，供前端目录页动态渲染；
- `VIEWS` 把「路由字符串 → 视图函数」显式映射，避免手写 path 出错；
- 结尾断言接口数量，防止后续改动无声破坏契约。
"""
from django.urls import include, path

from . import views_ai as A
from . import views_core as C
from . import views_eng as E
from . import views_learn as L

# 子系统定义：[key, 名称, 描述, [端点]]
SUBSYSTEMS = [
    ["meta", "元信息", "运行时探测与语言清单", [
        "catalog/", "runtimes/", "languages/", "templates/",
    ]],
    ["workspace", "工作区", "代码工程的容器", [
        "workspaces/", "workspaces/create/", "workspaces/<int:pk>/",
        "workspaces/<int:pk>/star/", "workspaces/<int:pk>/clone/",
    ]],
    ["file", "代码文件", "增删改查、树、批量", [
        "files/", "files/create/", "files/<int:pk>/", "files/<int:pk>/favorite/",
        "files/<int:pk>/entry/", "files/<int:pk>/move/", "files/batch/", "files/tree/",
    ]],
    ["version", "版本历史", "快照 / diff / 回滚", [
        "files/<int:pk>/versions/", "files/<int:pk>/versions/create/",
        "files/<int:pk>/versions/diff/", "files/<int:pk>/versions/<int:vid>/rollback/",
        "files/<int:pk>/versions/<int:vid>/delete/",
    ]],
    ["run", "安全执行", "执行 / REPL / 历史 / 统计 / 参数预设", [
        "run/", "run/repl/", "run/history/", "run/<int:pk>/", "run/<int:pk>/delete/",
        "run/clear/", "run/stats/", "run/presets/", "run/presets/<int:pk>/",
    ]],
    ["judge", "判题", "多用例判定与排行榜", [
        "judge/", "judge/history/", "judge/<int:pk>/", "leaderboard/",
    ]],
    ["snippet", "代码片段库", "可复用片段、标签与收藏夹分组", [
        "snippets/", "snippets/create/", "snippets/<int:pk>/", "snippets/<int:pk>/copy/",
        "snippets/tags/", "snippets/from-file/", "snippets/folders/",
    ]],
    ["analyze", "静态分析", "指标 / 大纲 / 复杂度 / 质量 / 统计卡", [
        "analyze/", "outline/", "complexity/", "quality/", "flow/",
        "similarity/", "secret-scan/", "refactor-hints/", "code-stats/",
    ]],
    ["ai", "智能辅助", "生成 / 解释 / 找bug / 重构 / 测试", [
        "ai/status/", "ai/generate/", "ai/transform/", "ai/error-explain/",
        "ai/regex/", "ai/nl2sql/", "ai/learning-path/", "ai/chat-edit/",
        "ai/inline/", "ai/apply/<int:pk>/",
        "ai/translate/", "ai/comment/", "ai/optimize/", "ai/testgen/", "ai/summary/",
    ]],
    ["collab", "协作", "行评论与协同状态", [
        "files/<int:pk>/comments/", "files/<int:pk>/comments/<int:cid>/resolve/",
        "files/<int:pk>/comments/<int:cid>/delete/",
        "files/<int:pk>/collab/", "files/<int:pk>/collab/ws/",
    ]],
    ["share", "分享", "只读/可运行分享链接", [
        "shares/", "shares/create/", "shares/<str:token>/", "shares/<str:token>/revoke/",
    ]],
    ["export", "导出", "zip 打包与单文件下载", [
        "export/zip/", "export/file/<int:pk>/",
    ]],
    ["daily", "每日一题", "今日题目 / 提交 / 打卡历史 / 站内提醒", [
        "daily/today/", "daily/submit/", "daily/history/", "daily/reminder/",
    ]],
    ["achievement", "成就徽章", "徽章列表与解锁进度", [
        "achievements/", "achievements/mine/",
    ]],
    ["wrongbook", "错题本", "错题收录与复习", [
        "wrongbook/", "wrongbook/add/", "wrongbook/<int:pk>/review/",
        "wrongbook/<int:pk>/delete/",
    ]],
    ["learnpath", "学习路径", "生成 / 勾选进度 / 管理", [
        "paths/", "paths/generate/", "paths/<int:pk>/",
        "paths/<int:pk>/tick/", "paths/<int:pk>/delete/",
    ]],
    ["arena", "竞技场", "战力榜 / 随机挑战 / 提交", [
        "arena/board/", "arena/challenge/", "arena/submit/",
    ]],
    ["learn", "学习总览", "个人学习看板聚合", [
        "learn/overview/",
    ]],
    ["engineering", "工程化", "归属统计 / TODO 聚合 / diff / 洞察", [
        "blame/<int:pk>/", "todos/", "diff/", "insights/",
        "contributors/", "files/<int:pk>/versions/<int:vid>/side-by-side/",
    ]],
]

# 路由字符串 → 视图函数
VIEWS = {
    # meta
    "catalog/": C.code_catalog,
    "runtimes/": C.runtimes,
    "languages/": C.languages,
    "templates/": C.templates,
    # workspace
    "workspaces/": C.workspace_list,
    "workspaces/create/": C.workspace_create,
    "workspaces/<int:pk>/": C.workspace_detail,
    "workspaces/<int:pk>/update/": C.workspace_update,
    "workspaces/<int:pk>/delete/": C.workspace_delete,
    "workspaces/<int:pk>/star/": C.workspace_star,
    "workspaces/<int:pk>/clone/": C.workspace_clone,
    # file
    "files/": C.file_list,
    "files/create/": C.file_create,
    "files/batch/": C.file_batch,
    "files/tree/": C.file_tree,
    "files/<int:pk>/": C.file_detail,
    "files/<int:pk>/update/": C.file_update,
    "files/<int:pk>/delete/": C.file_delete,
    "files/<int:pk>/favorite/": C.file_favorite,
    "files/<int:pk>/entry/": C.file_entry,
    "files/<int:pk>/move/": C.file_move,
    # version
    "files/<int:pk>/versions/": C.version_list,
    "files/<int:pk>/versions/create/": C.version_create,
    "files/<int:pk>/versions/diff/": C.version_diff,
    "files/<int:pk>/versions/<int:vid>/rollback/": C.version_rollback,
    "files/<int:pk>/versions/<int:vid>/delete/": C.version_delete,
    # run
    "run/": C.run,
    "run/repl/": C.run_repl,
    "run/history/": C.run_history,
    "run/clear/": C.run_clear,
    "run/stats/": C.run_stats,
    "run/presets/": C.run_presets,
    "run/presets/<int:pk>/": C.run_preset_detail,
    "run/<int:pk>/": C.run_detail,
    "run/<int:pk>/delete/": C.run_delete,
    # judge
    "judge/": C.judge,
    "judge/history/": C.judge_history,
    "judge/<int:pk>/": C.judge_detail,
    "leaderboard/": C.leaderboard,
    # snippet
    "snippets/": C.snippet_list,
    "snippets/create/": C.snippet_create,
    "snippets/tags/": C.snippet_tags,
    "snippets/folders/": C.snippet_folders,
    "snippets/from-file/": C.snippet_from_file,
    "snippets/<int:pk>/": C.snippet_detail,
    "snippets/<int:pk>/update/": C.snippet_update,
    "snippets/<int:pk>/delete/": C.snippet_delete,
    "snippets/<int:pk>/copy/": C.snippet_copy,
    # analyze
    "analyze/": A.analyze,
    "outline/": A.outline,
    "complexity/": A.complexity,
    "quality/": A.quality,
    "flow/": A.flow,
    "similarity/": A.similarity,
    "secret-scan/": A.secret_scan,
    "refactor-hints/": A.refactor_hints,
    "code-stats/": A.code_stats,
    # ai
    "ai/status/": A.ai_status,
    "ai/generate/": A.ai_generate,
    "ai/transform/": A.ai_transform,
    "ai/error-explain/": A.ai_error_explain,
    "ai/regex/": A.ai_regex,
    "ai/nl2sql/": A.ai_nl2sql,
    "ai/learning-path/": A.ai_learning_path,
    "ai/chat-edit/": A.ai_chat_edit,
    "ai/inline/": A.ai_inline,
    "ai/apply/<int:pk>/": A.ai_complete_apply,
    # ai（L3 补齐：翻译 / 注释 / 优化 / 单测 / 摘要）
    "ai/translate/": A.ai_translate,
    "ai/comment/": A.ai_comment,
    "ai/optimize/": A.ai_optimize,
    "ai/testgen/": A.ai_testgen,
    "ai/summary/": A.ai_summary,
    "ai/review/": A.ai_review,
    # collab
    "files/<int:pk>/comments/": A.comment_list,
    "files/<int:pk>/comments/create/": A.comment_create,
    "files/<int:pk>/comments/<int:cid>/resolve/": A.comment_resolve,
    "files/<int:pk>/comments/<int:cid>/delete/": A.comment_delete,
    "files/<int:pk>/collab/": A.collab_state,
    "files/<int:pk>/collab/ws/": A.collab_ws_info,
    # share
    "shares/": A.share_list,
    "shares/create/": A.share_create,
    "shares/<str:token>/": A.share_update,
    "shares/<str:token>/revoke/": A.share_revoke,
    # export
    "export/zip/": C.export_zip,
    "export/file/<int:pk>/": C.export_file,
    # daily（L5 每日一题）
    "daily/today/": L.daily_today,
    "daily/submit/": L.daily_submit,
    "daily/history/": L.daily_history,
    "daily/reminder/": L.daily_reminder,
    # achievement（L5 成就徽章）
    "achievements/": L.achievement_list,
    "achievements/mine/": L.achievement_mine,
    # wrongbook（L5 错题本）
    "wrongbook/": L.wrong_list,
    "wrongbook/add/": L.wrong_add,
    "wrongbook/<int:pk>/review/": L.wrong_review,
    "wrongbook/<int:pk>/delete/": L.wrong_delete,
    # learnpath（L5 学习路径）
    "paths/": L.path_list,
    "paths/generate/": L.path_generate,
    "paths/<int:pk>/": L.path_detail,
    "paths/<int:pk>/tick/": L.path_tick,
    "paths/<int:pk>/delete/": L.path_delete,
    # arena（L5 竞技场）
    "arena/board/": L.arena_board,
    "arena/challenge/": L.arena_challenge,
    "arena/submit/": L.arena_submit,
    # learn（L5 学习总览）
    "learn/overview/": L.learn_overview,
    # engineering（L4 工程化收口）
    "blame/<int:pk>/": E.blame,
    "todos/": E.todos,
    "diff/": E.diff_view,
    "insights/": E.insights,
    "contributors/": E.contributors,
    "files/<int:pk>/versions/<int:vid>/side-by-side/": E.version_side_by_side,
}

urlpatterns = [path(route, view) for route, view in VIEWS.items()]

# 公开分享（无需登录），挂到 /api/share/code/<token>/
public_urlpatterns = [
    path("share/code/<str:token>/", A.public_share_view, name="code_public_share"),
    path("share/code/<str:token>/run/", A.public_share_run, name="code_public_share_run"),
]

# 契约断言：接口数量变化时必须显式确认
# v6 基础 75 + L5 竞技教学 18 + L3 AI 补齐 5 + L4 工程化 6 = 104
# F669–F680 能力扩展 +5：snippets/folders · run/presets(2) · code-stats · daily/reminder
_EXPECTED = 110
assert len(urlpatterns) == _EXPECTED, (
    f"code 接口数应为 {_EXPECTED}，实际 {len(urlpatterns)}"
)
