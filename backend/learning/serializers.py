"""学习中心序列化器"""
from rest_framework import serializers

from learning.models import (
    LearningProgress, MistakeRecord, SnippetBookmark, StudyPlan, StudySession, WordbookItem,
)


class LearningProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningProgress
        fields = ["id", "domain", "target_key", "target_name", "status", "percent", "note", "created_at", "updated_at"]


class SnippetBookmarkSerializer(serializers.ModelSerializer):
    class Meta:
        model = SnippetBookmark
        fields = ["id", "language", "title", "code", "note", "created_at"]


class WordbookItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = WordbookItem
        fields = ["id", "word", "phonetic", "meaning", "mastered", "created_at"]


class MistakeRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = MistakeRecord
        fields = ["id", "stage", "subject", "question_type", "difficulty", "stem",
                  "answer", "user_answer", "analysis", "mastered", "created_at"]


class StudySessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudySession
        fields = ["id", "subject", "minutes", "study_date", "note", "created_at"]


class StudyPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudyPlan
        fields = ["id", "title", "subject", "total", "days", "plan", "finished", "start_date", "created_at"]
