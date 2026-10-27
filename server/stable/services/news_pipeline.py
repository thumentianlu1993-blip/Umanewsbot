"""P01 新闻流水线。已接管的文章即使停用新认领也不得退回旧 writer。"""


def is_pipeline_article(article):
    return bool(getattr(article, "active_news_run_id", None))
