# -*- coding: utf-8 -*-
"""dataintel 路由：dataset/profile/transform/calc + stats/forecast/regress/cluster/outlier
+ nlp/textmine/vector + ai/report + chart/abtest/cohort/sampling/geo，共 124 个 URL（含目录）。

F48 版本管理 +3（versions / diff / rollback），F49 图表落盘 +1，F50 数据质量 +1。
"""
from django.urls import path

from . import views_ai as ai
from . import views_data as d
from . import views_extra as e
from . import views_nlp as n
from . import views_plus as px
from . import views_stats as s
from devtools.common import endpoint, endpoint_index, ok

SUBSYSTEMS = [
    ("dataset", "数据集管理", 10), ("profile", "数据画像", 6), ("transform", "数据变换", 9),
    ("calc", "数据计算器", 5), ("stats", "统计检验", 8), ("forecast", "时间序列", 6),
    ("regress", "回归拟合", 5), ("cluster", "聚类", 4), ("outlier", "异常检测", 4),
    ("nlp", "中文 NLP", 8), ("textmine", "文本挖掘", 5), ("vector", "向量运算", 5),
    ("ai", "AI 增强", 8), ("report", "智能报表", 5), ("chart", "图表数据", 9),
    ("abtest", "A/B 实验", 5), ("cohort", "留存分析", 4), ("sampling", "抽样", 4),
    ("geo", "轻地理计算", 6), ("insight", "自动洞察", 6), ("quality", "数据质量", 1),
]

