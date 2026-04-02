"""Database schema definitions for DataManagerAgent.

Contains SQL DDL for PostgreSQL tables, Cypher patterns for Neo4j, and Milvus collection schema.
"""

from __future__ import annotations

# PostgreSQL DDL bootstrap used by DataDistributor._ensure_postgres_schema().
POSTGRES_DDL = """
-- Stock quotes table (OHLCV data)
CREATE TABLE IF NOT EXISTS stock_ohlcv (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    trade_date DATE NOT NULL,
    open DECIMAL(18, 4),
    high DECIMAL(18, 4),
    low DECIMAL(18, 4),
    close DECIMAL(18, 4),
    volume BIGINT,
    collected_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (symbol, trade_date)
);

-- Company fundamentals table
CREATE TABLE IF NOT EXISTS company_fundamentals (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    as_of_date DATE NOT NULL,
    name VARCHAR(256),
    sector VARCHAR(128),
    industry VARCHAR(128),
    market_cap BIGINT,
    pe_ratio DECIMAL(10, 4),
    forward_pe DECIMAL(10, 4),
    peg_ratio DECIMAL(10, 4),
    price_to_book DECIMAL(10, 4),
    eps_ttm DECIMAL(10, 4),
    dividend_yield DECIMAL(10, 6),
    beta DECIMAL(10, 4),
    fifty_two_week_high DECIMAL(18, 4),
    fifty_two_week_low DECIMAL(18, 4),
    collected_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (symbol, as_of_date)
);

-- Financial statements table (balance sheet, cashflow, income - EAV format)
CREATE TABLE IF NOT EXISTS financial_statements (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    statement_type VARCHAR(32) NOT NULL,
    report_date DATE NOT NULL,
    fiscal_period VARCHAR(16),
    line_item VARCHAR(128) NOT NULL,
    value DECIMAL(24, 4),
    collected_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (symbol, statement_type, report_date, line_item)
);

-- Insider transactions table
CREATE TABLE IF NOT EXISTS insider_transactions (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    insider_name VARCHAR(256),
    relation VARCHAR(128),
    transaction_type VARCHAR(64),
    shares BIGINT,
    value DECIMAL(18, 4),
    transaction_date DATE,
    collected_at TIMESTAMP DEFAULT NOW()
);

-- Technical indicators table (EAV format)
CREATE TABLE IF NOT EXISTS technical_indicators (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    indicator_name VARCHAR(64) NOT NULL,
    indicator_date DATE NOT NULL,
    value DECIMAL(18, 6),
    collected_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (symbol, indicator_name, indicator_date)
);

-- Fund info table
CREATE TABLE IF NOT EXISTS fund_info (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    name VARCHAR(256),
    category VARCHAR(128),
    index_tracked VARCHAR(128),
    investment_style VARCHAR(64),
    total_assets_billion DECIMAL(12, 2),
    expense_ratio DECIMAL(8, 6),
    dividend_yield DECIMAL(8, 6),
    holdings_count INTEGER,
    as_of_date DATE NOT NULL,
    collected_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (symbol, as_of_date)
);

-- Fund performance table
CREATE TABLE IF NOT EXISTS fund_performance (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    as_of_date DATE NOT NULL,
    ytd_return DECIMAL(10, 6),
    return_1yr DECIMAL(10, 6),
    return_3yr DECIMAL(10, 6),
    return_5yr DECIMAL(10, 6),
    return_10yr DECIMAL(10, 6),
    collected_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (symbol, as_of_date)
);

-- Fund risk metrics table
CREATE TABLE IF NOT EXISTS fund_risk_metrics (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    as_of_date DATE NOT NULL,
    beta DECIMAL(8, 4),
    standard_deviation DECIMAL(8, 6),
    sharpe_ratio DECIMAL(8, 4),
    max_drawdown DECIMAL(8, 6),
    collected_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (symbol, as_of_date)
);

-- Fund holdings table
CREATE TABLE IF NOT EXISTS fund_holdings (
    id SERIAL PRIMARY KEY,
    fund_symbol VARCHAR(32) NOT NULL,
    holding_symbol VARCHAR(32) NOT NULL,
    holding_name VARCHAR(256),
    weight DECIMAL(8, 6),
    sector VARCHAR(128),
    as_of_date DATE NOT NULL,
    collected_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (fund_symbol, holding_symbol, as_of_date)
);

-- Fund sector allocation table
CREATE TABLE IF NOT EXISTS fund_sector_allocation (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    sector VARCHAR(128) NOT NULL,
    weight DECIMAL(8, 6),
    as_of_date DATE NOT NULL,
    collected_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (symbol, sector, as_of_date)
);

-- Fund flows table
CREATE TABLE IF NOT EXISTS fund_flows (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    period VARCHAR(32) NOT NULL,
    inflow_billion DECIMAL(12, 4),
    outflow_billion DECIMAL(12, 4),
    net_flow_billion DECIMAL(12, 4),
    pct_of_aum DECIMAL(8, 6),
    as_of_date DATE NOT NULL,
    collected_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (symbol, period, as_of_date)
);

-- CN fund basic metadata table (offline ingestion domain)
CREATE TABLE IF NOT EXISTS cn_fund_basic (
    id SERIAL PRIMARY KEY,
    fund_id VARCHAR(16) NOT NULL,
    fund_name VARCHAR(256),
    fund_type VARCHAR(64),
    risk_level VARCHAR(32),
    inception_date DATE,
    fund_manager VARCHAR(256),
    management_company VARCHAR(256),
    tracking_index VARCHAR(256),
    investment_scope TEXT,
    latest_scale DECIMAL(18, 6),
    description TEXT,
    as_of_date DATE NOT NULL,
    collected_at TIMESTAMP DEFAULT NOW(),
    source VARCHAR(64),
    UNIQUE (fund_id, as_of_date)
);

-- CN fund NAV time series (one record per fund_id + nav_date)
CREATE TABLE IF NOT EXISTS cn_fund_nav (
    id SERIAL PRIMARY KEY,
    fund_id VARCHAR(16) NOT NULL,
    nav_date DATE NOT NULL,
    nav DECIMAL(18, 8),
    nav_accumulated DECIMAL(18, 8),
    collected_at TIMESTAMP DEFAULT NOW(),
    source VARCHAR(64),
    UNIQUE (fund_id, nav_date)
);

-- CN fund report sections extracted from PDFs
CREATE TABLE IF NOT EXISTS cn_fund_report_sections (
    id SERIAL PRIMARY KEY,
    fund_id VARCHAR(16) NOT NULL,
    report_id VARCHAR(64) NOT NULL,
    section_id VARCHAR(64) NOT NULL,
    section_title_raw TEXT,
    section_text TEXT,
    section_summary TEXT,
    report_type VARCHAR(32),
    report_date VARCHAR(32),
    collected_at TIMESTAMP DEFAULT NOW(),
    extractor_version VARCHAR(32),
    parser_name VARCHAR(32),
    parser_version VARCHAR(32),
    UNIQUE (fund_id, report_id, section_id)
);

-- CN fund report signals extracted from PDFs (one row per report)
CREATE TABLE IF NOT EXISTS cn_fund_report_signals (
    id SERIAL PRIMARY KEY,
    fund_id VARCHAR(16) NOT NULL,
    report_id VARCHAR(64) NOT NULL,
    strategy TEXT,
    risk TEXT,
    market_view TEXT,
    style VARCHAR(64),
    sector_preference_json TEXT,
    report_type VARCHAR(32),
    report_date VARCHAR(32),
    collected_at TIMESTAMP DEFAULT NOW(),
    extractor_version VARCHAR(32),
    parser_name VARCHAR(32),
    parser_version VARCHAR(32),
    UNIQUE (fund_id, report_id)
);
"""

