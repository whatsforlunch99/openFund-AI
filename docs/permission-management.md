# Permission Management Module Design

> **Status**: Design document for future implementation. Not yet implemented.  
> **PRD Reference**: Authentication/authorization is out of scope for current phase per [prd.md](prd.md).  
> **Last Updated**: 2026-03-02

Unified access control for the OpenFund-AI multi-agent system. This document describes the architecture, data model, and integration points for permission management across all storage backends (PostgreSQL, Neo4j, Milvus) and the agent layer.

---

## 1. Overview

### 1.1 Design Goals

1. **Data Tagging at Ingestion**: Embed permission labels during data collection (via DataManagerAgent) so permissions flow with data.
2. **Hybrid Permission Model**: Support RBAC (Role-Based Access Control), ABAC (Attribute-Based Access Control), and data classification.
3. **Cross-Storage Consistency**: Enforce permissions uniformly across:
   - Raw data (JSON files in `datasets/`)
   - PostgreSQL (structured data)
   - Neo4j (knowledge graph)
   - Milvus (vector embeddings)
4. **Agent-Layer Authorization**: Dynamic permission evaluation at query time.
5. **Audit Trail**: Log all access attempts for compliance and debugging.

### 1.2 Architecture Position

```
                    ┌──────────────────┐
                    │    REST / WS     │
                    │      API         │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  SafetyGateway   │  ← Input validation, PII masking
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
            ┌───────┤ PermissionEngine │───────┐  ← NEW: Authorization layer
            │       └────────┬─────────┘       │
            │                │                 │
    ┌───────▼───────┐  ┌─────▼─────┐  ┌───────▼───────┐
    │ PlannerAgent  │  │  Agents   │  │ DataManager   │
    │               │  │ (L/W/A/R) │  │    Agent      │
    └───────┬───────┘  └─────┬─────┘  └───────┬───────┘
            │                │                 │
            └────────────────┼─────────────────┘
                             │
                    ┌────────▼─────────┐
                    │    MCPServer     │
                    │   (Tool Layer)   │
                    └────────┬─────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
   ┌────▼────┐         ┌─────▼─────┐        ┌─────▼─────┐
   │PostgreSQL│         │   Neo4j   │        │   Milvus  │
   │(sql_tool)│         │ (kg_tool) │        │(vector_tool)│
   └──────────┘         └───────────┘        └───────────┘
```

### 1.3 Key Components

| Component | Location | Responsibility |
|-----------|----------|----------------|
| PermissionEngine | `permission/engine.py` | Core authorization logic; evaluates policies |
| AccessControlData | `permission/models.py` | Data structures for access control metadata |
| PermissionPolicy | `permission/policy.py` | Policy definitions and matching |
| PermissionConfig | `config/config.py` | Configuration from environment |
| AuditLogger | `permission/audit.py` | Access logging for compliance |
| PermissionFilter | `permission/filters.py` | Query filters for each database type |

---

## 2. Data Model

### 2.1 Access Control Schema

Every data record includes an `access_control` object with the following fields:

```python
@dataclass
class AccessControl:
    """Access control metadata embedded in data records."""
    
    classification: str  # PUBLIC | INTERNAL | CONFIDENTIAL | RESTRICTED
    classification_level: int  # Numeric: 0=PUBLIC, 1=INTERNAL, 2=CONFIDENTIAL, 3=RESTRICTED
    tenant_id: str       # Organization/team identifier
    roles_allowed: list[str]   # Roles that can access (RBAC)
    users_allowed: list[str]   # Specific users that can access (ABAC)
    source: str          # Data source identifier
    region: str          # Geographic region for compliance
    expiry_date: str | None  # Optional expiration (ISO format, timezone-aware)
    owner: str           # Data owner identifier
    created_at: str      # Creation timestamp (ISO format)
    
    def __post_init__(self):
        """Ensure classification_level matches classification."""
        expected_level = CLEARANCE_HIERARCHY.get(self.classification, 0)
        if self.classification_level != expected_level:
            self.classification_level = expected_level
```

**Note**: `classification_level` is the numeric representation of `classification` for efficient database comparisons. Both fields must be kept in sync (enforced by `__post_init__` and database triggers).

### 2.2 Data Classification Levels

| Level | Code | Access Scope | Example Data |
|-------|------|--------------|--------------|
| Public | `PUBLIC` | Anyone, including unauthenticated | Market prices, public filings |
| Internal | `INTERNAL` | All authenticated users within tenant | Internal research notes |
| Confidential | `CONFIDENTIAL` | Specific roles only | Portfolio strategies |
| Restricted | `RESTRICTED` | Specific users only | Client PII, proprietary models |

### 2.3 User Context

```python
@dataclass
class UserContext:
    """User identity and attributes for authorization."""
    
    user_id: str              # Unique user identifier
    tenant_id: str            # Organization the user belongs to
    roles: list[str]          # User's roles (e.g., ["analyst", "admin"])
    attributes: dict[str, Any]  # Additional attributes for ABAC
    clearance_level: str      # Maximum classification user can access
```

### 2.4 Clearance Level Hierarchy

```python
CLEARANCE_HIERARCHY = {
    "PUBLIC": 0,
    "INTERNAL": 1,
    "CONFIDENTIAL": 2,
    "RESTRICTED": 3,
}
```

A user can access data if their clearance level >= data classification level.

---

## 3. Permission Engine

### 3.1 Core Interface

