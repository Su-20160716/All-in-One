"""索引与双链的自动维护（post_save / post_delete 信号）

放在 core 里统一接线，业务 app 不需要自己写索引调用：
- 笔记、文件、项目、任务保存后 → 写入/更新全文索引
- 笔记保存后 → 重建 [[双链]] 关系 + 解析反向链接
- 删除后 → 移除索引

注意：所有索引动作都包在 try/except 中，索引失败绝不影响业务写入。
"""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver


def _safe(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except Exception:
        pass


@receiver(post_save, sender="notes.Note")
def on_note_saved(sender, instance, **kwargs):
    from core.search import index_document

    _safe(index_document, "note", instance.id, instance.owner_id, instance.title, instance.content,
          summary=instance.content)
    # 双链：正文变化后重建出链；标题变化后把别的笔记指向本标题的悬浮链接接上
    from notes.links import rebuild_links_for_note, resolve_dangling_links

    _safe(rebuild_links_for_note, instance)
    _safe(resolve_dangling_links, instance.owner_id, instance.title)


@receiver(post_delete, sender="notes.Note")
def on_note_deleted(sender, instance, **kwargs):
    from core.search import remove_document

    _safe(remove_document, "note", instance.id)
    _safe(lambda: __import__("notes.links", fromlist=["x"]).NoteLink.objects.filter(
        source_id=instance.id
    ).delete())


@receiver(post_save, sender="files.FileMeta")
def on_file_saved(sender, instance, **kwargs):
    """文件只在「文本可抽取」且体积合理时建立索引，避免保存时卡顿"""
    from core.search import can_index, index_document

    if instance.is_deleted or not can_index(instance.ext):
        return

    from django.conf import settings

    limit = int(getattr(settings, "SEARCH_FILE_MAX_MB", 20)) * 1024 * 1024
    if instance.size and instance.size > limit:
        return

    def _do():
        from django.conf import settings as s
        from pathlib import Path

        from core.search import extract_text

        media = Path(s.MEDIA_ROOT)
        abs_path = media / instance.storage_path
        text = extract_text(str(abs_path), instance.ext)
        if text:
            index_document("file", instance.id, instance.owner_id, instance.name, text, summary=text)

    _safe(_do)


@receiver(post_delete, sender="files.FileMeta")
def on_file_deleted(sender, instance, **kwargs):
    from core.search import remove_document

    _safe(remove_document, "file", instance.id)


@receiver(post_save, sender="projects.Project")
def on_project_saved(sender, instance, **kwargs):
    from core.search import index_document

    _safe(index_document, "project", instance.id, instance.owner_id, instance.name,
          instance.description or "")


@receiver(post_save, sender="projects.TaskCard")
def on_task_saved(sender, instance, **kwargs):
    from core.search import index_document

    try:
        owner_id = instance.board.project.owner_id
    except Exception:
        owner_id = None
    _safe(index_document, "task", instance.id, owner_id, instance.title, instance.description or "")


# ---------- v6 代码工坊：代码文件入全文索引（第 79 条）----------
# 复用 core.search 已有的 TEXT_EXTS（含 py/js/ts/vue/java/c/cpp/go/rs/rb/php/sql/sh），
# 因此代码片段天然可被「/api/core/search/fulltext/」检索到，无需额外索引结构。


@receiver(post_save, sender="code.CodeFile")
def on_code_file_saved(sender, instance, **kwargs):
    """代码文件保存后写入全文索引（标题取 path，正文为源码）。"""
    from core.search import index_document

    title = f"{instance.workspace.name}/{instance.path}" if instance.workspace_id else instance.path
    _safe(index_document, "code", instance.id, instance.owner_id, title, instance.content or "")


@receiver(post_delete, sender="code.CodeFile")
def on_code_file_deleted(sender, instance, **kwargs):
    from core.search import remove_document

    _safe(remove_document, "code", instance.id)


@receiver(post_save, sender="code.CodeSnippet")
def on_code_snippet_saved(sender, instance, **kwargs):
    """代码片段入索引，标题+描述+代码正文。"""
    from core.search import index_document

    body = f"{instance.description}\n{instance.code}"
    _safe(index_document, "snippet", instance.id, instance.owner_id, instance.title, body,
          summary=instance.description or instance.code[:200])


@receiver(post_delete, sender="code.CodeSnippet")
def on_code_snippet_deleted(sender, instance, **kwargs):
    from core.search import remove_document

    _safe(remove_document, "snippet", instance.id)