# Parameterized UPSERT SQL templates keyed by logical table name.
POSTGRES_UPSERT_TEMPLATES = {
    "stock_ohlcv": """
        INSERT INTO stock_ohlcv (symbol, trade_date, open, high, low, close, volume, collected_at)
        VALUES (%(symbol)s, %(trade_date)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(collected_at)s)
        ON CONFLICT (symbol, trade_date) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            collected_at = EXCLUDED.collected_at
    """,
    "company_fundamentals": """
        INSERT INTO company_fundamentals (
            symbol, as_of_date, name, sector, industry, market_cap,
            pe_ratio, forward_pe, peg_ratio, price_to_book, eps_ttm,
            dividend_yield, beta, fifty_two_week_high, fifty_two_week_low, collected_at
        ) VALUES (
            %(symbol)s, %(as_of_date)s, %(name)s, %(sector)s, %(industry)s, %(market_cap)s,
            %(pe_ratio)s, %(forward_pe)s, %(peg_ratio)s, %(price_to_book)s, %(eps_ttm)s,
            %(dividend_yield)s, %(beta)s, %(fifty_two_week_high)s, %(fifty_two_week_low)s, %(collected_at)s
        )
        ON CONFLICT (symbol, as_of_date) DO UPDATE SET
            name = EXCLUDED.name, sector = EXCLUDED.sector, industry = EXCLUDED.industry,
            market_cap = EXCLUDED.market_cap, pe_ratio = EXCLUDED.pe_ratio,
            forward_pe = EXCLUDED.forward_pe, peg_ratio = EXCLUDED.peg_ratio,
            price_to_book = EXCLUDED.price_to_book, eps_ttm = EXCLUDED.eps_ttm,
            dividend_yield = EXCLUDED.dividend_yield, beta = EXCLUDED.beta,
            fifty_two_week_high = EXCLUDED.fifty_two_week_high,
            fifty_two_week_low = EXCLUDED.fifty_two_week_low,
            collected_at = EXCLUDED.collected_at
    """,
    "financial_statements": """
        INSERT INTO financial_statements (symbol, statement_type, report_date, fiscal_period, line_item, value, collected_at)
        VALUES (%(symbol)s, %(statement_type)s, %(report_date)s, %(fiscal_period)s, %(line_item)s, %(value)s, %(collected_at)s)
        ON CONFLICT (symbol, statement_type, report_date, line_item) DO UPDATE SET
            fiscal_period = EXCLUDED.fiscal_period,
            value = EXCLUDED.value,
            collected_at = EXCLUDED.collected_at
    """,
    "insider_transactions": """
        INSERT INTO insider_transactions (symbol, insider_name, relation, transaction_type, shares, value, transaction_date, collected_at)
        VALUES (%(symbol)s, %(insider_name)s, %(relation)s, %(transaction_type)s, %(shares)s, %(value)s, %(transaction_date)s, %(collected_at)s)
    """,
    "technical_indicators": """
        INSERT INTO technical_indicators (symbol, indicator_name, indicator_date, value, collected_at)
        VALUES (%(symbol)s, %(indicator_name)s, %(indicator_date)s, %(value)s, %(collected_at)s)
        ON CONFLICT (symbol, indicator_name, indicator_date) DO UPDATE SET
            value = EXCLUDED.value,
            collected_at = EXCLUDED.collected_at
    """,
    "fund_info": """
        INSERT INTO fund_info (symbol, name, category, index_tracked, investment_style, total_assets_billion, expense_ratio, dividend_yield, holdings_count, as_of_date, collected_at)
        VALUES (%(symbol)s, %(name)s, %(category)s, %(index_tracked)s, %(investment_style)s, %(total_assets_billion)s, %(expense_ratio)s, %(dividend_yield)s, %(holdings_count)s, %(as_of_date)s, %(collected_at)s)
        ON CONFLICT (symbol, as_of_date) DO UPDATE SET
            name = EXCLUDED.name, category = EXCLUDED.category, index_tracked = EXCLUDED.index_tracked,
            investment_style = EXCLUDED.investment_style, total_assets_billion = EXCLUDED.total_assets_billion,
            expense_ratio = EXCLUDED.expense_ratio, dividend_yield = EXCLUDED.dividend_yield,
            holdings_count = EXCLUDED.holdings_count, collected_at = EXCLUDED.collected_at
    """,
    "fund_performance": """
        INSERT INTO fund_performance (symbol, as_of_date, ytd_return, return_1yr, return_3yr, return_5yr, return_10yr, collected_at)
        VALUES (%(symbol)s, %(as_of_date)s, %(ytd_return)s, %(return_1yr)s, %(return_3yr)s, %(return_5yr)s, %(return_10yr)s, %(collected_at)s)
        ON CONFLICT (symbol, as_of_date) DO UPDATE SET
            ytd_return = EXCLUDED.ytd_return, return_1yr = EXCLUDED.return_1yr, return_3yr = EXCLUDED.return_3yr,
            return_5yr = EXCLUDED.return_5yr, return_10yr = EXCLUDED.return_10yr, collected_at = EXCLUDED.collected_at
    """,
    "fund_risk_metrics": """
        INSERT INTO fund_risk_metrics (symbol, as_of_date, beta, standard_deviation, sharpe_ratio, max_drawdown, collected_at)
        VALUES (%(symbol)s, %(as_of_date)s, %(beta)s, %(standard_deviation)s, %(sharpe_ratio)s, %(max_drawdown)s, %(collected_at)s)
        ON CONFLICT (symbol, as_of_date) DO UPDATE SET
            beta = EXCLUDED.beta, standard_deviation = EXCLUDED.standard_deviation,
            sharpe_ratio = EXCLUDED.sharpe_ratio, max_drawdown = EXCLUDED.max_drawdown, collected_at = EXCLUDED.collected_at
    """,
    "fund_holdings": """
        INSERT INTO fund_holdings (fund_symbol, holding_symbol, holding_name, weight, sector, as_of_date, collected_at)
        VALUES (%(fund_symbol)s, %(holding_symbol)s, %(holding_name)s, %(weight)s, %(sector)s, %(as_of_date)s, %(collected_at)s)
        ON CONFLICT (fund_symbol, holding_symbol, as_of_date) DO UPDATE SET
            holding_name = EXCLUDED.holding_name, weight = EXCLUDED.weight, sector = EXCLUDED.sector, collected_at = EXCLUDED.collected_at
    """,
    "fund_sector_allocation": """
        INSERT INTO fund_sector_allocation (symbol, sector, weight, as_of_date, collected_at)
        VALUES (%(symbol)s, %(sector)s, %(weight)s, %(as_of_date)s, %(collected_at)s)
        ON CONFLICT (symbol, sector, as_of_date) DO UPDATE SET
            weight = EXCLUDED.weight, collected_at = EXCLUDED.collected_at
    """,
    "fund_flows": """
        INSERT INTO fund_flows (symbol, period, inflow_billion, outflow_billion, net_flow_billion, pct_of_aum, as_of_date, collected_at)
        VALUES (%(symbol)s, %(period)s, %(inflow_billion)s, %(outflow_billion)s, %(net_flow_billion)s, %(pct_of_aum)s, %(as_of_date)s, %(collected_at)s)
        ON CONFLICT (symbol, period, as_of_date) DO UPDATE SET
            inflow_billion = EXCLUDED.inflow_billion, outflow_billion = EXCLUDED.outflow_billion,
            net_flow_billion = EXCLUDED.net_flow_billion, pct_of_aum = EXCLUDED.pct_of_aum, collected_at = EXCLUDED.collected_at
    """,
    "cn_fund_basic": """
        INSERT INTO cn_fund_basic (
            fund_id, fund_name, fund_type, risk_level, inception_date,
            fund_manager, management_company, tracking_index, investment_scope,
            latest_scale, description, as_of_date, collected_at, source
        ) VALUES (
            %(fund_id)s, %(fund_name)s, %(fund_type)s, %(risk_level)s, %(inception_date)s,
            %(fund_manager)s, %(management_company)s, %(tracking_index)s, %(investment_scope)s,
            %(latest_scale)s, %(description)s, %(as_of_date)s, %(collected_at)s, %(source)s
        )
        ON CONFLICT (fund_id, as_of_date) DO UPDATE SET
            fund_name = EXCLUDED.fund_name,
            fund_type = EXCLUDED.fund_type,
            risk_level = EXCLUDED.risk_level,
            inception_date = EXCLUDED.inception_date,
            fund_manager = EXCLUDED.fund_manager,
            management_company = EXCLUDED.management_company,
            tracking_index = EXCLUDED.tracking_index,
            investment_scope = EXCLUDED.investment_scope,
            latest_scale = EXCLUDED.latest_scale,
            description = EXCLUDED.description,
            collected_at = EXCLUDED.collected_at,
            source = EXCLUDED.source
    """,
    "cn_fund_nav": """
        INSERT INTO cn_fund_nav (
            fund_id, nav_date, nav, nav_accumulated, collected_at, source
        ) VALUES (
            %(fund_id)s, %(nav_date)s, %(nav)s, %(nav_accumulated)s, %(collected_at)s, %(source)s
        )
        ON CONFLICT (fund_id, nav_date) DO UPDATE SET
            nav = EXCLUDED.nav,
            nav_accumulated = EXCLUDED.nav_accumulated,
            collected_at = EXCLUDED.collected_at,
            source = EXCLUDED.source
    """,
    "cn_fund_report_sections": """
        INSERT INTO cn_fund_report_sections (
            fund_id, report_id, section_id, section_title_raw, section_text, section_summary,
            report_type, report_date, collected_at, extractor_version, parser_name, parser_version
        ) VALUES (
            %(fund_id)s, %(report_id)s, %(section_id)s, %(section_title_raw)s, %(section_text)s, %(section_summary)s,
            %(report_type)s, %(report_date)s, %(collected_at)s, %(extractor_version)s, %(parser_name)s, %(parser_version)s
        )
        ON CONFLICT (fund_id, report_id, section_id) DO UPDATE SET
            section_title_raw = EXCLUDED.section_title_raw,
            section_text = EXCLUDED.section_text,
            section_summary = EXCLUDED.section_summary,
            report_type = EXCLUDED.report_type,
            report_date = EXCLUDED.report_date,
            collected_at = EXCLUDED.collected_at,
            extractor_version = EXCLUDED.extractor_version,
            parser_name = EXCLUDED.parser_name,
            parser_version = EXCLUDED.parser_version
    """,
    "cn_fund_report_signals": """
        INSERT INTO cn_fund_report_signals (
            fund_id, report_id, strategy, risk, market_view, style, sector_preference_json,
            report_type, report_date, collected_at, extractor_version, parser_name, parser_version
        ) VALUES (
            %(fund_id)s, %(report_id)s, %(strategy)s, %(risk)s, %(market_view)s, %(style)s, %(sector_preference_json)s,
            %(report_type)s, %(report_date)s, %(collected_at)s, %(extractor_version)s, %(parser_name)s, %(parser_version)s
        )
        ON CONFLICT (fund_id, report_id) DO UPDATE SET
            strategy = EXCLUDED.strategy,
            risk = EXCLUDED.risk,
            market_view = EXCLUDED.market_view,
            style = EXCLUDED.style,
            sector_preference_json = EXCLUDED.sector_preference_json,
            report_type = EXCLUDED.report_type,
            report_date = EXCLUDED.report_date,
            collected_at = EXCLUDED.collected_at,
            extractor_version = EXCLUDED.extractor_version,
            parser_name = EXCLUDED.parser_name,
            parser_version = EXCLUDED.parser_version
    """,
}

