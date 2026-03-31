This file lists the intended output for converting CSVs under `database/graph_data/` to Neo4j imports.

Source tables: `funds.csv`, `equities.csv`, `etfs.csv`, `indices.csv`, `currencies.csv`, `cryptos.csv`, `moneymarkets.csv`.

---
# funds.csv

header:
symbol,name,currency,summary,category_group,category,family,exchange

data:
0GKA.SG,Börslich handelbare Krügerrand,EUR,The exchange-traded Krugerrand (1oz) Gold Bond is a financial product that allows investors to invest in physical Krugerrand gold coins while benefiting from the advantages of a traded security.,Commodities,Commodities Broad Basket,,STU

intended conversion:
- create nodes for categorical variables (variable name, sample value):
    currency “EUR”,
    category_group “Commodities”,
    category “Commodities Broad Basket”,
    exchange “STU”
    (family empty on this row — skip or omit a link when absent)

- create nodes for entities that are not summaries or numeric values:
    name “Börslich handelbare Krügerrand”,
    symbol “0GKA.SG”

- append the summary as a property of the symbol:
    append the following summary:
    “The exchange-traded Krugerrand (1oz) Gold Bond is a financial product that allows investors to invest in physical Krugerrand gold coins while benefiting from the advantages of a traded security.”
    as a property of:
    “0GKA.SG”

- link relationships between nodes:
    The symbol “0GKA.SG” BELONGS_TO the dataset “funds” (implicit scope for this file)
    The symbol “0GKA.SG” IS_DENOMINATED_IN the currency “EUR”
    The symbol “0GKA.SG” IS_IN_CATEGORY_GROUP “Commodities”
    The symbol “0GKA.SG” IS_IN_CATEGORY “Commodities Broad Basket”
    The symbol “0GKA.SG” IS_LISTED_ON the exchange “STU”

---

# equities.csv

header:
symbol,name,summary,currency,sector,industry_group,industry,exchange,market,country,state,city,zipcode,website,market_cap,isin,cusip,figi,composite_figi,shareclass_figi

data:
000002.SZ,"China Vanke Co., Ltd.","China Vanke Co., Ltd., together with its subsidiaries, engages in the development and sale of properties in the Mainland China, Hong Kong, and internationally. […]",CNY,Real Estate,Real Estate,Real Estate Management & Development,SHZ,Shenzhen Stock Exchange,China,,Shenzhen,518083,http://www.vanke.com,Large Cap,CNE100001SR9,,,,

intended conversion:
- create nodes for categorical variables (variable name, sample value):
    currency “CNY”,
    sector “Real Estate”,
    industry_group “Real Estate”,
    industry “Real Estate Management & Development”,
    exchange “SHZ”,
    market “Shenzhen Stock Exchange”,
    country “China”,
    state “” (empty — skip link when absent),
    market_cap “Large Cap”

- create nodes for entities that are not summaries or numeric values:
    name “China Vanke Co., Ltd.”,
    symbol “000002.SZ”

- append the summary as a property of the symbol:
    append the full narrative summary text
    as a property of:
    “000002.SZ”

- link relationships between nodes:
    The symbol “000002.SZ” BELONGS_TO the dataset “equities”
    The symbol “000002.SZ” IS_DENOMINATED_IN the currency “CNY”
    The symbol “000002.SZ” IS_IN_SECTOR “Real Estate”
    The symbol “000002.SZ” IS_IN_INDUSTRY_GROUP “Real Estate”
    The symbol “000002.SZ” IS_IN_INDUSTRY “Real Estate Management & Development”
    The symbol “000002.SZ” IS_LISTED_ON the exchange “SHZ”
    The symbol “000002.SZ” IS_IN_MARKET “Shenzhen Stock Exchange”
    The symbol “000002.SZ” IS_IN_COUNTRY “China”
    The symbol “000002.SZ” IS_IN_MARKET_CAP_CLASS “Large Cap”

---

# etfs.csv

header:
symbol,name,currency,summary,category_group,category,family,exchange,isin

data:
^ACWI,ISHARES TRUST,USD,"The iShares MSCI ACWI ETF seeks to track the investment results of an index composed of large- and mid-capitalization developed and emerging market equities. […]",Financials,Developed Markets,BlackRock Asset Management,NIM,

intended conversion:
- create nodes for categorical variables (variable name, sample value):
    currency “USD”,
    category_group “Financials”,
    category “Developed Markets”,
    family “BlackRock Asset Management”,
    exchange “NIM”

- create nodes for entities that are not summaries or numeric values:
    name “ISHARES TRUST”,
    symbol “^ACWI”

- append the summary as a property of the symbol:
    append the following summary (full text from the row)
    as a property of:
    “^ACWI”

- link relationships between nodes:
    The symbol “^ACWI” BELONGS_TO the dataset “etfs”
    The symbol “^ACWI” IS_DENOMINATED_IN the currency “USD”
    The symbol “^ACWI” IS_IN_CATEGORY_GROUP “Financials”
    The symbol “^ACWI” IS_IN_CATEGORY “Developed Markets”
    The symbol “^ACWI” IS_IN_FAMILY “BlackRock Asset Management”
    The symbol “^ACWI” IS_LISTED_ON the exchange “NIM”

