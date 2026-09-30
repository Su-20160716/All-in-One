# -*- coding: utf-8 -*-
from django.contrib import admin

from .models import Dataset


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "owner", "row_count", "created_at")
    search_fields = ("name", "description")
    list_filter = ("created_at",)
