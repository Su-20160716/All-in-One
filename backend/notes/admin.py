from django.contrib import admin

from notes.models import Note, NoteTag, NoteVersion


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ["title", "owner", "version", "is_public", "is_pinned", "updated_at"]
    search_fields = ["title", "content"]


@admin.register(NoteVersion)
class NoteVersionAdmin(admin.ModelAdmin):
    list_display = ["note", "version", "created_at"]


@admin.register(NoteTag)
class NoteTagAdmin(admin.ModelAdmin):
    list_display = ["name", "owner"]
