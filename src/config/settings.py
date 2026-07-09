from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_env: str = "local"
    app_name: str = "DocWise"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Security
    auth_enabled: bool = False
    admin_api_token: str = "change-me"
    secret_key: str = "change-me"

    # PostgreSQL
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "docwise"
    postgres_user: str = "docwise"
    postgres_password: str = "docwise"
    database_url: str = "postgresql+asyncpg://docwise:docwise@postgres:5432/docwise"
    sql_echo: bool = False

    # Redis / arq
    redis_url: str = "redis://redis:6379/0"
    arq_default_timeout: int = 1800
    arq_result_ttl: int = 86400

    # MinIO
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "docwise-documents"
    minio_secure: bool = False

    # DeepSeek
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str = ""
    llm_fast_model: str = "deepseek-v4-flash"
    llm_pro_model: str = "deepseek-v4-pro"

    # Qwen / DashScope
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_api_key: str = ""
    embedding_model: str = "text-embedding-v4"
    embedding_dim: int = 2048
    reranker_model: str = "qwen3-rerank"
    reranker_enabled: bool = True

    # Retrieval
    vector_top_k: int = 20
    keyword_top_k: int = 20
    rerank_input_top_k: int = 20
    rerank_output_top_k: int = 5
    rrf_k: int = 60
    answer_context_budget: int = 12000
    tool_planner_context_budget: int = 3500
    context_max_chunk_chars: int = 1000
    context_max_tool_result_chars: int = 2000
    context_token_estimate_safety_margin: float = 0.85
    # Retrieval score below which a chunk is eligible for eviction under budget pressure
    context_min_retrieval_score: float = 0.3
    # Minimum chars to keep when shrinking a tool result before evicting it entirely
    context_min_tool_chars: int = 400
    # Maximum number of failed tool results forwarded to tool_planner context
    context_max_failed_tools: int = 3
    # Hard-truncate parameters (last-resort, after compaction)
    context_hard_truncate_initial_ratio: float = 0.7
    context_hard_truncate_min_chars: int = 128
    context_hard_truncate_floor_chars: int = 64
    context_hard_truncate_step_ratio: float = 0.85
    # LLM compaction call parameters
    context_compaction_max_tokens: int = 300
    context_compaction_timeout: float = 20.0
    context_compaction_min_output_chars: int = 50
    context_summary_max_chars: int = 400
    context_loader_recent_turns: int = 3
    context_loader_history_limit: int = 5
    rewriter_use_history: bool = True
    rewriter_effective_query_max_chars: int = 512
    rewriter_min_effective_query_chars: int = 4
    scope_max_workspaces_tech_general: int = 2
    scope_max_workspaces_project_specific: int = 2
    scope_max_workspaces_troubleshooting: int = 3
    scope_max_workspaces_runbook_generation: int = 2
    scope_enable_followup_inheritance: bool = True
    scope_include_public_for_project_specific: bool = True
    mineru_api_base_url: str = "https://mineru.net/api/v4"
    mineru_api_key: str = ""
    mineru_request_timeout: float = 180.0
    mineru_poll_interval: float = 3.0
    mineru_daily_call_budget: int = 800
    mineru_max_result_zip_mb: int = 100
    mineru_max_result_markdown_mb: int = 50
    normalizer_cache_dir: str = "data/processed/normalized"
    normalizer_enable_fallback: bool = True

    # Upload
    max_upload_size_mb: int = 50
    allowed_file_types: str = "pdf,docx,doc,md,markdown,mdx,txt,html,htm"

    # Trace
    trace_backend: str = "local_and_langfuse"
    langfuse_enabled: bool = False
    langfuse_host: str = "http://langfuse:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_file_type_list(self) -> list[str]:
        return [t.strip() for t in self.allowed_file_types.split(",") if t.strip()]


settings = Settings()
