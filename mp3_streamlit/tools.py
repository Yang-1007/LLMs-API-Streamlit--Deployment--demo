from config import ACTIVE_MODEL
import os
import sqlite3
import json
import time
import textwrap
import requests
import pandas as pd
import yfinance as yf
from config import ALPHAVANTAGE_API_KEY

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "stocks.db")
CSV_PATH = str(BASE_DIR / "sp500_companies.csv")



def create_local_database(csv_path: str = "sp500_companies.csv"):
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"'{csv_path}' not found.\n"
            "Download from: https://www.kaggle.com/datasets/andrewmvd/sp-500-stocks"
        )
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip().str.lower()
    df = df.rename(columns={
        "symbol":"ticker", "shortname":"company",
        "sector":"sector",  "industry":"industry",
        "exchange":"exchange", "marketcap":"market_cap_raw"
    })

    # bucket market cap into "Small", "Mid", "Large"
    def cap_bucket(v):
        try:
            v = float(v)
            return "Large" if v >= 10_000_000_000 else "Mid" if v >= 2_000_000_000 else "Small"
        except: return "Unknown"

    # apply bucketing and clean up the DataFrame
    # also drop rows with missing ticker or company, and remove duplicates based on ticker
    df["market_cap"] = df["market_cap_raw"].apply(cap_bucket)
    df = (df.dropna(subset=["ticker","company"])
            .drop_duplicates(subset=["ticker"])
            [["ticker","company","sector","industry","market_cap","exchange"]])
    
    # save to SQLite database
    conn = sqlite3.connect(DB_PATH)
    df.to_sql("stocks", conn, if_exists="replace", index=False)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ticker ON stocks(ticker)")
    conn.commit()

    # print summary info
    n = pd.read_sql_query("SELECT COUNT(*) AS n FROM stocks", conn).iloc[0]["n"]
    print(f"✅ {n} companies loaded into stocks.db")
    print("\nDistinct sector values stored in DB:")
    print(pd.read_sql_query("SELECT DISTINCT sector FROM stocks ORDER BY sector", conn).to_string(index=False))
    conn.close()



# ── Tool 1 ── Provided ────────────────────────────────────────
def get_price_performance(tickers: list, period: str = "1y") -> dict:
    """
    % price change for a list of tickers over a period.
    Valid periods: '1mo', '3mo', '6mo', 'ytd', '1y'
    Returns: { TICKER: {start_price, end_price, pct_change, period} }
    """
    results = {}
    for ticker in tickers:
        try:
            data = yf.download(ticker, period=period, progress=False, auto_adjust=True)
            if data.empty:
                results[ticker] = {"error": "No data — possibly delisted"}
                continue
        
            start = float(data["Close"].iloc[0].item())
            end   = float(data["Close"].iloc[-1].item())
            results[ticker] = {
                "start_price": round(start, 2),
                "end_price"  : round(end,   2),
                "pct_change" : round((end - start) / start * 100, 2),
                "period"     : period,
            }
        except Exception as e:
            results[ticker] = {"error": str(e)}
    return results

# ── Tool 2 ── Provided ────────────────────────────────────────
def get_market_status() -> dict:
    """Open / closed status for global stock exchanges."""
    return requests.get(
        # AV_BASE + "/query?function=MARKET_STATUS",
        f"https://www.alphavantage.co/query?function=MARKET_STATUS"
        f"&apikey={ALPHAVANTAGE_API_KEY}", timeout=10
    ).json()

# ── Tool 3 ── Provided ────────────────────────────────────────
def get_top_gainers_losers() -> dict:
    """Today's top gaining, top losing, and most active tickers."""
    return requests.get(
        # AV_BASE + "/query?function=TOP_GAINERS_LOSERS",
        f"https://www.alphavantage.co/query?function=TOP_GAINERS_LOSERS"
        f"&apikey={ALPHAVANTAGE_API_KEY}", timeout=10
    ).json()

# ── Tool 4 ── Provided ────────────────────────────────────────
def get_news_sentiment(ticker: str, limit: int = 5) -> dict:
    """
    Latest headlines + Bullish / Bearish / Neutral sentiment for a ticker.
    Returns: { ticker, articles: [{title, source, sentiment, score}] }
    """
    data = requests.get(
        # AV_BASE + "/query?function=NEWS_SENTIMENT",
        f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT"
        f"&tickers={ticker}&limit={limit}&apikey={ALPHAVANTAGE_API_KEY}", timeout=10
    ).json()
    return {
        "ticker": ticker,
        "articles": [
            {
                "title"    : a.get("title"),
                "source"   : a.get("source"),
                "sentiment": a.get("overall_sentiment_label"),
                "score"    : a.get("overall_sentiment_score"),
            }
            for a in data.get("feed", [])[:limit]
        ],
    }

