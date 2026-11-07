# -*- coding: utf-8 -*-
"""devtools 路由：text/str/md/json/log/encode/regex + hash/token/code/diff/id/file/qr/web/db
+ num/color/date/cron/math/unit + net/fake/fun，共 168 个 URL（含目录）。"""
from django.urls import path

from . import views_code as c
from . import views_datax as d
from . import views_math as m
from . import views_misc as x
from . import views_text as t
from .common import endpoint, endpoint_index, ok

SUBSYSTEMS = [
    ("text", "文本处理", ["case", "wrap", "pad", "replace", "extract", "normalize"]),
    ("str", "字符串进阶", ["dedent", "truncate", "char-stats", "initials", "abbr", "reverse-words"]),
    ("md", "Markdown 工具链", ["to-html", "headings", "toc", "strip", "table", "frontmatter"]),
    ("json", "JSON 进阶", ["flatten", "unflatten", "merge", "ndjson", "stats", "pick"]),
    ("log", "日志分析", ["parse", "level-stat", "timeframe", "topn", "filter"]),
    ("encode", "编码转换", ["base32", "base85", "qp", "unicode-escape", "punycode"]),
    ("regex", "正则实验室", ["replace", "extract", "split", "explain", "grep", "template", "debug", "cases"]),
    ("data", "结构化数据互转", ["yaml", "toml", "xml", "convert"]),
    ("hash", "哈希扩展", ["crc32", "adler32", "sha3", "hmac", "blake2"]),
    ("token", "令牌与密钥", ["jwt-sign", "jwt-verify", "apikey", "otp", "nanoid", "password-audit"]),
    ("code", "代码工具", ["minify-css", "beautify", "lang-detect", "loc", "todo-scan", "gitmoji",
                          "complexity", "import-graph"]),
    ("diff", "差异对比", ["text", "word", "json", "similarity", "patch", "three-way"]),
    ("id", "标识符", ["uuid-multi", "shortid", "checksum", "luhn-gen", "snowflake-parse"]),
    ("file", "文件工具", ["data-url", "csv-clean", "magic", "zip-list", "encoding-detect", "line-endings"]),
    ("qr", "码制", ["generate", "info", "barcode39"]),
    ("web", "接口助手", ["curl-parse", "jsonpath", "dotpath", "http-status", "headers", "querystring"]),
    ("db", "SQL 助手", ["sql-format", "sql-minify", "where-builder", "join-explain", "epoch", "sql-to-model"]),
    ("num", "数字进制", ["base", "ieee754", "bitwise", "combinatorics", "format", "rounding"]),
    ("color", "颜色实验室", ["contrast", "mix", "scale", "nearest", "shade", "filter"]),
    ("date", "日期数学", ["add", "workdays", "week-info", "quarter-info", "seq", "countdown",
                          "timestamp-batch"]),
    ("cron", "CRON 表达式", ["parse", "validate", "from-interval", "shift", "next-runs"]),
    ("math", "数学扩展", ["matrix", "linear-solve", "primes", "expr", "dist", "dijkstra"]),
    ("unit", "单位换算", ["data-size", "angle", "speed", "apparel"]),
    ("net", "网络工具", ["ip-calc", "ip-classify", "url-parse", "url-build", "ua-parse", "mime-lookup",
                          "cidr-merge"]),
    ("fake", "模拟数据", ["person", "company", "address", "lorem", "batch", "net", "bank-card"]),
    ("fun", "趣味盒子", ["fortune", "dice", "lottery", "team-splitter", "coinflip", "emoji", "today", "zodiac"]),
    ("cheatsheet", "速查手册", ["md", "git", "vim", "shell", "regex", "http", "python", "sql"]),
    ("asciiart", "ASCII 艺术", ["banner", "box", "table", "block", "sparkline", "progress"]),
]

