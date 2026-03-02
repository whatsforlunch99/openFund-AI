"""Configuration loaded from environment (MILVUS_*, NEO4J_*, TAVILY_*, etc.)."""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """Application configuration from env vars.

    Attributes:
        milvus_uri: Milvus connection (or host/port).
        milvus_collection: Collection name for fund documents.
        neo4j_uri: Neo4j connection URI.
        neo4j_user: Neo4j user.
        neo4j_password: Neo4j password.
        tavily_api_key: Tavily API key.
        yahoo_base_url: Yahoo API base URL.
        yahoo_api_key: Optional Yahoo API key.
        analyst_api_url: Custom Analyst API base URL.
        analyst_api_key: Optional auth for Analyst API.
        mcp_server_endpoint: MCP server endpoint (e.g. URL or stdio).
        llm_api_key: Optional LLM provider API key.
        llm_model: Optional model name.
        memory_store_path: Root dir for conversation persistence (default memory/).
        e2e_timeout_seconds: E2E timeout in seconds (default 30).
        demo: If True, use static demo tool responses (no external APIs/DBs).
        database_url: PostgreSQL connection URL for sql_tool.
        embedding_model: Model name for embeddings.
        embedding_dim: Embedding dimension.
        planner_sufficiency_threshold: Planner sufficiency threshold (default 0.6).
        analyst_confidence_threshold: Analyst confidence threshold (default 0.6).
        responder_confidence_threshold: Responder confidence threshold (default 0.75).
        permission_enabled: Enable/disable permission checks (default False).
        permission_default_classification: Default classification for untagged data.
        permission_policy_file: Path to custom policy JSON file.
        permission_audit_enabled: Enable access audit logging.
        permission_audit_file: Path to audit log file.
        permission_cache_ttl: Policy cache TTL in seconds.
        jwt_secret_key: Secret for JWT validation (production auth).
        jwt_algorithm: JWT algorithm (default HS256).
        jwt_audience: Expected JWT audience claim.
    """

    milvus_uri: str = ""
    milvus_collection: str = ""
    neo4j_uri: str = ""
    neo4j_user: str = ""
    neo4j_password: str = ""
    tavily_api_key: str = ""
    yahoo_base_url: str = ""
    yahoo_api_key: Optional[str] = None
    analyst_api_url: str = ""
    analyst_api_key: Optional[str] = None
    mcp_server_endpoint: str = ""
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    memory_store_path: str = "memory"
    e2e_timeout_seconds: int = 30
    demo: bool = False
    database_url: str = ""
    embedding_model: str = ""
    embedding_dim: int = 0
    planner_sufficiency_threshold: float = 0.6
    analyst_confidence_threshold: float = 0.6
    responder_confidence_threshold: float = 0.75
    permission_enabled: bool = False
    permission_default_classification: str = "PUBLIC"
    permission_policy_file: str = ""
    permission_audit_enabled: bool = False
    permission_audit_file: str = "logs/access.log"
    permission_cache_ttl: int = 300
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_audience: str = "openfund-ai"


def load_config() -> Config:
    """Load configuration from environment variables.

    Loads .env from the current directory if python-dotenv is installed and .env exists.
    Then reads MILVUS_*, NEO4J_*, TAVILY_API_KEY, YAHOO_*, ANALYST_API_*,
    MCP server endpoint, MEMORY_STORE_PATH, E2E_TIMEOUT_SECONDS,
    DATABASE_URL, EMBEDDING_*, thresholds, and optional LLM/feature flags.
    Demo is True when OPENFUND_DEMO or DEMO is set (e.g. 1, true, yes).

    Returns:
        Config instance populated from env.
    """
    # Load .env so env vars are set before reading (optional if python-dotenv not installed).
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    def _int(key: str, default: int) -> int:
        """Parse env as int; return default if missing or invalid."""
        try:
            return int(os.getenv(key, str(default)))
        except ValueError:
            return default

    def _float(key: str, default: float) -> float:
        """Parse env as float; return default if missing or invalid."""
        try:
            return float(os.getenv(key, str(default)))
        except ValueError:
            return default

    def _bool(key: str, default: bool) -> bool:
        """Parse env as bool; true if key is 1, true, yes, on."""
        v = (os.getenv(key) or "").strip().lower()
        if not v:
            return default
        return v in ("1", "true", "yes", "on")

    return Config(
        milvus_uri=os.getenv("MILVUS_URI", ""),
        milvus_collection=os.getenv("MILVUS_COLLECTION", ""),
        neo4j_uri=os.getenv("NEO4J_URI", ""),
        neo4j_user=os.getenv("NEO4J_USER", ""),
        neo4j_password=os.getenv("NEO4J_PASSWORD", ""),
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
        yahoo_base_url=os.getenv("YAHOO_BASE_URL", ""),
        yahoo_api_key=os.getenv("YAHOO_API_KEY") or None,
        analyst_api_url=os.getenv("ANALYST_API_URL", ""),
        analyst_api_key=os.getenv("ANALYST_API_KEY") or None,
        mcp_server_endpoint=os.getenv("MCP_SERVER_ENDPOINT", ""),
        llm_api_key=os.getenv("LLM_API_KEY") or None,
        llm_model=os.getenv("LLM_MODEL") or None,
        memory_store_path=os.getenv("MEMORY_STORE_PATH", "memory"),
        e2e_timeout_seconds=_int("E2E_TIMEOUT_SECONDS", 30),
        demo=_bool("OPENFUND_DEMO", False) or _bool("DEMO", False),
        database_url=os.getenv("DATABASE_URL", ""),
        embedding_model=os.getenv("EMBEDDING_MODEL", ""),
        embedding_dim=_int("EMBEDDING_DIM", 0),
        planner_sufficiency_threshold=_float("PLANNER_SUFFICIENCY_THRESHOLD", 0.6),
        analyst_confidence_threshold=_float("ANALYST_CONFIDENCE_THRESHOLD", 0.6),
        responder_confidence_threshold=_float("RESPONDER_CONFIDENCE_THRESHOLD", 0.75),
        permission_enabled=_bool("PERMISSION_ENABLED", False),
        permission_default_classification=os.getenv("PERMISSION_DEFAULT_CLASSIFICATION", "PUBLIC"),
        permission_policy_file=os.getenv("PERMISSION_POLICY_FILE", ""),
        permission_audit_enabled=_bool("PERMISSION_AUDIT_ENABLED", False),
        permission_audit_file=os.getenv("PERMISSION_AUDIT_FILE", "logs/access.log"),
        permission_cache_ttl=_int("PERMISSION_CACHE_TTL", 300),
        jwt_secret_key=os.getenv("JWT_SECRET_KEY", ""),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        jwt_audience=os.getenv("JWT_AUDIENCE", "openfund-ai"),
    )