```python
# permission/engine.py

class PermissionEngine:
    """
    Central authorization engine for all data access.
    
    Evaluates user context against data access control to determine
    if access should be granted. Generates database-specific filters
    for authorized queries.
    """
    
    def __init__(
        self,
        policy_store: PolicyStore,
        audit_logger: AuditLogger,
    ) -> None:
        """
        Initialize the permission engine.
        
        Args:
            policy_store: Storage for permission policies.
            audit_logger: Logger for access audit trail.
        """
        self.policy_store = policy_store
        self.audit_logger = audit_logger
    
    def evaluate(
        self,
        user: UserContext,
        resource: AccessControl,
        action: str = "read",
    ) -> PermissionResult:
        """
        Evaluate if user can access resource.
        
        Args:
            user: User context with identity and roles.
            resource: Access control metadata of the resource.
            action: Action being performed (read, write, delete).
        
        Returns:
            PermissionResult with allowed flag and reason.
        """
        pass
    
    def sql_filter(self, user: UserContext) -> str:
        """
        Generate SQL WHERE clause for PostgreSQL queries.
        
        Args:
            user: User context for filter generation.
        
        Returns:
            SQL WHERE clause string (e.g., "classification = 'PUBLIC' OR ...").
        """
        pass
    
    def neo4j_filter(self, user: UserContext) -> str:
        """
        Generate Cypher WHERE clause for Neo4j queries.
        
        Args:
            user: User context for filter generation.
        
        Returns:
            Cypher WHERE clause string.
        """
        pass
    
    def milvus_filter(self, user: UserContext) -> str:
        """
        Generate filter expression for Milvus queries.
        
        Args:
            user: User context for filter generation.
        
        Returns:
            Milvus filter expression string.
        """
        pass
    
    def tag_data(
        self,
        data: dict,
        source: str,
        policy_name: str | None = None,
    ) -> dict:
        """
        Apply access control tags to data based on source and policy.
        
        Used during data ingestion (DataManagerAgent) to embed
        permission metadata.
        
        Args:
            data: Raw data to tag.
            source: Data source identifier.
            policy_name: Optional policy to apply; auto-selects if None.
        
        Returns:
            Data with access_control field added.
        """
        pass
```

### 3.2 Permission Evaluation Logic

```python
def evaluate(
    self,
    user: UserContext,
    resource: AccessControl,
    action: str = "read",
) -> PermissionResult:
    """
    Multi-step evaluation:
    1. Check data expiry
    2. Check clearance level vs classification (using numeric hierarchy)
    3. Check tenant match (if not PUBLIC)
    4. Check RBAC OR ABAC (roles_allowed OR users_allowed)
    5. Log access attempt (both allowed and denied)
    """
    # Helper to log and return denial
    def deny(reason: str) -> PermissionResult:
        self.audit_logger.log_access(user, resource, action, allowed=False, reason=reason)
        return PermissionResult(allowed=False, reason=reason)
    
    # Step 1: Check expiry
    if resource.expiry_date:
        if datetime.fromisoformat(resource.expiry_date) < datetime.now(timezone.utc):
            return deny("Data expired")
    
    # Step 2: Classification vs clearance (PUBLIC data allows all)
    if resource.classification == "PUBLIC":
        self.audit_logger.log_access(user, resource, action, allowed=True, reason="Public data")
        return PermissionResult(allowed=True, reason="Public data")
    
    user_level = CLEARANCE_HIERARCHY.get(user.clearance_level, 0)
    data_level = CLEARANCE_HIERARCHY.get(resource.classification, 3)
    if user_level < data_level:
        return deny(f"Insufficient clearance: {user.clearance_level} < {resource.classification}")
    
    # Step 3: Tenant check
    if resource.tenant_id and resource.tenant_id != user.tenant_id:
        return deny("Tenant mismatch")
    
    # Step 4: RBAC OR ABAC (either condition grants access)
    # If both lists are empty, clearance + tenant is sufficient
    has_role_restriction = bool(resource.roles_allowed)
    has_user_restriction = bool(resource.users_allowed)
    
    if has_role_restriction or has_user_restriction:
        role_match = has_role_restriction and any(
            role in resource.roles_allowed for role in user.roles
        )
        user_match = has_user_restriction and user.user_id in resource.users_allowed
        
        if not (role_match or user_match):
            return deny("Neither role nor user authorized")
    
    # Log and allow
    self.audit_logger.log_access(user, resource, action, allowed=True, reason="Access granted")
    return PermissionResult(allowed=True, reason="Access granted")
```

### 3.3 Filter Generation

> **Security Note**: All filter methods return parameterized queries (clause + params dict) to prevent SQL/Cypher injection. Never concatenate user input directly into query strings.

#### PostgreSQL Filter

```python
@dataclass
class SQLFilter:
    """Parameterized SQL filter result."""
    clause: str
    params: dict[str, Any]


def sql_filter(self, user: UserContext) -> SQLFilter:
    """
    Generate parameterized PostgreSQL WHERE clause.
    
    Uses numeric clearance comparison and checks expiry_date.
    Returns clause with named parameters for safe execution.
    
    Example:
        filter = engine.sql_filter(user)
        cursor.execute(f"SELECT * FROM table WHERE {filter.clause}", filter.params)
    """
    # Map clearance to numeric level for comparison
    user_level = CLEARANCE_HIERARCHY.get(user.clearance_level, 0)
    
    params = {
        "tenant_id": user.tenant_id,
        "user_id": user.user_id,
        "roles": user.roles,
        "clearance_level": user_level,
    }
    
    clause = """
        (
            classification = 'PUBLIC'
        )
        OR (
            -- Tenant match
            tenant_id = %(tenant_id)s
            -- Clearance check using numeric hierarchy
            AND classification_level <= %(clearance_level)s
            -- Not expired
            AND (expiry_date IS NULL OR expiry_date > NOW())
            -- RBAC OR ABAC
            AND (
                roles_allowed IS NULL
                OR cardinality(roles_allowed) = 0
                OR roles_allowed ?| %(roles)s
                OR users_allowed ? %(user_id)s
            )
        )
    """
    
    return SQLFilter(clause=clause, params=params)
```

**Note**: Requires a `classification_level` integer column (or computed via CASE WHEN) for proper hierarchy comparison. See Section 5.1 for schema.

#### Neo4j Filter

```python
@dataclass
class CypherFilter:
    """Parameterized Cypher filter result."""
    clause: str
    params: dict[str, Any]


def neo4j_filter(self, user: UserContext) -> CypherFilter:
    """
    Generate parameterized Cypher WHERE clause for node filtering.
    
    Checks ALL user roles (not just the first one) using ANY().
    Returns clause with parameters for safe execution.
    
    Example:
        filter = engine.neo4j_filter(user)
        session.run(f"MATCH (n) WHERE {filter.clause} RETURN n", filter.params)
    """
    user_level = CLEARANCE_HIERARCHY.get(user.clearance_level, 0)
    
    params = {
        "tenant_id": user.tenant_id,
        "user_id": user.user_id,
        "roles": user.roles,
        "clearance_level": user_level,
    }
    
    clause = """
        n.classification = 'PUBLIC'
        OR (
            n.tenant_id = $tenant_id
            AND n.classification_level <= $clearance_level
            AND (n.expiry_date IS NULL OR n.expiry_date > datetime())
            AND (
                n.roles_allowed IS NULL
                OR size(n.roles_allowed) = 0
                OR ANY(role IN $roles WHERE role IN n.roles_allowed)
                OR $user_id IN n.users_allowed
            )
        )
    """
    
    return CypherFilter(clause=clause, params=params)
```