# Neo4j Cypher templates for node upsert and relationship linking.
NEO4J_CYPHER_TEMPLATES = {
    "merge_company": """
        MERGE (c:Company {symbol: $symbol})
        SET c.name = $name,
            c.market_cap = $market_cap,
            c.exchange = $exchange,
            c.currency = $currency,
            c.country = $country,
            c.city = $city,
            c.employees = $employees,
            c.website = $website,
            c.collected_at = $collected_at
        RETURN c
    """,
    "merge_sector": """
        MERGE (s:Sector {name: $name})
        RETURN s
    """,
    "merge_industry": """
        MERGE (i:Industry {name: $name})
        RETURN i
    """,
    "merge_officer": """
        MERGE (o:Officer {name: $name})
        SET o.age = $age
        RETURN o
    """,
    "link_company_sector": """
        MATCH (c:Company {symbol: $symbol})
        MATCH (s:Sector {name: $sector_name})
        MERGE (c)-[:IN_SECTOR]->(s)
    """,
    "link_company_industry": """
        MATCH (c:Company {symbol: $symbol})
        MATCH (i:Industry {name: $industry_name})
        MERGE (c)-[:IN_INDUSTRY]->(i)
    """,
    "link_company_officer": """
        MATCH (c:Company {symbol: $symbol})
        MATCH (o:Officer {name: $officer_name})
        MERGE (c)-[r:HAS_OFFICER]->(o)
        SET r.title = $title, r.total_pay = $total_pay
    """,
    "merge_fund": """
        MERGE (f:Fund {symbol: $symbol})
        SET f.name = $name,
            f.category = $category,
            f.index_tracked = $index_tracked,
            f.investment_style = $investment_style,
            f.total_assets_billion = $total_assets_billion,
            f.expense_ratio = $expense_ratio,
            f.collected_at = $collected_at
        RETURN f
    """,
    "link_fund_sector": """
        MATCH (f:Fund {symbol: $symbol})
        MERGE (s:Sector {name: $sector_name})
        MERGE (f)-[r:INVESTS_IN_SECTOR]->(s)
        SET r.weight = $weight
    """,
    "link_fund_holding": """
        MATCH (f:Fund {symbol: $fund_symbol})
        MERGE (c:Company {symbol: $holding_symbol})
        ON CREATE SET c.name = $holding_name
        MERGE (f)-[r:HOLDS]->(c)
        SET r.weight = $weight, r.as_of_date = $as_of_date
    """,
}

MILVUS_COLLECTION_CONFIG = {
    "name": "fund_documents",
    "dimension": 384,
    "primary_key_field": "id",
    "scalar_fields": [
        {"name": "symbol", "dtype": "VARCHAR", "max_length": 32},
        {"name": "doc_type", "dtype": "VARCHAR", "max_length": 32},
        {"name": "source", "dtype": "VARCHAR", "max_length": 256},
        {"name": "published_at", "dtype": "VARCHAR", "max_length": 32},
        {"name": "collected_at", "dtype": "VARCHAR", "max_length": 32},
    ],
    "index_params": {
        "metric_type": "COSINE",
        "index_type": "IVF_FLAT",
        "params": {"nlist": 128},
    },
}
