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
    cors_origins: str = "http://localhost:8501,http://127.0.0.1:8501"

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

    # Upload
    max_upload_size_mb: int = 50
    allowed_file_types: str = "pdf,docx,md,txt"

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