#### Milvus Filter

```python
@dataclass
class MilvusFilter:
    """Milvus filter with post-filter function for complex RBAC."""
    expr: str
    post_filter: Callable[[list[dict]], list[dict]] | None


def milvus_filter(self, user: UserContext) -> MilvusFilter:
    """
    Generate Milvus boolean expression for metadata filtering.
    
    Milvus has limited expression capabilities (no array intersection).
    Strategy:
    1. Pre-filter: classification and tenant (efficient in Milvus)
    2. Post-filter: RBAC/ABAC check in Python after retrieval
    
    Example:
        filter = engine.milvus_filter(user)
        results = collection.search(..., expr=filter.expr)
        if filter.post_filter:
            results = filter.post_filter(results)
    """
    user_level = CLEARANCE_HIERARCHY.get(user.clearance_level, 0)
    
    # Pre-filter: what Milvus can handle efficiently
    # Note: Values are safe here because they come from validated UserContext
    expr = f'''
        classification == "PUBLIC"
        or (
            tenant_id == "{_escape_milvus_string(user.tenant_id)}"
            and classification_level <= {user_level}
        )
    '''
    
    # Post-filter: check roles/users after retrieval
    def post_filter(results: list[dict]) -> list[dict]:
        filtered = []
        for item in results:
            if item.get("classification") == "PUBLIC":
                filtered.append(item)
                continue
            
            roles_allowed = item.get("roles_allowed", [])
            users_allowed = item.get("users_allowed", [])
            
            # If no restrictions, allow
            if not roles_allowed and not users_allowed:
                filtered.append(item)
                continue
            
            # Check RBAC OR ABAC
            role_match = any(r in roles_allowed for r in user.roles)
            user_match = user.user_id in users_allowed
            if role_match or user_match:
                filtered.append(item)
        
        return filtered
    
    return MilvusFilter(expr=expr, post_filter=post_filter)


def _escape_milvus_string(s: str) -> str:
    """Escape special characters for Milvus string literals."""
    return s.replace('\\', '\\\\').replace('"', '\\"')
```

---

## 4. Policy Management

### 4.1 Policy Definition

```python
# permission/policy.py

@dataclass
class PermissionPolicy:
    """
    Named policy that defines default access control for a data source.
    
    Policies are matched by source name/pattern and applied during
    data ingestion to generate access_control metadata.
    """
    
    name: str                     # Policy identifier
    source_pattern: str           # Regex pattern to match data source
    default_classification: str   # Default classification level
    default_tenant: str           # Default tenant (or empty for source-based)
    default_roles: list[str]      # Default roles allowed
    allow_owner_override: bool    # Can data owner override defaults
    expiry_days: int | None       # Auto-expiry in days (None = no expiry)
    region_restrictions: list[str]  # Allowed regions (empty = all)
```

### 4.2 Built-in Policies

```python
DEFAULT_POLICIES = [
    # Public market data - anyone can access
    PermissionPolicy(
        name="public_market_data",
        source_pattern=r"^(yfinance|alpha_vantage|public_api).*",
        default_classification="PUBLIC",
        default_tenant="",
        default_roles=[],
        allow_owner_override=False,
        expiry_days=None,
        region_restrictions=[],
    ),
    # Internal research - analysts only
    PermissionPolicy(
        name="internal_research",
        source_pattern=r"^internal_.*",
        default_classification="INTERNAL",
        default_tenant="",  # Inherit from collector
        default_roles=["analyst", "researcher"],
        allow_owner_override=True,
        expiry_days=365,
        region_restrictions=[],
    ),
    # Premium data - subscribed roles
    PermissionPolicy(
        name="premium_data",
        source_pattern=r"^(morningstar|bloomberg|refinitiv).*",
        default_classification="CONFIDENTIAL",
        default_tenant="",
        default_roles=["premium_user", "analyst"],
        allow_owner_override=False,
        expiry_days=None,
        region_restrictions=[],
    ),
    # Client data - restricted
    PermissionPolicy(
        name="client_data",
        source_pattern=r"^client_.*",
        default_classification="RESTRICTED",
        default_tenant="",
        default_roles=["client_manager"],
        allow_owner_override=False,
        expiry_days=90,
        region_restrictions=[],
    ),
]
```

### 4.3 Policy Store

```python
# permission/policy.py

class PolicyStore:
    """
    Storage and lookup for permission policies.
    
    Policies can be loaded from:
    - Built-in defaults (DEFAULT_POLICIES)
    - JSON configuration file (PERMISSION_POLICY_FILE env var)
    - Database (future: PostgreSQL policy table)
    """
    
    def __init__(self) -> None:
        self._policies: dict[str, PermissionPolicy] = {}
        self._load_defaults()
    
    def _load_defaults(self) -> None:
        for policy in DEFAULT_POLICIES:
            self._policies[policy.name] = policy
    
    def load_from_file(self, path: str) -> None:
        """Load policies from JSON file."""
        pass
    
    def get_policy(self, name: str) -> PermissionPolicy | None:
        """Get policy by name."""
        return self._policies.get(name)
    
    def match_policy(self, source: str) -> PermissionPolicy | None:
        """Find first policy matching the source pattern."""
        import re
        for policy in self._policies.values():
            if re.match(policy.source_pattern, source):
                return policy
        return None
    
    def add_policy(self, policy: PermissionPolicy) -> None:
        """Register a new policy."""
        self._policies[policy.name] = policy
```

---

## 5. Database Schema Extensions

### 5.1 PostgreSQL Schema

Add access control columns to existing tables:

```sql
-- Access control columns (add to all data tables)
ALTER TABLE stock_ohlcv ADD COLUMN IF NOT EXISTS
    classification VARCHAR(20) DEFAULT 'PUBLIC',
    classification_level SMALLINT DEFAULT 0,  -- Numeric: 0=PUBLIC, 1=INTERNAL, 2=CONFIDENTIAL, 3=RESTRICTED
    tenant_id VARCHAR(50),
    roles_allowed JSONB DEFAULT '[]',
    users_allowed JSONB DEFAULT '[]',
    source VARCHAR(100),
    region VARCHAR(20),
    expiry_date TIMESTAMP WITH TIME ZONE,
    owner VARCHAR(50),
    ac_created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

-- Trigger to sync classification_level from classification
CREATE OR REPLACE FUNCTION sync_classification_level()
RETURNS TRIGGER AS $$
BEGIN
    NEW.classification_level := CASE NEW.classification
        WHEN 'PUBLIC' THEN 0
        WHEN 'INTERNAL' THEN 1
        WHEN 'CONFIDENTIAL' THEN 2
        WHEN 'RESTRICTED' THEN 3
        ELSE 0
    END;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sync_classification_level
    BEFORE INSERT OR UPDATE OF classification ON stock_ohlcv
    FOR EACH ROW EXECUTE FUNCTION sync_classification_level();

-- Create index for permission filtering
CREATE INDEX IF NOT EXISTS idx_stock_ohlcv_access
ON stock_ohlcv (classification_level, tenant_id);

CREATE INDEX IF NOT EXISTS idx_stock_ohlcv_roles
ON stock_ohlcv USING GIN (roles_allowed);

CREATE INDEX IF NOT EXISTS idx_stock_ohlcv_expiry
ON stock_ohlcv (expiry_date) WHERE expiry_date IS NOT NULL;

-- View with Row-Level Security (RLS) - optional for advanced deployments
-- Enable RLS on table
ALTER TABLE stock_ohlcv ENABLE ROW LEVEL SECURITY;

-- Policy: users see PUBLIC or their tenant's data with matching role/user
-- Session variables set via: SET app.tenant_id = 'xxx'; SET app.user_id = 'yyy'; SET app.user_roles = 'role1,role2';
CREATE POLICY stock_ohlcv_access_policy ON stock_ohlcv
    FOR SELECT
    USING (
        -- Not expired
        (expiry_date IS NULL OR expiry_date > NOW())
        AND (
            -- Public data
            classification = 'PUBLIC'
            OR (
                -- Tenant match
                tenant_id = current_setting('app.tenant_id', true)
                -- Clearance check
                AND classification_level <= COALESCE(current_setting('app.clearance_level', true)::int, 0)
                -- RBAC OR ABAC (role intersection or user in list)
                AND (
                    roles_allowed = '[]'::jsonb
                    OR roles_allowed ?| string_to_array(current_setting('app.user_roles', true), ',')
                    OR users_allowed ? current_setting('app.user_id', true)
                )
            )
        )
    );
```

### 5.2 Neo4j Schema

Add access control properties to nodes:

```cypher
// Add access control properties to nodes
// Use during MERGE/CREATE operations

MERGE (c:Company {symbol: $symbol})
SET c.classification = $classification,
    c.classification_level = CASE $classification
        WHEN 'PUBLIC' THEN 0
        WHEN 'INTERNAL' THEN 1
        WHEN 'CONFIDENTIAL' THEN 2
        WHEN 'RESTRICTED' THEN 3
        ELSE 0
    END,
    c.tenant_id = $tenant_id,
    c.roles_allowed = $roles_allowed,
    c.users_allowed = $users_allowed,
    c.source = $source,
    c.region = $region,
    c.expiry_date = $expiry_date,
    c.owner = $owner,
    c.ac_created_at = datetime()

// Create constraint for required fields
CREATE CONSTRAINT IF NOT EXISTS FOR (n:Company)
REQUIRE n.classification IS NOT NULL

// Indexes for access filtering
CREATE INDEX IF NOT EXISTS FOR (n:Company) ON (n.classification_level, n.tenant_id)
CREATE INDEX IF NOT EXISTS FOR (n:Company) ON (n.expiry_date)
```

### 5.3 Milvus Schema

Update collection schema to include access control metadata:

```python
MILVUS_ACCESS_CONTROL_FIELDS = [
    FieldSchema(name="classification", dtype=DataType.VARCHAR, max_length=20),
    FieldSchema(name="classification_level", dtype=DataType.INT8),  # 0-3 for hierarchy comparison
    FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=50),
    FieldSchema(name="roles_allowed", dtype=DataType.VARCHAR, max_length=500),  # JSON array as string
    FieldSchema(name="users_allowed", dtype=DataType.VARCHAR, max_length=500),  # JSON array as string
    FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=100),
    FieldSchema(name="owner", dtype=DataType.VARCHAR, max_length=50),
    FieldSchema(name="expiry_date", dtype=DataType.VARCHAR, max_length=30),  # ISO format or empty
]

# Update vector_tool.create_collection_from_config to include these fields
# Note: roles_allowed and users_allowed are stored as JSON strings, parsed in post_filter
```

---

## 6. Integration Points

### 6.1 API Layer Integration

Modify `api/rest.py` to extract and inject user context:

```python
# api/rest.py

class ChatRequest(BaseModel):
    query: str
    user_profile: str = "beginner"
    user_id: str = ""
    conversation_id: Optional[str] = None
    path: Optional[str] = None
    # NEW: Optional auth token for permission context
    auth_token: Optional[str] = None


def _extract_user_context(body: ChatRequest) -> UserContext:
    """
    Extract user context from request.
    
    In production, decode auth_token (JWT) to get user identity.
    For MVP, use user_id with default permissions.
    """
    if body.auth_token:
        # Decode JWT and extract claims
        return _decode_token(body.auth_token)
    
    # Default context for unauthenticated or simple user_id
    return UserContext(
        user_id=body.user_id or "anonymous",
        tenant_id="default",
        roles=["public_user"],
        attributes={},
        clearance_level="PUBLIC",
    )


@app.post("/chat")
def post_chat_endpoint(body: ChatRequest) -> JSONResponse:
    # Extract user context
    user_context = _extract_user_context(body)
    
    # Inject into conversation content for downstream use
    content = {
        "query": body.query,
        "conversation_id": conversation_id,
        "user_profile": body.user_profile,
        "user_context": asdict(user_context),  # NEW
    }
    # ... rest of handler
```

### 6.2 MCP Tool Integration

Wrap MCP tools to apply permission filters. Use SQL parsing (via `sqlglot`) for safe query modification instead of string replacement.

