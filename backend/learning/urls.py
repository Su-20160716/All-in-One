# -*- coding: utf-8 -*-
"""学习中心路由：编程 / 学科 / 个人 / 工具 四组。"""
from django.urls import path

from learning import views as v
from learning.learn_tools import LEARN_TOOL_REGISTRY

prog = [
    # 编程 30 项
    path("prog/languages/", v.LangCatalogView.as_view(), name="learn-lang-catalog"),
    path("prog/languages/compare/", v.LangCompareView.as_view(), name="learn-lang-compare"),
    path("prog/glossary/", v.GlossaryView.as_view(), name="learn-glossary"),
    path("prog/paradigms/", v.ParadigmsView.as_view(), name="learn-paradigms"),
    path("prog/algorithms/", v.AlgorithmsView.as_view(), name="learn-algorithms"),
    path("prog/data-structures/", v.DataStructuresView.as_view(), name="learn-data-structures"),
    path("prog/recommend/", v.RecommendView.as_view(), name="learn-recommend"),
    path("prog/daily-challenge/", v.DailyChallengeView.as_view(), name="learn-daily"),
    path("prog/drill/quiz/", v.DrillQuizView.as_view(), name="learn-drill-quiz"),
    path("prog/drill/output/", v.DrillOutputView.as_view(), name="learn-drill-output"),
    path("prog/drill/fill/", v.DrillFillView.as_view(), name="learn-drill-fill"),
    path("prog/drill/bug/", v.DrillBugView.as_view(), name="learn-drill-bug"),
    path("prog/drill/random/", v.DrillRandomView.as_view(), name="learn-drill-random"),
    path("prog/drill/grade/", v.DrillGradeView.as_view(), name="learn-drill-grade"),
    path("prog/drill/quiz-submit/", v.QuizSubmitView.as_view(), name="learn-quiz-submit"),
    path("prog/progress/", v.ProgressView.as_view(), name="learn-progress"),
    path("prog/snippets/bookmarks/", v.SnippetBookmarkView.as_view(), name="learn-snippet-bookmark"),
    path("prog/languages/<str:key>/", v.LangDetailView.as_view(), name="learn-lang-detail"),
    path("prog/languages/<str:key>/roadmap/", v.LangRoadmapView.as_view(), name="learn-lang-roadmap"),
    path("prog/languages/<str:key>/cheatsheet/", v.LangCheatsheetView.as_view(), name="learn-lang-cheatsheet"),
    path("prog/languages/<str:key>/keywords/", v.LangKeywordsView.as_view(), name="learn-lang-keywords"),
    path("prog/languages/<str:key>/keywords/<str:word>/", v.LangKeywordDetailView.as_view(), name="learn-lang-keyword-detail"),
    path("prog/languages/<str:key>/modules/", v.LangModulesView.as_view(), name="learn-lang-modules"),
    path("prog/languages/<str:key>/modules/<int:idx>/", v.LangModuleDetailView.as_view(), name="learn-lang-module-detail"),
    path("prog/languages/<str:key>/types/", v.LangTypesView.as_view(), name="learn-lang-types"),
    path("prog/languages/<str:key>/snippets/", v.LangSnippetListView.as_view(), name="learn-lang-snippets"),
    path("prog/languages/<str:key>/snippets/<int:idx>/", v.LangSnippetDetailView.as_view(), name="learn-lang-snippet"),
    path("prog/languages/<str:key>/lessons/", v.LessonListView.as_view(), name="learn-lessons"),
    path("prog/languages/<str:key>/lessons/<int:idx>/", v.LessonDetailView.as_view(), name="learn-lesson"),
    path("prog/languages/<str:key>/troubleshoot/", v.LangTroubleshootView.as_view(), name="learn-lang-errors"),
    path("prog/languages/<str:key>/ide/", v.LangIdeView.as_view(), name="learn-lang-ide"),
    path("prog/languages/<str:key>/style/", v.LangStyleView.as_view(), name="learn-lang-style"),
]

