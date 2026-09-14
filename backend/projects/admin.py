from django.contrib import admin

from projects.models import Board, CardComment, Project, ProjectActivity, TaskCard


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "is_archived", "created_at"]


@admin.register(Board)
class BoardAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "sort_order"]


@admin.register(TaskCard)
class TaskCardAdmin(admin.ModelAdmin):
    list_display = ["title", "board", "priority", "status", "due_date"]


@admin.register(CardComment)
class CardCommentAdmin(admin.ModelAdmin):
    list_display = ["card", "author", "created_at"]


@admin.register(ProjectActivity)
class ProjectActivityAdmin(admin.ModelAdmin):
    list_display = ["project", "user", "action", "created_at"]