```python
# mcp/tools/sql_tool.py

import sqlglot
from sqlglot import exp

def run_query_with_permissions(
    query: str,
    params: dict | None = None,
    user_context: UserContext | None = None,
) -> dict:
    """
    Execute SQL query with permission filtering.
    
    If user_context is provided, injects permission WHERE clause
    using SQL AST parsing (for SELECT only).
    
    For write operations (INSERT/UPDATE/DELETE), permission checks
    are performed separately before execution.
    """
    params = params or {}
    
    if not user_context:
        return run_query(query, params)
    
    # Parse query to determine type
    try:
        parsed = sqlglot.parse_one(query, dialect="postgres")
    except sqlglot.errors.ParseError:
        # If parsing fails, reject query for safety
        return {"error": "Unable to parse query for permission filtering"}
    
    # Only filter SELECT queries; reject write operations without explicit check
    if not isinstance(parsed, exp.Select):
        if isinstance(parsed, (exp.Insert, exp.Update, exp.Delete)):
            return {"error": "Write operations require explicit permission check"}
        return run_query(query, params)
    
    # Get permission filter
    engine = get_permission_engine()
    sql_filter = engine.sql_filter(user_context)
    
    # Merge filter params into query params
    params.update(sql_filter.params)
    
    # Inject filter into AST
    filter_condition = sqlglot.parse_one(sql_filter.clause, dialect="postgres")
    
    if parsed.args.get("where"):
        # Existing WHERE: AND with permission filter
        new_where = exp.And(this=parsed.args["where"].this, expression=filter_condition)
        parsed.args["where"].set("this", new_where)
    else:
        # No WHERE: add one
        parsed = parsed.where(filter_condition)
    
    # Generate final query
    final_query = parsed.sql(dialect="postgres")
    
    return run_query(final_query, params)


def check_write_permission(
    user_context: UserContext,
    table: str,
    action: str,  # "insert", "update", "delete"
    target_classification: str = "PUBLIC",
) -> bool:
    """
    Check if user can perform write operation on table.
    
    For inserts: user must have clearance >= target_classification.
    For updates/deletes: additional row-level checks needed.
    """
    engine = get_permission_engine()
    user_level = CLEARANCE_HIERARCHY.get(user_context.clearance_level, 0)
    target_level = CLEARANCE_HIERARCHY.get(target_classification, 0)
    
    return user_level >= target_level
```

**Alternative (RLS-based)**: Instead of application-level filtering, use PostgreSQL RLS policies (Section 5.1). Set session parameters before query:

```python
def set_session_context(conn, user: UserContext) -> None:
    """Set PostgreSQL session parameters for RLS policies."""
    with conn.cursor() as cur:
        cur.execute("SET app.tenant_id = %s", (user.tenant_id,))
        cur.execute("SET app.user_id = %s", (user.user_id,))
        cur.execute("SET app.user_roles = %s", (",".join(user.roles),))
        cur.execute("SET app.clearance_level = %s", (CLEARANCE_HIERARCHY.get(user.clearance_level, 0),))
```

### 6.3 DataManagerAgent Integration

Tag data during collection:

```python
# data_manager/collector.py

class DataCollector:
    def __init__(self, permission_engine: PermissionEngine | None = None):
        self.permission_engine = permission_engine or get_permission_engine()
    
    def collect_symbol(self, symbol: str, as_of_date: str) -> CollectionResult:
        # ... existing collection logic ...
        
        for task in COLLECTION_TASKS:
            data = self._fetch_data(task, symbol, as_of_date)
            
            # Tag data with access control
            tagged_data = self.permission_engine.tag_data(
                data=data,
                source=task.tool_name,
                policy_name=None,  # Auto-match by source
            )
            
            self._save_to_file(tagged_data, task, symbol, as_of_date)
```

### 6.4 Agent Message Integration

Pass user context through agent messages:

```python
# a2a/acl_message.py

@dataclass
class ACLMessage:
    performative: Performative
    sender: str
    receiver: str
    content: dict
    conversation_id: str = ""
    reply_to: Optional[str] = None
    in_reply_to: Optional[str] = None
    timestamp: Optional[str] = None
    # NEW: User context for permission checks
    user_context: Optional[dict] = None
```

---

## 7. Configuration

### 7.1 Environment Variables

```bash
# Permission module configuration
PERMISSION_ENABLED=true                    # Enable/disable permission checks
PERMISSION_DEFAULT_CLASSIFICATION=PUBLIC   # Default for untagged data
PERMISSION_POLICY_FILE=config/policies.json  # Custom policy definitions
PERMISSION_AUDIT_ENABLED=true              # Enable access logging
PERMISSION_AUDIT_FILE=logs/access.log      # Audit log location
PERMISSION_CACHE_TTL=300                   # Policy cache TTL in seconds

# JWT configuration (for production auth)
JWT_SECRET_KEY=                            # Secret for JWT validation
JWT_ALGORITHM=HS256                        # JWT algorithm
JWT_AUDIENCE=openfund-ai                   # Expected audience claim
```

### 7.2 Config Class Extension

```python
# config/config.py

@dataclass
class Config:
    # ... existing fields ...
    
    # Permission settings
    permission_enabled: bool = False
    permission_default_classification: str = "PUBLIC"
    permission_policy_file: str = ""
    permission_audit_enabled: bool = False
    permission_audit_file: str = "logs/access.log"
    permission_cache_ttl: int = 300
    
    # JWT settings (production)
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_audience: str = "openfund-ai"


def load_config() -> Config:
    # ... existing loading ...
    
    return Config(
        # ... existing fields ...
        permission_enabled=_bool("PERMISSION_ENABLED", False),
        permission_default_classification=os.getenv(
            "PERMISSION_DEFAULT_CLASSIFICATION", "PUBLIC"
        ),
        permission_policy_file=os.getenv("PERMISSION_POLICY_FILE", ""),
        permission_audit_enabled=_bool("PERMISSION_AUDIT_ENABLED", False),
        permission_audit_file=os.getenv("PERMISSION_AUDIT_FILE", "logs/access.log"),
        permission_cache_ttl=_int("PERMISSION_CACHE_TTL", 300),
        jwt_secret_key=os.getenv("JWT_SECRET_KEY", ""),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        jwt_audience=os.getenv("JWT_AUDIENCE", "openfund-ai"),
    )
```

---

## 8. Audit Logging

### 8.1 Audit Record Structure

```python
# permission/audit.py

@dataclass
class AuditRecord:
    """Single access audit log entry."""
    
    timestamp: str           # ISO format
    user_id: str
    tenant_id: str
    action: str              # read, write, delete
    resource_type: str       # table name, node label, collection
    resource_id: str         # Primary key or identifier
    classification: str      # Data classification accessed
    allowed: bool            # Was access granted
    reason: str              # Why allowed/denied
    source_ip: str | None    # Client IP if available
    conversation_id: str | None  # Associated conversation
```

### 8.2 Audit Logger