---

# indices.csv

header:
symbol,name,currency,summary,category_group,category,exchange

data:
000008.SS,SSE Conglomerates Index,CNY,"The SSE Conglomerates Index aims to reflect the overall performance of companies listed on the Shanghai Stock Exchange (SSE) that operate across multiple industries or sectors. […]",Equities,Equities,SHH

intended conversion:
- create nodes for categorical variables (variable name, sample value):
    currency “CNY”,
    category_group “Equities”,
    category “Equities”,
    exchange “SHH”

- create nodes for entities that are not summaries or numeric values:
    name “SSE Conglomerates Index”,
    symbol “000008.SS”

- append the summary as a property of the symbol:
    append the full narrative summary text
    as a property of:
    “000008.SS”

- link relationships between nodes:
    The symbol “000008.SS” BELONGS_TO the dataset “indices”
    The symbol “000008.SS” IS_DENOMINATED_IN the currency “CNY”
    The symbol “000008.SS” IS_IN_CATEGORY_GROUP “Equities”
    The symbol “000008.SS” IS_IN_CATEGORY “Equities”
    The symbol “000008.SS” IS_LISTED_ON the exchange “SHH”

---

# currencies.csv

header:
symbol,name,base_currency,quote_currency,summary,exchange

data:
AED=X,USD/AED,USD,AED,The exchange rate between the United States Dollar (USD) and the United Arab Emirates Dirham (AED). It reflects how many AED can be purchased with one USD.,CCY

intended conversion:
- create nodes for categorical variables (variable name, sample value):
    exchange “CCY”

- create nodes for entities that are not summaries or numeric values:
    name “USD/AED”,
    symbol “AED=X”,
    base_currency “USD”,
    quote_currency “AED”

- append the summary as a property of the symbol:
    append the following summary:
    “The exchange rate between the United States Dollar (USD) and the United Arab Emirates Dirham (AED). It reflects how many AED can be purchased with one USD.”
    as a property of:
    “AED=X”

- link relationships between nodes:
    The symbol “AED=X” BELONGS_TO the dataset “currencies”
    The symbol “AED=X” HAS_BASE_CURRENCY the currency node “USD”
    The symbol “AED=X” HAS_QUOTE_CURRENCY the currency node “AED”
    The symbol “AED=X” IS_LISTED_ON the exchange “CCY”

---

# cryptos.csv

header:
symbol,name,cryptocurrency,currency,summary,exchange

data:
AAVE-CAD,Aave CAD,AAVE,CAD,"Aave (AAVE) is a cryptocurrency and operates on the Ethereum platform. Aave has a current supply of 16,000,000 with 12,488,045.98548802 in circulation. The last known price of Aave is 472.51174201 USD and is down -7.08 over the last 24 hours. It is currently trading on 194 active market(s) with $808,255,779.93 traded over the last 24 hours. More information can be found at https://aave.com/.",CCC

intended conversion:
- create nodes for categorical variables (variable name, sample value):
    currency “CAD”,
    exchange “CCC”

- create nodes for entities that are not summaries or numeric values:
    name “Aave CAD”,
    symbol “AAVE-CAD”,
    cryptocurrency “AAVE”

- append the summary as a property of the symbol:
    append the following summary:
    “Aave (AAVE) is a cryptocurrency and operates on the Ethereum platform. Aave has a current supply of 16,000,000 with 12,488,045.98548802 in circulation. The last known price of Aave is 472.51174201 USD and is down -7.08 over the last 24 hours. It is currently trading on 194 active market(s) with $808,255,779.93 traded over the last 24 hours. More information can be found at https://aave.com/.”
    as a property of:
    “AAVE-CAD”

- link relationships between nodes:
    The symbol “AAVE-CAD” REPRESENTS the cryptocurrency “AAVE”
    The symbol “AAVE-CAD” IS_QUOTED_IN the currency “CAD”
    The symbol “AAVE-CAD” IS_TRADED_ON the exchange “CCC”

---

# moneymarkets.csv

header:
symbol,name,currency,summary,family,exchange

data:
AABXX,SEI Daily Income Trust Government Fund,USD,"SEI Daily Income Trust Government Fund is a money market fund that invests primarily in U.S. government securities. The fund seeks to provide current income consistent with the preservation of capital and liquidity, focusing on securities issued or guaranteed by the U.S. government or its agencies. The fund is managed by SEI Investments Management Corporation and aims to maintain a stable net asset value.",,NAS

intended conversion:
- create nodes for categorical variables (variable name, sample value):
    currency “USD”,
    exchange “NAS”
    (family empty on this row — skip or omit a link when absent)

- create nodes for entities that are not summaries or numeric values:
    name “SEI Daily Income Trust Government Fund”,
    symbol “AABXX”

- append the summary as a property of the symbol:
    append the following summary (full text from the row)
    as a property of:
    “AABXX”

- link relationships between nodes:
    The symbol “AABXX” BELONGS_TO the dataset “moneymarkets”
    The symbol “AABXX” IS_DENOMINATED_IN the currency “USD”
    The symbol “AABXX” IS_LISTED_ON the exchange “NAS”
