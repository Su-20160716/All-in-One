from django.contrib import admin

from notes.models import Note, NoteAttachment, NoteComment, NoteTag, NoteTemplate, NoteVersion


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ["title", "owner", "version", "is_public", "is_pinned", "remind_at", "updated_at"]
    search_fields = ["title", "content"]


@admin.register(NoteVersion)
class NoteVersionAdmin(admin.ModelAdmin):
    list_display = ["note", "version", "created_at"]


@admin.register(NoteTag)
class NoteTagAdmin(admin.ModelAdmin):
    list_display = ["name", "owner"]


@admin.register(NoteComment)
class NoteCommentAdmin(admin.ModelAdmin):
    list_display = ["note", "author", "resolved", "created_at"]


@admin.register(NoteAttachment)
class NoteAttachmentAdmin(admin.ModelAdmin):
    list_display = ["note", "name", "size", "created_at"]


@admin.register(NoteTemplate)
class NoteTemplateAdmin(admin.ModelAdmin):
    list_display = ["title", "owner", "updated_at"]