```python
# permission/audit.py

class AuditLogger:
    """
    Async-safe access audit logger.
    
    Writes to file and optionally to database for compliance reporting.
    """
    
    def __init__(self, config: Config) -> None:
        self.enabled = config.permission_audit_enabled
        self.file_path = config.permission_audit_file
        self._buffer: list[AuditRecord] = []
        self._lock = threading.Lock()
    
    def log_access(
        self,
        user: UserContext,
        resource: AccessControl,
        action: str,
        allowed: bool,
        reason: str = "",
        resource_type: str = "",
        resource_id: str = "",
        conversation_id: str | None = None,
    ) -> None:
        """Log an access attempt."""
        if not self.enabled:
            return
        
        record = AuditRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            user_id=user.user_id,
            tenant_id=user.tenant_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            classification=resource.classification,
            allowed=allowed,
            reason=reason,
            source_ip=None,
            conversation_id=conversation_id,
        )
        
        with self._lock:
            self._buffer.append(record)
            if len(self._buffer) >= 100:
                self._flush()
    
    def _flush(self) -> None:
        """Write buffered records to file."""
        if not self._buffer:
            return
        
        import json
        import os
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        
        with open(self.file_path, "a") as f:
            for record in self._buffer:
                f.write(json.dumps(asdict(record)) + "\n")
        
        self._buffer.clear()
```

---

## 9. Data Masking and Desensitization

### 9.1 Field-Level Masking

For sensitive data that passes authorization but should be partially hidden:

```python
# permission/masking.py

@dataclass
class MaskingRule:
    """Rule for field-level data masking."""
    
    field_pattern: str      # Regex for field names to mask
    classification: str     # Apply when data is this classification
    mask_type: str          # full, partial, hash, round
    mask_char: str = "*"


DEFAULT_MASKING_RULES = [
    # Mask exact AUM values for CONFIDENTIAL data
    MaskingRule(
        field_pattern=r"^(aum|assets_under_management|total_assets)$",
        classification="CONFIDENTIAL",
        mask_type="round",  # Round to nearest million
    ),
    # Partially mask account numbers
    MaskingRule(
        field_pattern=r"^(account_number|client_id)$",
        classification="RESTRICTED",
        mask_type="partial",  # Show last 4 digits
    ),
]


def apply_masking(
    data: dict,
    classification: str,
    rules: list[MaskingRule] | None = None,
) -> dict:
    """
    Apply masking rules to data before returning to user.
    
    Used in LLM response generation to desensitize values.
    """
    rules = rules or DEFAULT_MASKING_RULES
    result = data.copy()
    
    for key, value in result.items():
        for rule in rules:
            if re.match(rule.field_pattern, key) and classification >= rule.classification:
                result[key] = _mask_value(value, rule)
    
    return result
```

---

## 10. Implementation Plan

### Phase 1: Core Module (MVP)

**Goal**: Basic permission checking with classification levels.

| Task | Component | Priority |
|------|-----------|----------|
| Create `permission/` module structure | Module | P0 |
| Implement `AccessControl`, `UserContext`, `PermissionResult` models | models.py | P0 |
| Implement `PermissionEngine.evaluate()` with full audit logging | engine.py | P0 |
| Add permission config to `config/config.py` | config | P0 |
| Add tests for permission evaluation (allow + deny cases) | tests | P0 |
| Document SafetyGateway vs PermissionEngine boundary | docs | P1 |

### Phase 2: Database Integration

**Goal**: Permission filtering in all storage backends with parameterized queries.