school = [
    # 学科 30 项
    path("school/stages/", v.StageListView.as_view(), name="learn-stages"),
    path("school/knowledge/", v.KnowledgeTreeView.as_view(), name="learn-knowledge"),
    path("school/knowledge/search/", v.KnowledgeSearchView.as_view(), name="learn-knowledge-search"),
    # v8 新增（dsh 2026-10-01）：必须排在 <str:kid> 兜底之前，否则会被当知识点 ID 吃掉
    path("school/knowledge/related/", v.KnowledgeRelatedView.as_view(), name="learn-knowledge-related"),  # F539
    path("school/knowledge/<str:kid>/", v.KnowledgeDetailView.as_view(), name="learn-knowledge-detail"),
    path("school/stages/<str:stage>/subjects/<str:subject>/", v.SubjectDetailView.as_view(), name="learn-subject"),
    path("school/formulas/", v.FormulaListView.as_view(), name="learn-formulas"),
    path("school/formulas/calc/", v.FormulaCalcView.as_view(), name="learn-formula-calc"),
    path("school/formulas/favorites/", v.FormulaFavoriteView.as_view(), name="learn-formula-fav"),  # F532
    path("school/formulas/<str:key>/", v.FormulaDetailView.as_view(), name="learn-formula"),
    path("school/poems/", v.PoemListView.as_view(), name="learn-poems"),
    path("school/poems/drill/", v.PoemDrillView.as_view(), name="learn-poem-drill"),
    path("school/poems/fill-blank/", v.PoemFillBlankView.as_view(), name="learn-poem-fill"),  # F528
    path("school/poems/<str:key>/", v.PoemDetailView.as_view(), name="learn-poem"),
    path("school/words/", v.WordListView.as_view(), name="learn-words"),
    path("school/words/dictation/", v.WordDictationView.as_view(), name="learn-word-dictation"),
    path("school/words/dictation/collect/", v.DictationCollectView.as_view(), name="learn-dict-collect"),  # F531
    path("school/words/dictation/grade/", v.DictationGradeView.as_view(), name="learn-dict-grade"),  # F543
    path("school/words/quiz/", v.WordQuizView.as_view(), name="learn-word-quiz"),
    path("school/words/wordbook/", v.WordbookView.as_view(), name="learn-wordbook"),
    path("school/words/<str:word>/", v.WordDetailView.as_view(), name="learn-word"),
    path("school/questions/", v.QuestionListView.as_view(), name="learn-questions"),
    path("school/questions/favorites/", v.QuestionFavoriteView.as_view(), name="learn-question-fav"),  # F536
    path("school/paper/compose/", v.PaperComposeView.as_view(), name="learn-paper-compose"),
    path("school/paper/grade/", v.PaperGradeView.as_view(), name="learn-paper-grade"),
    path("school/questions/<str:qid>/", v.QuestionDetailView.as_view(), name="learn-question"),
    path("school/mistakes/", v.MistakeView.as_view(), name="learn-mistakes"),
    path("school/mastery/", v.MasteryView.as_view(), name="learn-mastery"),
    path("school/idioms/", v.IdiomListView.as_view(), name="learn-idioms"),
    path("school/idioms/chain/", v.IdiomChainView.as_view(), name="learn-idiom-chain"),
    path("school/idioms/chain-records/", v.IdiomChainRecordView.as_view(), name="learn-idiom-chains"),  # F529
    path("school/hanzi/", v.HanziView.as_view(), name="learn-hanzi"),
    path("school/elements/", v.ElementListView.as_view(), name="learn-elements"),
    path("school/elements/<str:key>/", v.ElementDetailView.as_view(), name="learn-element"),
    path("school/equations/", v.EquationListView.as_view(), name="learn-equations"),
    path("school/equations/practice/", v.EquationPracticeView.as_view(), name="learn-eq-practice"),  # F530
    path("school/grammar/", v.GrammarListView.as_view(), name="learn-grammar"),
    path("school/grammar/<str:key>/", v.GrammarDetailView.as_view(), name="learn-grammar-detail"),
]

personal = [
    path("study/sessions/", v.StudySessionView.as_view(), name="learn-sessions"),
    path("study/plans/", v.StudyPlanView.as_view(), name="learn-plans"),
    # ---- v8 学习闭环增强（dsh 2026-09-30，只增不改）----
    path("study/streak/", v.StudyStreakView.as_view(), name="learn-streak"),                 # F522
    path("study/report/", v.StudyReportView.as_view(), name="learn-report"),                 # F519
    path("study/review-queue/", v.StudyReviewQueueView.as_view(), name="learn-review-queue"),  # F521
    path("study/re-drill/", v.StudyReDrillView.as_view(), name="learn-re-drill"),            # F520
    path("study/weakness/", v.StudyWeaknessView.as_view(), name="learn-weakness"),           # F541
    path("study/backup/", v.StudyBackupView.as_view(), name="learn-backup"),                 # F533
    path("search/", v.LearningGlobalSearchView.as_view(), name="learn-search"),              # F542
    path("prog/radar/", v.ProgRadarView.as_view(), name="learn-prog-radar"),                 # F535
    # ---- v8 学习区新增能力（dsh 2026-10-01，只增不改）----
    path("study/daily-goal/", v.DailyGoalView.as_view(), name="learn-daily-goal"),           # F523
    path("study/pomodoro/", v.PomodoroView.as_view(), name="learn-pomodoro"),                # F524
    path("study/question-sets/", v.QuestionSetView.as_view(), name="learn-question-sets"),   # F525
    path("study/mastery-rating/", v.MasteryRatingView.as_view(), name="learn-mastery-rating"),  # F526
    path("study/paper-archive/", v.PaperArchiveView.as_view(), name="learn-paper-archive"),  # F537
    path("study/tool-usage/", v.ToolUsageView.as_view(), name="learn-tool-usage"),           # F538
    path("study/badges/", v.LearningBadgeView.as_view(), name="learn-badges"),               # F540
    path("study/progress-detail/", v.ProgressDetailView.as_view(), name="learn-progress-detail"),  # F544
    path("study/mistake-cause/", v.MistakeCauseView.as_view(), name="learn-mistake-cause"),  # F545
    path("study/plan-detail/", v.StudyPlanDetailView.as_view(), name="learn-plan-detail"),   # F546
]

tools = [
    path("tools/catalog/", v.LearnToolCatalogView.as_view(), name="learn-tool-catalog"),
    path("tools/run/", v.LearnToolRunView.as_view(), name="learn-tool-run"),
]
# 每个学习工具的直达入口 /api/learning/tools/<key>/
for _key in LEARN_TOOL_REGISTRY:
    tools.append(path(f"tools/{_key}/", v.LearnToolRunView.as_view(), kwargs={"tool": _key}))

urlpatterns = prog + school + personal + tools