VIEWS = {
    # text
    "text/case/": t.text_case, "text/wrap/": t.text_wrap, "text/pad/": t.text_pad,
    "text/replace/": t.text_replace, "text/extract/": t.text_extract, "text/normalize/": t.text_normalize,
    "str/dedent/": t.str_dedent, "str/truncate/": t.str_truncate, "str/char-stats/": t.str_char_stats,
    "str/initials/": t.str_initials, "str/abbr/": t.str_abbr, "str/reverse-words/": t.str_reverse_words,
    "md/to-html/": t.md_to_html, "md/headings/": t.md_headings, "md/toc/": t.md_toc,
    "md/strip/": t.md_strip, "md/table/": t.md_table, "md/frontmatter/": t.md_frontmatter,
    "json/flatten/": t.json_flatten, "json/unflatten/": t.json_unflatten, "json/merge/": t.json_merge,
    "json/ndjson/": t.json_ndjson, "json/stats/": t.json_stats, "json/pick/": t.json_pick,
    "log/parse/": t.log_parse, "log/level-stat/": t.log_level_stat, "log/timeframe/": t.log_timeframe,
    "log/topn/": t.log_topn, "log/filter/": t.log_filter,
    "encode/base32/": t.encode_base32, "encode/base85/": t.encode_base85, "encode/qp/": t.encode_qp,
    "encode/unicode-escape/": t.encode_unicode_escape, "encode/punycode/": t.encode_punycode,
    "regex/replace/": t.regex_replace, "regex/extract/": t.regex_extract, "regex/split/": t.regex_split,
    "regex/explain/": t.regex_explain, "regex/grep/": t.regex_grep, "regex/template/": t.regex_template,
    # F39 结构化数据互转 / F40 正则调试 / F41 时间戳批量
    "data/yaml/": d.data_yaml, "data/toml/": d.data_toml, "data/xml/": d.data_xml,
    "data/convert/": d.data_convert,
    "regex/debug/": d.regex_debug, "date/timestamp-batch/": d.timestamp_batch,
    # code
    "hash/crc32/": c.hash_crc32, "hash/adler32/": c.hash_adler32, "hash/sha3/": c.hash_sha3,
    "hash/hmac/": c.hash_hmac, "hash/blake2/": c.hash_blake2,
    "token/jwt-sign/": c.token_jwt_sign, "token/jwt-verify/": c.token_jwt_verify, "token/apikey/": c.token_apikey,
    "token/otp/": c.token_otp, "token/nanoid/": c.token_nanoid, "token/password-audit/": c.token_password_audit,
    "code/minify-css/": c.code_minify_css, "code/beautify/": c.code_beautify, "code/lang-detect/": c.code_lang_detect,
    "code/loc/": c.code_loc, "code/todo-scan/": c.code_todo_scan, "code/gitmoji/": c.code_gitmoji,
    "diff/text/": c.diff_text, "diff/word/": c.diff_word, "diff/json/": c.diff_json,
    "diff/similarity/": c.diff_similarity, "diff/patch/": c.diff_patch,
    "id/uuid-multi/": c.id_uuid_multi, "id/shortid/": c.id_shortid, "id/checksum/": c.id_checksum,
    "id/luhn-gen/": c.id_luhn_gen,
    "file/data-url/": c.file_data_url, "file/csv-clean/": c.file_csv_clean, "file/magic/": c.file_magic,
    "file/zip-list/": c.file_zip_list, "file/encoding-detect/": c.file_encoding_detect, "file/line-endings/": c.file_line_endings,
    "qr/generate/": c.qr_generate, "qr/info/": c.qr_info, "qr/barcode39/": c.barcode_code39,
    "web/curl-parse/": c.web_curl_parse, "web/jsonpath/": c.web_jsonpath, "web/dotpath/": c.web_dotpath,
    "web/http-status/": c.web_http_status, "web/headers/": c.web_headers, "web/querystring/": c.web_querystring,
    "db/sql-format/": c.db_sql_format, "db/sql-minify/": c.db_sql_minify, "db/where-builder/": c.db_where_builder,
    "db/join-explain/": c.db_join_explain, "db/epoch/": c.db_epoch,
    # math
    "num/base/": m.num_base, "num/ieee754/": m.num_ieee754, "num/bitwise/": m.num_bitwise,
    "num/combinatorics/": m.num_combinatorics, "num/format/": m.num_format, "num/rounding/": m.num_rounding,
    "color/contrast/": m.color_contrast, "color/mix/": m.color_mix, "color/scale/": m.color_scale,
    "color/nearest/": m.color_nearest, "color/shade/": m.color_shade, "color/filter/": m.color_filter,
    "date/add/": m.date_add, "date/workdays/": m.date_workdays, "date/week-info/": m.date_week_info,
    "date/quarter-info/": m.date_quarter_info, "date/seq/": m.date_seq, "date/countdown/": m.date_countdown,
    "cron/parse/": m.cron_parse, "cron/validate/": m.cron_validate, "cron/from-interval/": m.cron_from_interval,
    "cron/shift/": m.cron_shift,
    "math/matrix/": m.math_matrix, "math/linear-solve/": m.math_linear_solve, "math/primes/": m.math_primes,
    "math/expr/": m.math_expr, "math/dist/": m.math_dist, "math/dijkstra/": m.math_dijkstra,
    "unit/data-size/": m.unit_data_size, "unit/angle/": m.unit_angle, "unit/speed/": m.unit_speed,
    "unit/apparel/": m.unit_apparel,
    # misc
    "net/ip-calc/": x.net_ip_calc, "net/ip-classify/": x.net_ip_classify, "net/url-parse/": x.net_url_parse,
    "net/url-build/": x.net_url_build, "net/ua-parse/": x.net_ua_parse, "net/mime-lookup/": x.net_mime_lookup,
    "fake/person/": x.fake_person, "fake/company/": x.fake_company, "fake/address/": x.fake_address,
    "fake/lorem/": x.fake_lorem, "fake/batch/": x.fake_batch, "fake/net/": x.fake_net,
    "fake/bank-card/": x.fake_bank_card,
    "fun/fortune/": x.fun_fortune, "fun/dice/": x.fun_dice, "fun/lottery/": x.fun_lottery,
    "fun/team-splitter/": x.fun_team_splitter, "fun/coinflip/": x.fun_coinflip, "fun/emoji/": x.fun_emoji,
    "fun/today/": x.fun_today, "fun/zodiac/": x.fun_zodiac,
    # cheatsheet + asciiart
    "cheatsheet/md/": x.cheatsheet_md, "cheatsheet/git/": x.cheatsheet_git, "cheatsheet/vim/": x.cheatsheet_vim,
    "cheatsheet/shell/": x.cheatsheet_shell, "cheatsheet/regex/": x.cheatsheet_regex,
    "cheatsheet/http/": x.cheatsheet_http, "cheatsheet/python/": x.cheatsheet_python, "cheatsheet/sql/": x.cheatsheet_sql,
    "asciiart/banner/": x.asciiart_banner, "asciiart/box/": x.asciiart_box, "asciiart/table/": x.asciiart_table,
    "asciiart/block/": x.asciiart_block, "asciiart/sparkline/": x.asciiart_sparkline,
    "asciiart/progress/": x.asciiart_progress,
    # ---- 第三轮 S26（391–398，8 个：静态分析 / 合并 / 反解 / DDL）----
    "code/complexity/": c.code_complexity, "code/import-graph/": c.code_import_graph,
    "regex/cases/": t.regex_cases,
    "diff/three-way/": c.diff_three_way,
    "cron/next-runs/": m.cron_next_runs,
    "net/cidr-merge/": x.net_cidr_merge,
    "id/snowflake-parse/": c.id_snowflake_parse,
    "db/sql-to-model/": c.db_sql_to_model,
}


@endpoint(("GET",))
def devtools_catalog(request):
    """目录：28 个子系统 × 167 接口的路由总览（供前端动态渲染）。"""
    return ok({
        "domain": "devtools", "domain_name": "开发者工具箱",
        "subsystems": [{"key": k, "name": n, "endpoints": eps,
                        "url_prefix": f"/api/devtools/{k}/"} for k, n, eps in SUBSYSTEMS],
        "subsystem_count": len(SUBSYSTEMS),
        "endpoint_count": sum(len(eps) for _, _, eps in SUBSYSTEMS) + 1,
        "endpoints": endpoint_index(urlpatterns),
    })


urlpatterns = [path("catalog/", devtools_catalog, name="devtools-catalog")]
for _route, _view in VIEWS.items():
    urlpatterns.append(path(_route, _view))

assert len(urlpatterns) == 168, f"devtools 接口数应为 168，实际 {len(urlpatterns)}"
