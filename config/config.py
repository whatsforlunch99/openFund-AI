"""Configuration loaded from environment (MILVUS_*, NEO4J_*, TAVILY_*, etc.)."""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """
    Application configuration from env vars.

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


def load_config() -> Config:
    """
    Load configuration from environment variables.

    Reads MILVUS_*, NEO4J_*, TAVILY_API_KEY, YAHOO_*, ANALYST_API_*,
    MCP server endpoint, and optional LLM/feature flags.

    Returns:
        Config instance populated from env.
    """
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
    )