# ── Tool 5 ── Provided ────────────────────────────────────────
def query_local_db(sql: str) -> dict:
    """
    Run any SQL SELECT on stocks.db.
    Table 'stocks' columns: ticker, company, sector, industry, market_cap, exchange
    market_cap values: 'Large' | 'Mid' | 'Small'
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        df   = pd.read_sql_query(sql, conn)
        conn.close()
        return {"columns": list(df.columns), "rows": df.to_dict(orient="records")}
    except Exception as e:
        return {"error": str(e)}


# ── Tool 6 — YOUR IMPLEMENTATION ─────────────────────────────
def get_company_overview(ticker: str) -> dict:

    try:
        data = requests.get(
            # AV_BASE + "/query?function=OVERVIEW",
            f"https://www.alphavantage.co/query?function=OVERVIEW"
            f"&symbol={ticker}&apikey={ALPHAVANTAGE_API_KEY}", 
            timeout=10
        ).json()

        if not data or "Name" not in data:
            # print(f"⚠️ No overview data for {ticker}")
            return {"error": f"No overview data for {ticker}"}
        return {
            "ticker": ticker,
            "name": data.get("Name"),
            "sector": data.get("Sector"),
            "industry": data.get("Industry"),
            "pe_ratio": float(data.get("PERatio", "nan")),
            "eps": float(data.get("EPS", "nan")),
            "market_cap": float(data.get("MarketCapitalization", "nan")),
            "52w_high": float(data.get("52WeekHigh", "nan")),
            "52w_low": float(data.get("52WeekLow", "nan")),
        }
    except Exception as e:
        return {"error": f"API request failed: {str(e)}"}


# ── Tool 7 — YOUR IMPLEMENTATION ─────────────────────────────
def get_tickers_by_sector(sector: str) -> dict:
   
    try:
        # Step 1: exact match on sector
        conn = sqlite3.connect(DB_PATH)

        sql_sector = """
            SELECT ticker, company, industry 
            FROM stocks
            WHERE LOWER(sector) = LOWER(?)
            """
        
        df = pd.read_sql_query(sql_sector, conn, params=(sector,))
        
        # Check if got results from the exact sector match
        if not df.empty:
            conn.close()
            return {"sector": sector, "stocks": df.to_dict(orient="records")}
        
        # No exact sector match → try LIKE on industry
        # Step 2: LIKE match on industry
        sql_industry = """
            SELECT ticker, company, industry 
            FROM stocks
            WHERE LOWER(industry) LIKE LOWER(?) 
            """
        
        df = pd.read_sql_query(sql_industry, conn, params=(f"%{sector}%",))
        conn.close()
        return {"sector": sector, "stocks": df.to_dict(orient="records")}
    
    except Exception as e:
        return {"error": f"Database query failed: {str(e)}"}



def _s(name, desc, props, req):
    return {"type":"function","function":{
        "name":name,"description":desc,
        "parameters":{"type":"object","properties":props,"required":req}}}

SCHEMA_TICKERS  = _s("get_tickers_by_sector",
    "Return all stocks in a sector or industry from the local database. "
    "Use broad sector names ('Information Technology', 'Energy') or sub-sectors ('semiconductor', 'insurance').",
    {"sector":{"type":"string","description":"Sector or industry name"}}, ["sector"])

SCHEMA_PRICE    = _s("get_price_performance",
    "Get % price change for a list of tickers over a time period. "
    "Periods: '1mo','3mo','6mo','ytd','1y'.",
    {"tickers":{"type":"array","items":{"type":"string"}},
     "period":{"type":"string","default":"1y"}}, ["tickers"])

SCHEMA_OVERVIEW = _s("get_company_overview",
    "Get fundamentals for one stock: P/E ratio, EPS, market cap, 52-week high and low.",
    {"ticker":{"type":"string","description":"Ticker symbol e.g. 'AAPL'"}}, ["ticker"])

SCHEMA_STATUS   = _s("get_market_status",
    "Check whether global stock exchanges are currently open or closed.", {}, [])

SCHEMA_MOVERS   = _s("get_top_gainers_losers",
    "Get today's top gaining, top losing, and most actively traded stocks.", {}, [])

SCHEMA_NEWS     = _s("get_news_sentiment",
    "Get latest news headlines and Bullish/Bearish/Neutral sentiment scores for a stock.",
    {"ticker":{"type":"string"},"limit":{"type":"integer","default":5}}, ["ticker"])

SCHEMA_SQL      = _s("query_local_db",
    "Run a SQL SELECT on stocks.db. "
    "Table 'stocks': ticker, company, sector, industry, market_cap (Large/Mid/Small), exchange.",
    {"sql":{"type":"string","description":"A valid SQL SELECT statement"}}, ["sql"])

# All 7 schemas in one list — used by single agent
ALL_SCHEMAS = [SCHEMA_TICKERS, SCHEMA_PRICE, SCHEMA_OVERVIEW,
               SCHEMA_STATUS, SCHEMA_MOVERS, SCHEMA_NEWS, SCHEMA_SQL]

# Dispatch map — maps the tool name string the LLM returns → the Python function to call
ALL_TOOL_FUNCTIONS = {
    "get_tickers_by_sector" : get_tickers_by_sector,
    "get_price_performance"  : get_price_performance,
    "get_company_overview"   : get_company_overview,
    "get_market_status"      : get_market_status,
    "get_top_gainers_losers" : get_top_gainers_losers,
    "get_news_sentiment"     : get_news_sentiment,
    "query_local_db"         : query_local_db,
}


