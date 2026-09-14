from django.contrib import admin

from learning.models import (
    LearningProgress, MistakeRecord, SnippetBookmark, StudyPlan, StudySession, WordbookItem,
)

for model, cols in [
    (LearningProgress, ["owner", "domain", "target_key", "percent", "status", "updated_at"]),
    (SnippetBookmark, ["owner", "language", "title", "created_at"]),
    (WordbookItem, ["owner", "word", "phonetic", "mastered", "created_at"]),
    (MistakeRecord, ["owner", "stage", "subject", "question_type", "mastered", "created_at"]),
    (StudySession, ["owner", "subject", "minutes", "study_date"]),
    (StudyPlan, ["owner", "title", "subject", "total", "finished", "days"]),
]:
    admin.site.register(
        model,
        type(f"{model.__name__}Admin", (admin.ModelAdmin,), {"list_display": cols, "search_fields": ["owner__username"]}),
    )