| Task | Component | Priority |
|------|-----------|----------|
| Add `sqlglot` dependency for SQL AST parsing | requirements.txt | P0 |
| Implement `SQLFilter`, `CypherFilter`, `MilvusFilter` dataclasses | filters.py | P0 |
| Implement `sql_filter()` with parameterized output | engine.py | P0 |
| Implement `neo4j_filter()` with parameterized output | engine.py | P0 |
| Implement `milvus_filter()` with post-filter function | engine.py | P0 |
| Add access control columns + `classification_level` to PostgreSQL | schemas.py | P0 |
| Add trigger to sync `classification_level` from `classification` | schemas.py | P0 |
| Update Neo4j node properties with `classification_level` | schemas.py | P0 |
| Update Milvus collection schema | schemas.py | P0 |
| Wrap MCP tools with permission checks using AST parser | tools/*.py | P1 |
| Add expiry_date checks to all filter methods | engine.py | P0 |

### Phase 3: Data Tagging

**Goal**: Automatic permission tagging during data ingestion.

| Task | Component | Priority |
|------|-----------|----------|
| Implement `PolicyStore` | policy.py | P0 |
| Implement `tag_data()` | engine.py | P0 |
| Integrate with DataCollector | collector.py | P0 |
| Update DataDistributor for access control | distributor.py | P0 |
| Add policy configuration file support | policy.py | P1 |

### Phase 4: Audit and Compliance

**Goal**: Full audit trail and compliance features.

| Task | Component | Priority |
|------|-----------|----------|
| Implement `AuditLogger` | audit.py | P0 |
| Add masking rules | masking.py | P1 |
| Database-backed audit storage | audit.py | P2 |
| Compliance reporting endpoints | api/rest.py | P2 |

### Phase 5: Production Auth

**Goal**: JWT-based authentication integration.

| Task | Component | Priority |
|------|-----------|----------|
| JWT token validation | auth.py | P0 |
| Integration with external IdP | auth.py | P1 |
| Role synchronization | auth.py | P2 |

---

## 11. File Structure

```
OpenFund-AI/
├── permission/
│   ├── __init__.py
│   ├── models.py          # AccessControl, UserContext, PermissionResult
│   ├── engine.py          # PermissionEngine
│   ├── policy.py          # PermissionPolicy, PolicyStore
│   ├── filters.py         # Database-specific filter generators
│   ├── audit.py           # AuditLogger, AuditRecord
│   ├── masking.py         # Data masking rules and functions
│   └── auth.py            # JWT validation (Phase 5)
├── config/
│   └── config.py          # Extended with permission settings
│   └── policies.json      # Custom policy definitions (optional)
└── tests/
    └── test_permission.py # Permission module tests
```

---

## 12. Security Considerations

### 12.1 Defense in Depth

| Layer | Component | Responsibility | NOT Responsible For |
|-------|-----------|----------------|---------------------|
| 1 | **API Layer** | Auth token validation, user context extraction | Business logic |
| 2 | **SafetyGateway** | Input validation, guardrails, input PII masking | Authorization decisions |
| 3 | **PermissionEngine** | Authorization check before data access | Input validation |
| 4 | **MCP Tools** | Apply parameterized filters to database queries | Policy evaluation |
| 5 | **OutputRail + Masking** | Output compliance, field-level masking | Data retrieval |

**Component Boundary Clarification**:
- **SafetyGateway** handles _input_ sanitization (what goes in)
- **PermissionEngine** handles _authorization_ (who can access what)
- **OutputRail/Masking** handles _output_ sanitization (what goes out)

### 12.2 SQL Injection Prevention

All database filter methods return parameterized queries. **Never** build SQL by string concatenation.

```python
# WRONG - SQL injection vulnerability
query = f"SELECT * FROM data WHERE tenant_id = '{user.tenant_id}'"

# CORRECT - Parameterized query
filter_result = engine.sql_filter(user)
cursor.execute(f"SELECT * FROM data WHERE {filter_result.clause}", filter_result.params)
```

For complex query modifications, use SQL parsers (e.g., `sqlglot`) instead of string replacement.

### 12.3 Principle of Least Privilege

- Default classification is `PUBLIC` (most restrictive for privileged data)
- Users get minimal clearance (`PUBLIC`) until explicitly elevated
- Roles are additive; no implicit inheritance
- Expired data is inaccessible even with sufficient clearance

### 12.4 Audit Trail

- Log **all** access attempts (both allowed and denied)
- Include conversation context for traceability
- Retain logs per compliance requirements (configurable)
- Denial logs are critical for security monitoring and intrusion detection

### 12.5 Data Isolation

- Tenant ID enforces logical separation
- Cross-tenant access requires explicit `users_allowed` entry
- Region restrictions for data residency compliance
- Expiry dates are enforced at both evaluate() and filter() levels

---

## 13. Testing Strategy

### 13.1 Unit Tests

```python
# tests/test_permission.py

def test_evaluate_public_data():
    """PUBLIC data accessible to anyone."""
    engine = PermissionEngine(PolicyStore(), AuditLogger(mock_config))
    user = UserContext(user_id="u1", tenant_id="t1", roles=[], clearance_level="PUBLIC", attributes={})
    resource = AccessControl(classification="PUBLIC", classification_level=0, ...)
    
    result = engine.evaluate(user, resource)
    assert result.allowed
    assert result.reason == "Public data"


def test_evaluate_classification_denied():
    """User with PUBLIC clearance cannot access CONFIDENTIAL."""
    engine = PermissionEngine(...)
    user = UserContext(clearance_level="PUBLIC", ...)
    resource = AccessControl(classification="CONFIDENTIAL", classification_level=2, ...)
    
    result = engine.evaluate(user, resource)
    assert not result.allowed
    assert "clearance" in result.reason.lower()


def test_evaluate_expired_data_denied():
    """Expired data is not accessible even with sufficient clearance."""
    engine = PermissionEngine(...)
    user = UserContext(clearance_level="RESTRICTED", ...)
    resource = AccessControl(
        classification="PUBLIC",
        classification_level=0,
        expiry_date="2020-01-01T00:00:00Z",  # Past date
        ...
    )
    
    result = engine.evaluate(user, resource)
    assert not result.allowed
    assert "expired" in result.reason.lower()


def test_evaluate_rbac_or_abac():
    """User passes if EITHER role matches OR user is in allowlist."""
    engine = PermissionEngine(...)
    
    # User has no matching role but is in users_allowed
    user = UserContext(user_id="special_user", roles=["viewer"], ...)
    resource = AccessControl(
        roles_allowed=["admin"],
        users_allowed=["special_user"],
        ...
    )
    
    result = engine.evaluate(user, resource)
    assert result.allowed  # Passes via users_allowed


def test_evaluate_all_denials_logged():
    """All denial reasons are logged to audit."""
    mock_logger = Mock()
    engine = PermissionEngine(PolicyStore(), mock_logger)
    user = UserContext(clearance_level="PUBLIC", ...)
    resource = AccessControl(classification="RESTRICTED", classification_level=3, ...)
    
    engine.evaluate(user, resource)
    
    mock_logger.log_access.assert_called_once()
    call_args = mock_logger.log_access.call_args
    assert call_args.kwargs["allowed"] is False


def test_sql_filter_returns_parameterized():
    """SQL filter returns clause + params, not interpolated string."""
    engine = PermissionEngine(...)
    user = UserContext(tenant_id="t1", roles=["analyst"], user_id="u1", clearance_level="INTERNAL", attributes={})
    
    filter_result = engine.sql_filter(user)
    
    assert isinstance(filter_result, SQLFilter)
    assert "%(tenant_id)s" in filter_result.clause  # Placeholder, not value
    assert filter_result.params["tenant_id"] == "t1"
    assert filter_result.params["roles"] == ["analyst"]
    assert "expiry_date" in filter_result.clause  # Expiry check included


def test_neo4j_filter_checks_all_roles():
    """Neo4j filter checks ALL user roles, not just first."""
    engine = PermissionEngine(...)
    user = UserContext(roles=["viewer", "analyst", "admin"], ...)
    
    filter_result = engine.neo4j_filter(user)
    
    assert "ANY(role IN $roles" in filter_result.clause
    assert filter_result.params["roles"] == ["viewer", "analyst", "admin"]
```

### 13.2 Integration Tests

```python
def test_sql_tool_with_permissions():
    """sql_tool.run_query respects user permissions."""
    # Insert test data with different classifications
    # Query with user context
    # Assert only authorized data returned
    # Assert expired data not returned


def test_milvus_post_filter():
    """Milvus results are correctly filtered by post_filter."""
    engine = PermissionEngine(...)
    user = UserContext(roles=["analyst"], user_id="u1", ...)
    filter_result = engine.milvus_filter(user)
    
    # Simulate Milvus results
    results = [
        {"classification": "PUBLIC", "roles_allowed": "[]", "users_allowed": "[]"},
        {"classification": "INTERNAL", "roles_allowed": '["admin"]', "users_allowed": "[]"},  # No match
        {"classification": "INTERNAL", "roles_allowed": '["analyst"]', "users_allowed": "[]"},  # Role match
        {"classification": "INTERNAL", "roles_allowed": "[]", "users_allowed": '["u1"]'},  # User match
    ]
    
    filtered = filter_result.post_filter(results)
    assert len(filtered) == 3  # PUBLIC + analyst role + u1 user


def test_data_collection_tagging():
    """DataCollector tags data with access control including classification_level."""
    collector = DataCollector(permission_engine)
    result = collector.collect_symbol("NVDA", "2024-01-15")
    
    for file in result.files:
        data = json.load(open(file))
        assert "access_control" in data
        ac = data["access_control"]
        assert "classification" in ac
        assert "classification_level" in ac
        assert ac["classification_level"] == CLEARANCE_HIERARCHY[ac["classification"]]
```

---

## 14. Migration Guide

### 14.1 Existing Data

For data already in storage without access control:

1. **Default Tagging**: Run migration script to add default `access_control` (PUBLIC classification)
2. **Selective Tagging**: Apply policies based on source/table/collection
3. **Manual Review**: Flag RESTRICTED data for manual classification

```python
# scripts/migrate_permissions.py

def migrate_postgres_table(table_name: str, default_policy: str):
    """Add access control columns and default values."""
    ddl = f"""
    ALTER TABLE {table_name}
    ADD COLUMN IF NOT EXISTS classification VARCHAR(20) DEFAULT 'PUBLIC',
    ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(50) DEFAULT 'default',
    ADD COLUMN IF NOT EXISTS roles_allowed JSONB DEFAULT '[]',
    ...
    """
    sql_tool.run_query(ddl)
```

### 14.2 Backward Compatibility

- Permission checks are disabled by default (`PERMISSION_ENABLED=false`)
- Existing queries work unchanged when disabled
- Gradual rollout: enable per-environment

---

## Appendix A: Example Access Control Records

### A.1 Public Market Data

```json
{
  "symbol": "NVDA",
  "price": 850.25,
  "timestamp": "2024-01-15T10:30:00Z",
  "access_control": {
    "classification": "PUBLIC",
    "classification_level": 0,
    "tenant_id": "",
    "roles_allowed": [],
    "users_allowed": [],
    "source": "yfinance",
    "region": "US",
    "expiry_date": null,
    "owner": "system",
    "created_at": "2024-01-15T10:30:00Z"
  }
}
```

### A.2 Internal Research Note

```json
{
  "fund_id": "FUND_X",
  "note": "Analyst recommendation: overweight",
  "access_control": {
    "classification": "INTERNAL",
    "classification_level": 1,
    "tenant_id": "research_team",
    "roles_allowed": ["analyst", "researcher"],
    "users_allowed": [],
    "source": "internal_notes",
    "region": "US",
    "expiry_date": "2025-01-15T00:00:00Z",
    "owner": "analyst_001",
    "created_at": "2024-01-15T10:30:00Z"
  }
}
```

### A.3 Client Portfolio (Restricted)

```json
{
  "client_id": "C****789",
  "holdings": ["..."],
  "access_control": {
    "classification": "RESTRICTED",
    "classification_level": 3,
    "tenant_id": "wealth_mgmt",
    "roles_allowed": ["client_manager"],
    "users_allowed": ["user_456", "user_789"],
    "source": "client_data",
    "region": "US",
    "expiry_date": "2024-04-15T00:00:00Z",
    "owner": "user_456",
    "created_at": "2024-01-15T10:30:00Z"
  }
}
```

---

## Appendix B: Query Examples

### B.1 PostgreSQL with Permission Filter (Parameterized)

```python
# Application code
user = UserContext(
    user_id="user_001",
    tenant_id="research_team",
    roles=["analyst", "premium_user"],
    clearance_level="CONFIDENTIAL",
    attributes={},
)

filter_result = engine.sql_filter(user)
# filter_result.params = {
#     "tenant_id": "research_team",
#     "user_id": "user_001",
#     "roles": ["analyst", "premium_user"],
#     "clearance_level": 2,
# }

# Original user query
base_query = "SELECT symbol, price FROM stock_ohlcv WHERE date > %(date)s"
params = {"date": "2024-01-01"}

# Inject filter (using sqlglot AST or subquery approach)
final_query = f"""
SELECT symbol, price FROM stock_ohlcv 
WHERE 
    (
        (classification = 'PUBLIC')
        OR (
            tenant_id = %(tenant_id)s
            AND classification_level <= %(clearance_level)s
            AND (expiry_date IS NULL OR expiry_date > NOW())
            AND (
                roles_allowed IS NULL
                OR cardinality(roles_allowed) = 0
                OR roles_allowed ?| %(roles)s
                OR users_allowed ? %(user_id)s
            )
        )
    )
    AND date > %(date)s
"""
params.update(filter_result.params)
cursor.execute(final_query, params)
```

### B.2 Neo4j with Permission Filter (Parameterized)

```python
# Application code
filter_result = engine.neo4j_filter(user)

# Original query
base_query = """
MATCH (f:Fund)-[:MANAGED_BY]->(m:Manager)
RETURN f.symbol, m.name
"""

# With permission filter (applied to both nodes)
final_query = """
MATCH (f:Fund)-[:MANAGED_BY]->(m:Manager)
WHERE 
    (
        f.classification = 'PUBLIC'
        OR (
            f.tenant_id = $tenant_id
            AND f.classification_level <= $clearance_level
            AND (f.expiry_date IS NULL OR f.expiry_date > datetime())
            AND (
                f.roles_allowed IS NULL
                OR size(f.roles_allowed) = 0
                OR ANY(role IN $roles WHERE role IN f.roles_allowed)
                OR $user_id IN f.users_allowed
            )
        )
    )
    AND
    (
        m.classification = 'PUBLIC'
        OR (
            m.tenant_id = $tenant_id
            AND m.classification_level <= $clearance_level
            AND (m.expiry_date IS NULL OR m.expiry_date > datetime())
            AND (
                m.roles_allowed IS NULL
                OR size(m.roles_allowed) = 0
                OR ANY(role IN $roles WHERE role IN m.roles_allowed)
                OR $user_id IN m.users_allowed
            )
        )
    )
RETURN f.symbol, m.name
"""
session.run(final_query, filter_result.params)
```

### B.3 Milvus with Permission Filter (Pre + Post)

```python
# Application code
filter_result = engine.milvus_filter(user)

# Original search
results = collection.search(
    data=[query_vector],
    anns_field="embedding",
    limit=20,  # Fetch extra to account for post-filter removal
    # Pre-filter: classification and tenant (efficient in Milvus)
    expr=filter_result.expr,
    output_fields=["classification", "classification_level", "tenant_id", 
                   "roles_allowed", "users_allowed", "content"],
)

# Post-filter: RBAC/ABAC check in Python
if filter_result.post_filter:
    # Convert results to dicts for filtering
    hits = [{"id": hit.id, **hit.entity} for hit in results[0]]
    filtered_hits = filter_result.post_filter(hits)
    # Return top 10 after filtering
    final_results = filtered_hits[:10]
```
