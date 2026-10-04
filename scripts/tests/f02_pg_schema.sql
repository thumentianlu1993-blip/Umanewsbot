-- Synthetic F02 PG16 fixture only. Never execute against production.

-- Matches required column types/nullability; does not claim full Django constraints.

CREATE TABLE public.stable_newsarticle (
    automation_status varchar(32) NOT NULL DEFAULT '',
    body_ja_normalized text NOT NULL DEFAULT '',
    body_ja_raw text NOT NULL DEFAULT '',
    body_zh text NOT NULL DEFAULT '',
    crawl_job_id bigint DEFAULT NULL,
    crawl_status varchar(16) NOT NULL DEFAULT '',
    duplicate_of_id bigint DEFAULT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    id bigint PRIMARY KEY,
    original_content_html text NOT NULL DEFAULT '',
    publish_ready_at timestamptz DEFAULT NULL,
    published_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at_verified boolean DEFAULT NULL,
    published_to_web_at timestamptz DEFAULT NULL,
    quality_score smallint NOT NULL DEFAULT 0,
    racing_region varchar(32) NOT NULL DEFAULT '',
    score_total smallint NOT NULL DEFAULT 0,
    source_config_id bigint DEFAULT NULL,
    source_language varchar(8) NOT NULL DEFAULT '',
    source_mode varchar(32) NOT NULL DEFAULT '',
    source_site varchar(32) NOT NULL DEFAULT '',
    source_url varchar(1000) NOT NULL DEFAULT '',
    summary_zh text NOT NULL DEFAULT '',
    title_ja varchar(500) NOT NULL DEFAULT '',
    title_zh varchar(500) NOT NULL DEFAULT '',
    translated_at timestamptz DEFAULT NULL,
    translated_body_zh text NOT NULL DEFAULT '',
    translated_title_zh varchar(500) NOT NULL DEFAULT '',
    translation_error_category varchar(64) NOT NULL DEFAULT '',
    translation_model varchar(128) NOT NULL DEFAULT '',
    translation_provider varchar(64) NOT NULL DEFAULT '',
    translation_retry_count integer NOT NULL DEFAULT 0,
    translation_status varchar(16) NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    withdrawn_at timestamptz DEFAULT NULL,
    workflow_status varchar(32) NOT NULL DEFAULT ''
);

CREATE TABLE public.stable_newssource (
    backoff_until timestamptz DEFAULT NULL,
    deleted_at timestamptz DEFAULT NULL,
    effective_crawl_interval_minutes integer DEFAULT NULL,
    enabled boolean NOT NULL DEFAULT false,
    failure_streak integer NOT NULL DEFAULT 0,
    id bigint PRIMARY KEY,
    last_crawl_at timestamptz DEFAULT NULL,
    last_crawl_status varchar(16) NOT NULL DEFAULT '',
    last_error_category varchar(32) NOT NULL DEFAULT '',
    production_approved boolean NOT NULL DEFAULT false,
    racing_region varchar(32) NOT NULL DEFAULT '',
    source_language varchar(8) NOT NULL DEFAULT '',
    source_mode varchar(32) NOT NULL DEFAULT '',
    source_site varchar(32) NOT NULL DEFAULT ''
);

CREATE TABLE public.stable_crawljob (
    fail_count integer NOT NULL DEFAULT 0,
    finished_at timestamptz DEFAULT NULL,
    id bigint PRIMARY KEY,
    source_id bigint DEFAULT NULL,
    started_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status varchar(16) NOT NULL DEFAULT '',
    success_count integer NOT NULL DEFAULT 0
);

CREATE TABLE public.stable_productionwindow (
    attempt_count smallint NOT NULL DEFAULT 0,
    finished_at timestamptz DEFAULT NULL,
    id bigint PRIMARY KEY,
    kind varchar(16) NOT NULL DEFAULT '',
    racing_region varchar(32) NOT NULL DEFAULT '',
    source_id bigint DEFAULT NULL,
    started_at timestamptz DEFAULT NULL,
    status varchar(16) NOT NULL DEFAULT '',
    window_end timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    window_start timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.stable_windowcandidatedecision (
    article_id bigint NOT NULL DEFAULT 0,
    id bigint PRIMARY KEY,
    rank smallint DEFAULT NULL,
    reason varchar(128) NOT NULL DEFAULT '',
    score smallint DEFAULT NULL,
    status varchar(16) NOT NULL DEFAULT '',
    window_id bigint NOT NULL DEFAULT 0
);

CREATE TABLE public.stable_racenewsexposure (
    activated_at timestamptz DEFAULT NULL,
    article_id bigint NOT NULL DEFAULT 0,
    channel varchar(16) NOT NULL DEFAULT '',
    event_id bigint NOT NULL DEFAULT 0,
    id bigint PRIMARY KEY,
    replaced_at timestamptz DEFAULT NULL,
    slot smallint NOT NULL DEFAULT 0,
    status varchar(16) NOT NULL DEFAULT ''
);

CREATE TABLE public.django_migrations (id bigint PRIMARY KEY, app varchar(255) NOT NULL, name varchar(255) NOT NULL, applied timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP);