urlpatterns = [
    path("catalog/", endpoint(("GET",))(
        lambda request: ok({"domain": "dataintel", "domain_name": "数据智能中心",
                            "subsystems": [{"key": k, "name": nm, "endpoints": c,
                                            "url_prefix": f"/api/dataintel/{k}/"}
                                           for k, nm, c in SUBSYSTEMS],
                            "subsystem_count": len(SUBSYSTEMS),
                            "endpoint_count": sum(c for _, _, c in SUBSYSTEMS) + 1,
                            "endpoints": endpoint_index(urlpatterns)})
    ), name="dataintel-catalog"),
    # dataset（6）
    path("dataset/create/", d.dataset_create),
    path("dataset/list/", d.dataset_list),
    path("dataset/<int:pk>/", d.dataset_detail),
    path("dataset/<int:pk>/delete/", d.dataset_delete),
    path("dataset/<int:pk>/rows/import/", d.dataset_rows_import),
    path("dataset/<int:pk>/rows/query/", d.dataset_rows_query),
    # S26(410) 数据集导出（csv/json）
    path("dataset/<int:pk>/export/", d.dataset_export),
    # F48 版本（3）
    path("dataset/<int:pk>/versions/", px.dataset_versions),
    path("dataset/<int:pk>/versions/diff/", px.dataset_version_diff),
    path("dataset/<int:pk>/versions/<int:vid>/rollback/", px.dataset_version_rollback),
    # profile（5）
    path("profile/describe/", d.profile_describe),
    path("profile/freq/", d.profile_freq),
    path("profile/corr/", d.profile_corr),
    path("profile/missing/", d.profile_missing),
    path("profile/dtype-infer/", d.profile_dtype_infer),
    # S26(409) 字段取值分布
    path("profile/unique-values/", d.profile_unique_values),
    # transform（6）
    path("transform/pivot/", d.transform_pivot),
    path("transform/groupby/", d.transform_groupby),
    path("transform/filter-expr/", d.transform_filter_expr),
    path("transform/sort/", d.transform_sort),
    path("transform/sample/", d.transform_sample),
    path("transform/normalize/", d.transform_normalize),
    # S26(406–408) 独热 / 时序位移 / PII 脱敏（落新 DatasetVersion）
    path("transform/one-hot/", d.transform_one_hot),
    path("transform/lag/", d.transform_lag),
    path("transform/mask-pii/", d.transform_mask_pii),
    # calc（5）
    path("calc/expr-row/", d.calc_expr_row),
    path("calc/pct-change/", d.calc_pct_change),
    path("calc/weighted/", d.calc_weighted),
    path("calc/running-total/", d.calc_running_total),
    path("calc/vlookup/", d.calc_vlookup),
    # stats（8）
    path("stats/ttest-one/", s.stats_ttest_one),
    path("stats/ttest-two/", s.stats_ttest_two),
    path("stats/chi2/", s.stats_chi2),
    path("stats/zscore/", s.stats_zscore),
    path("stats/ci-mean/", s.stats_ci_mean),
    path("stats/proportion-ci/", s.stats_proportion_ci),
    path("stats/binomial-test/", s.stats_binomial_test),
    path("stats/corr-sig/", s.stats_corr_sig),
    # forecast（6）
    path("forecast/moving-average/", s.forecast_moving_average),
    path("forecast/exp-smoothing/", s.forecast_exp_smoothing),
    path("forecast/linear-trend/", s.forecast_linear_trend),
    path("forecast/season-naive/", s.forecast_season_naive),
    path("forecast/eval/", s.forecast_eval),
    path("forecast/decompose/", s.forecast_decompose),
    # regress（5）
    path("regress/linear/", s.regress_linear),
    path("regress/poly/", s.regress_poly),
    path("regress/logit/", s.regress_logit),
    path("regress/eval/", s.regress_eval),
    path("regress/predict/", s.regress_predict),
    # cluster（4）
    path("cluster/kmeans/", s.cluster_kmeans),
    path("cluster/hierarchical/", s.cluster_hierarchical),
    path("cluster/dbscan/", s.cluster_dbscan),
    path("cluster/elbow/", s.cluster_elbow),
    # outlier（4）
    path("outlier/zscore/", s.outlier_zscore),
    path("outlier/iqr/", s.outlier_iqr),
    path("outlier/mad/", s.outlier_mad),
    path("outlier/lof/", s.outlier_lof),
    # nlp（8）
    path("nlp/tokenize/", n.nlp_tokenize),
    path("nlp/keywords/", n.nlp_keywords),
    path("nlp/sentiment/", n.nlp_sentiment),
    path("nlp/summarize/", n.nlp_summarize),
    path("nlp/entities/", n.nlp_entities),
    path("nlp/similarity/", n.nlp_similarity),
    path("nlp/readability/", n.nlp_readability),
    path("nlp/stopwords/", n.nlp_stopwords),
    # textmine（5）
    path("textmine/wordfreq/", n.textmine_wordfreq),
    path("textmine/cooccurrence/", n.textmine_cooccurrence),
    path("textmine/bigram/", n.textmine_bigram),
    path("textmine/classify/", n.textmine_classify),
    path("textmine/simhash/", n.textmine_simhash),
    # vector（5）
    path("vector/cosine/", n.vector_cosine),
    path("vector/distance/", n.vector_distance),
    path("vector/knn/", n.vector_knn),
    path("vector/centroid/", n.vector_centroid),
    path("vector/normalize/", n.vector_normalize),
    # ai（8）
    path("ai/status/", ai.ai_status),
    path("ai/chat/", ai.ai_chat),
    path("ai/translate/", ai.ai_translate),
    path("ai/rewrite/", ai.ai_rewrite),
    path("ai/classify/", ai.ai_classify),
    path("ai/extract/", ai.ai_extract),
    path("ai/sentiment/", ai.ai_sentiment),
    path("ai/summary/", ai.ai_summary),
    # report（5）
    path("report/summary/", ai.report_summary),
    path("report/trend/", ai.report_trend),
    path("report/compare/", ai.report_compare),
    path("report/kpi/", ai.report_kpi),
    path("report/export/", ai.report_export),
    # chart（8）
    path("chart/histogram/", e.chart_histogram),
    path("chart/boxplot/", e.chart_boxplot),
    path("chart/scatter/", e.chart_scatter),
    path("chart/pie/", e.chart_pie),
    path("chart/line/", e.chart_line),
    path("chart/heatmap/", e.chart_heatmap),
    path("chart/pareto/", e.chart_pareto),
    path("chart/funnel/", e.chart_funnel),
    # abtest（5）
    path("abtest/assign/", e.abtest_assign),
    path("abtest/hash-preview/", e.abtest_hash_preview),
    path("abtest/plan/", e.abtest_plan),
    path("abtest/significance/", e.abtest_significance),
    path("abtest/metrics/", e.abtest_metrics),
    # cohort（4）
    path("cohort/build/", e.cohort_build),
    path("cohort/summary/", e.cohort_summary),
    path("cohort/retain/", e.cohort_retain),
    path("cohort/compare/", e.cohort_compare),
    # sampling（4）
    path("sampling/random/", e.sampling_random),
    path("sampling/systematic/", e.sampling_systematic),
    path("sampling/stratified/", e.sampling_stratified),
    path("sampling/bootstrap/", e.sampling_bootstrap),
    # geo（6）
    path("geo/distance/", e.geo_distance),
    path("geo/geohash/", e.geo_geohash),
    path("geo/polygon/", e.geo_polygon),
    path("geo/bbox/", e.geo_bbox),
    path("geo/eta/", e.geo_eta),
    path("geo/parse/", e.geo_parse),
    # insight（6）
    path("insight/overview/", e.insight_overview),
    path("insight/anomaly-brief/", e.insight_anomaly_brief),
    path("insight/trend-brief/", e.insight_trend_brief),
    path("insight/corr-top/", e.insight_corr_top),
    path("insight/segment-diff/", e.insight_segment_diff),
    path("insight/narrate/", e.insight_narrate),
    # F49 图表落盘 + F50 数据质量（2）
    path("chart/save/", px.chart_save),
    path("data-quality/", px.data_quality),
]

assert len(urlpatterns) == 124, f"dataintel 接口数应为 124，实际 {len(urlpatterns)}"
