"""Static CSV->graph schema maps for graph tool CSV build."""

DATASET_FILES: dict[str, str] = {
    "funds": "funds.csv",
    "equities": "equities.csv",
    "etfs": "etfs.csv",
    "indices": "indices.csv",
    "currencies": "currencies.csv",
    "cryptos": "cryptos.csv",
    "moneymarkets": "moneymarkets.csv",
}

CATEGORY_FIELDS: dict[str, list[str]] = {
    "funds": ["currency", "category_group", "category", "family", "exchange"],
    "equities": [
        "currency",
        "sector",
        "industry_group",
        "industry",
        "exchange",
        "market",
        "country",
        "state",
        "market_cap",
    ],
    "etfs": ["currency", "category_group", "category", "family", "exchange"],
    "indices": ["currency", "category_group", "category", "exchange"],
    "currencies": ["base_currency", "quote_currency", "exchange"],
    "cryptos": ["cryptocurrency", "currency", "exchange"],
    "moneymarkets": ["currency", "family", "exchange"],
}

DIMENSION_REL: dict[str, tuple[str, str]] = {
    "currency": ("Currency", "DENOMINATED_IN"),
    "category_group": ("CategoryGroup", "IN_CATEGORY_GROUP"),
    "category": ("Category", "IN_CATEGORY"),
    "family": ("Family", "IN_FAMILY"),
    "exchange": ("Exchange", "LISTED_ON"),
    "sector": ("Sector", "IN_SECTOR"),
    "industry_group": ("IndustryGroup", "IN_INDUSTRY_GROUP"),
    "industry": ("Industry", "IN_INDUSTRY"),
    "market": ("Market", "IN_MARKET"),
    "country": ("Country", "IN_COUNTRY"),
    "state": ("State", "IN_STATE"),
    "market_cap": ("MarketCapClass", "IN_MARKET_CAP_CLASS"),
    "base_currency": ("BaseCurrency", "HAS_BASE_CURRENCY"),
    "quote_currency": ("QuoteCurrency", "HAS_QUOTE_CURRENCY"),
    "cryptocurrency": ("CryptoTicker", "TRACKS_CRYPTO"),
}

