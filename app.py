"""
My Portfolio Dashboard
------------------------
Manual entry — no account connection, no API keys. Type in what you hold,
get live prices, allocation charts, and for each stock: recent news
headlines, next earnings date, and analyst consensus data.

Run locally:
    streamlit run app.py
"""

import os
import urllib.parse
from datetime import datetime

import feedparser
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Mia's Portfolio", page_icon="📈", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700;800&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
    background-color: #101E38 !important;
}
[data-testid="stAppViewContainer"], [data-testid="stHeader"] {
    background-color: #101E38 !important;
}
h1, h2, h3 {
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em;
}
h1 {
    color: #E7F6FF !important;
    text-shadow: 0 0 18px rgba(34, 211, 238, 0.25);
    font-weight: 800 !important;
    font-size: 3rem !important;
    line-height: 1.05 !important;
}
h2, h3 { color: #22D3EE !important; font-weight: 700 !important; }

/* Numbers read as data, not prose */
[data-testid="stMetricValue"], [data-testid="stMetricDelta"] {
    font-family: 'IBM Plex Mono', monospace !important;
}
[data-testid="stMetric"] {
    background: linear-gradient(180deg, #17284A 0%, #132239 100%);
    border: 1px solid rgba(34, 211, 238, 0.25);
    border-radius: 10px;
    padding: 14px 16px;
    box-shadow: 0 0 20px rgba(34, 211, 238, 0.05);
}

/* Bordered containers (flags box) */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background-color: #17284A;
    border: 1px solid rgba(34, 211, 238, 0.25) !important;
    border-radius: 10px;
}

/* Tabs — make them look like a real nav bar */
button[data-baseweb="tab"] {
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 600 !important;
    color: #7B8CA6 !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color: #22D3EE !important;
}
div[data-baseweb="tab-highlight"] {
    background-color: #22D3EE !important;
    box-shadow: 0 0 10px rgba(34, 211, 238, 0.6);
}
div[data-baseweb="tab-border"] {
    background-color: #1A2E45 !important;
}

hr { border-color: #1A2E45 !important; }

[data-testid="stDataFrame"] {
    font-family: 'IBM Plex Mono', monospace;
}

.stCaption, [data-testid="stCaptionContainer"] {
    font-family: 'Inter', sans-serif;
    color: #7B8CA6 !important;
}

/* Expander (per-stock cards) */
div[data-testid="stExpander"] {
    background-color: #17284A;
    border: 1px solid rgba(34, 211, 238, 0.18);
    border-radius: 10px;
}
</style>
""", unsafe_allow_html=True)

DATA_FILE = "my_holdings.csv"
CONCENTRATION_WARNING_PCT = 25
DRAWDOWN_WARNING_PCT = 15
BENCHMARK_TICKER = "^GSPC"  # S&P 500. Use "^FTAS" for FTSE All-Share instead.
NEWS_PER_STOCK = 5


CURRENCY_SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€", "JPY": "¥", "CHF": "CHF ", "CAD": "C$", "AUD": "A$"}
BASE_CURRENCY = "GBP"

MARKET_INDICATORS = [
    ("^GSPC", "S&P 500"),
    ("^FTSE", "FTSE 100"),
    ("^IXIC", "Nasdaq"),
    ("^VIX", "VIX (volatility)"),
    ("^TNX", "US 10Y Treasury yield"),
]

# A fixed universe of well-known large caps to scan for the Discover tab.
# Not a recommendation list — just what gets checked for movers/analyst upside.
WATCHLIST_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "NFLX", "AMD", "JPM",
    "V", "MA", "DIS", "PYPL", "INTC", "CRM", "ADBE", "ORCL", "COST", "PEP",
    "VOD.L", "BARC.L", "HSBA.L", "AZN.L", "GSK.L", "SHEL.L", "BP.L", "ULVR.L",
    "TSCO.L", "LLOY.L", "RIO.L", "GLEN.L", "NG.L", "DGE.L", "REL.L",
]


# ---------------------------------------------------------------------------
# LOAD / SAVE HOLDINGS
# ---------------------------------------------------------------------------

def load_holdings() -> pd.DataFrame:
    if os.path.exists(DATA_FILE):
        return pd.read_csv(DATA_FILE)
    return pd.DataFrame([{"Ticker": "AAPL", "Quantity": 10.0, "Avg Price": 150.0}])


def save_holdings(df: pd.DataFrame):
    df.to_csv(DATA_FILE, index=False)


WATCHLIST_FILE = "my_watchlist.csv"


def load_watchlist() -> pd.DataFrame:
    if os.path.exists(WATCHLIST_FILE):
        return pd.read_csv(WATCHLIST_FILE)
    return pd.DataFrame([{"Ticker": "NVDA"}])


def save_watchlist(df: pd.DataFrame):
    df.to_csv(WATCHLIST_FILE, index=False)


# ---------------------------------------------------------------------------
# MARKET DATA
# ---------------------------------------------------------------------------

@st.cache_data(ttl=900, show_spinner=False)
def fetch_market_data(tickers: tuple):
    rows = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).info
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            currency = info.get("currency", BASE_CURRENCY)
            target_mean = info.get("targetMeanPrice")
            target_high = info.get("targetHighPrice")
            target_low = info.get("targetLowPrice")
            # Yahoo quotes many LSE stocks in pence (GBp), not pounds — applies to
            # both the trading price and analyst targets, so convert both.
            if currency == "GBp":
                currency = "GBP"
                if price is not None:
                    price = price / 100
                if target_mean is not None:
                    target_mean = target_mean / 100
                if target_high is not None:
                    target_high = target_high / 100
                if target_low is not None:
                    target_low = target_low / 100
            profit_margin = info.get("profitMargins")
            if profit_margin is not None:
                profit_margin = profit_margin * 100
            revenue_growth = info.get("revenueGrowth")
            if revenue_growth is not None:
                revenue_growth = revenue_growth * 100
            div_yield = info.get("dividendYield")
            if div_yield is not None:
                # yfinance has been inconsistent across versions about whether
                # this is a fraction (0.025) or already a percentage (2.5) —
                # yields over 100% are essentially never real, so use that as
                # the signal for which format we got.
                if div_yield < 1:
                    div_yield = div_yield * 100
            rows[t] = {
                "current_price": price,
                "currency": currency,
                "name": info.get("shortName", t),
                "sector": info.get("sector", "Unknown"),
                "trailing_pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "price_to_book": info.get("priceToBook"),
                "dividend_yield": div_yield,
                "debt_to_equity": info.get("debtToEquity"),
                "profit_margin": profit_margin,
                "revenue_growth": revenue_growth,
                "beta": info.get("beta"),
                "recommendation": info.get("recommendationKey"),  # e.g. "buy", "hold"
                "num_analysts": info.get("numberOfAnalystOpinions"),
                "target_mean_price": target_mean,
                "target_high_price": target_high,
                "target_low_price": target_low,
                "day_change_pct": info.get("regularMarketChangePercent"),
            }
        except Exception:
            rows[t] = {"current_price": None, "currency": BASE_CURRENCY, "name": t, "sector": "Unknown"}
    return rows


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fx_rate(currency: str) -> float:
    """Rate to convert 1 unit of `currency` into BASE_CURRENCY. 1.0 if already base."""
    if currency == BASE_CURRENCY:
        return 1.0
    try:
        pair = yf.Ticker(f"{currency}{BASE_CURRENCY}=X")
        rate = pair.fast_info.get("lastPrice")
        if rate:
            return float(rate)
    except Exception:
        pass
    try:
        # fall back to the inverse pair if the direct one isn't available
        pair = yf.Ticker(f"{BASE_CURRENCY}{currency}=X")
        rate = pair.fast_info.get("lastPrice")
        if rate:
            return 1.0 / float(rate)
    except Exception:
        pass
    return None  # unknown — caller should flag this rather than silently assume 1:1


@st.cache_data(ttl=600, show_spinner=False)
def fetch_market_overview():
    rows = []
    for ticker, label in MARKET_INDICATORS:
        try:
            fi = yf.Ticker(ticker).fast_info
            last = fi.get("lastPrice")
            prev = fi.get("previousClose")
            if ticker == "^TNX" and last is not None:
                # CBOE convention: index value is yield x 10
                last = last / 10
                prev = prev / 10 if prev else prev
            change_pct = ((last - prev) / prev * 100) if (last and prev) else None
            rows.append({"label": label, "value": last, "change_pct": change_pct, "is_yield": ticker == "^TNX"})
        except Exception:
            rows.append({"label": label, "value": None, "change_pct": None, "is_yield": False})
    return rows


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_earnings_date(ticker: str):
    try:
        dates = yf.Ticker(ticker).get_earnings_dates(limit=4)
        if dates is None or dates.empty:
            return None
        future = dates[dates.index >= pd.Timestamp.now(tz=dates.index.tz)]
        if not future.empty:
            return future.index.min()
        return dates.index.max()
    except Exception:
        return None


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_news(company_name: str, ticker: str, limit: int = NEWS_PER_STOCK):
    """Pulls recent headlines from Google News RSS — no API key needed.
    Naturally surfaces FT, BBC, Reuters etc. when they cover the stock."""
    query = urllib.parse.quote(f"{company_name} stock")
    url = f"https://news.google.com/rss/search?q={query}&hl=en-GB&gl=GB&ceid=GB:en"
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            timeout=10,
        )
        feed = feedparser.parse(resp.content)
        items = []
        for entry in feed.entries[:limit]:
            source = entry.get("source", {}).get("title", "") if hasattr(entry, "get") else ""
            items.append({
                "title": entry.title,
                "link": entry.link,
                "published": entry.get("published", ""),
                "source": source,
            })
        return items
    except Exception:
        return []


@st.cache_data(ttl=900, show_spinner=False)
def fetch_benchmark_history(days: int = 180):
    return yf.Ticker(BENCHMARK_TICKER).history(period=f"{days}d")


# ---------------------------------------------------------------------------
# MAIN APP
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# FUNDAMENTALS SCORECARD
# ---------------------------------------------------------------------------
# Plain-English badges for common valuation/health metrics. These are general
# rule-of-thumb ranges used widely in investing education — not personalised
# advice, and context (sector, growth stage, market conditions) always matters.
# A "high" reading isn't automatically bad, and a "low" one isn't automatically
# good — e.g. a low P/E can mean a bargain or can mean the market expects
# trouble. Use these as a starting point for your own research, not a verdict.

def badge(level: str) -> str:
    return {"green": "🟢", "amber": "🟡", "red": "🔴", "grey": "⚪"}.get(level, "⚪")


def metric_row(label: str, value, fmt: str, thresholds, explain: str):
    """thresholds: list of (upper_bound_or_None, level, description)."""
    if value is None:
        return f"{badge('grey')} **{label}:** not available — {explain}"
    level, desc = "grey", ""
    for upper, lvl, d in thresholds:
        if upper is None or value <= upper:
            level, desc = lvl, d
            break
    value_str = fmt.format(value)
    return f"{badge(level)} **{label}: {value_str}** — {desc} *({explain})*"


def render_fundamentals_scorecard(info: dict):
    st.markdown("**Fundamentals scorecard** — how this stock reads on common measures:")

    lines = []
    lines.append(metric_row(
        "P/E ratio (trailing)", info.get("trailing_pe"), "{:.1f}x",
        [(15, "green", "Low relative to earnings — could mean undervalued, or could mean the market expects trouble"),
         (25, "amber", "Moderate — fairly typical for an established company"),
         (None, "red", "High — market is pricing in strong future growth; more downside risk if it disappoints")],
        "price you pay per £1 of annual profit",
    ))
    lines.append(metric_row(
        "Price-to-book", info.get("price_to_book"), "{:.2f}x",
        [(1, "green", "Trading below its net asset value"),
         (3, "amber", "Reasonable premium to assets"),
         (None, "red", "Large premium to assets — priced mostly on future potential, not current assets")],
        "share price vs. net assets per share",
    ))
    lines.append(metric_row(
        "Dividend yield", info.get("dividend_yield"), "{:.2f}%",
        [(0.01, "grey", "No meaningful dividend — likely reinvesting for growth instead"),
         (4, "green", "Modest, typically sustainable income"),
         (None, "amber", "High yield — worth checking it's sustainable, very high yields can signal distress")],
        "annual dividend as % of share price",
    ))
    debt_eq = info.get("debt_to_equity")
    lines.append(metric_row(
        "Debt-to-equity", debt_eq, "{:.0f}%",
        [(50, "green", "Low leverage — less financial risk"),
         (150, "amber", "Moderate leverage — fairly normal for many industries"),
         (None, "red", "High leverage — more sensitive to rising interest rates or a downturn")],
        "debt relative to shareholder equity",
    ))
    lines.append(metric_row(
        "Profit margin", info.get("profit_margin"), "{:.1f}%",
        [(5, "red", "Thin margins — less buffer if costs rise"),
         (20, "amber", "Solid, fairly typical margins"),
         (None, "green", "Strong margins — often a sign of pricing power")],
        "how much of revenue becomes profit",
    ))
    lines.append(metric_row(
        "Revenue growth (YoY)", info.get("revenue_growth"), "{:.1f}%",
        [(0, "red", "Revenue shrinking year-on-year"),
         (10, "amber", "Modest growth"),
         (None, "green", "Strong growth")],
        "change in sales vs. a year ago",
    ))
    lines.append(metric_row(
        "Beta (volatility vs. market)", info.get("beta"), "{:.2f}",
        [(0.8, "green", "Tends to move less than the overall market"),
         (1.2, "amber", "Moves roughly in line with the market"),
         (None, "red", "Tends to swing more than the market — higher risk, higher potential reward")],
        "1.0 = moves with the market",
    ))

    for line in lines:
        st.markdown(line)

    st.caption(
        "These are general rule-of-thumb ranges, not a verdict — a metric that "
        "looks 'red' here can still be completely normal for the right kind of "
        "company (e.g. high-growth tech often runs high P/E and thin/no margins "
        "by design). Compare against similar companies in the same sector, not "
        "just these fixed cut-offs."
    )


def render_market_overview():
    st.subheader("Market overview")
    overview = fetch_market_overview()
    cols = st.columns(len(overview))
    for col, item in zip(cols, overview):
        if item["value"] is None:
            col.metric(item["label"], "—")
            continue
        suffix = "%" if item["is_yield"] else ""
        value_str = f"{item['value']:,.2f}{suffix}"
        delta_str = f"{item['change_pct']:+.2f}%" if item["change_pct"] is not None else None
        col.metric(item["label"], value_str, delta_str)
    st.caption("VIX above ~20 typically signals elevated market fear; below ~15 signals calm.")


# ---------------------------------------------------------------------------
# PASSWORD GATE (only matters once deployed online — no-op for local use)
# ---------------------------------------------------------------------------

def get_secret(key: str, default=None):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)


def check_password() -> bool:
    configured_password = get_secret("APP_PASSWORD")
    if not configured_password:
        return True  # no password configured — fine for local-only use

    if st.session_state.get("authed"):
        return True

    st.title("Mia's Portfolio")
    pwd = st.text_input("Password", type="password")
    if st.button("Unlock") or pwd:
        if pwd == configured_password:
            st.session_state["authed"] = True
            st.rerun()
        elif pwd:
            st.error("Wrong password.")
    return False


TERMINAL_PALETTE = ["#22D3EE", "#7B8CA6", "#F472B6", "#34D399", "#A78BFA", "#FBBF24", "#60A5FA", "#F87171"]


def theme_chart(fig):
    fig.update_layout(
        paper_bgcolor="#101E38",
        plot_bgcolor="#101E38",
        font=dict(family="Inter, sans-serif", color="#E7F6FF"),
        legend=dict(font=dict(color="#E7F6FF")),
    )
    return fig


@st.cache_data(ttl=900, show_spinner=False)
def fetch_price_history(ticker: str, period: str = "1mo"):
    try:
        hist = yf.Ticker(ticker).history(period=period)
        return hist
    except Exception:
        return pd.DataFrame()


def render_stock_card(ticker: str, name: str, info: dict, currency_symbol: str = "£"):
    """Renders the live price/chart, earnings/fundamentals/analyst/news rundown
    for one stock. Shared by the Holdings detail, Watchlist, and Discover tabs."""
    sym = currency_symbol
    price = info.get("current_price")
    change = info.get("day_change_pct")

    price_cols = st.columns([1, 1, 3])
    price_cols[0].metric(
        "Live price",
        f"{sym}{price:,.2f}" if price is not None else "—",
        f"{change:+.2f}% today" if change is not None else None,
    )

    period_choice = price_cols[2].radio(
        "Chart range", ["1D", "5D", "1M", "6M", "1Y"], index=2,
        horizontal=True, key=f"period_{ticker}", label_visibility="collapsed",
    )
    period_map = {"1D": "1d", "5D": "5d", "1M": "1mo", "6M": "6mo", "1Y": "1y"}
    hist = fetch_price_history(ticker, period_map[period_choice])

    if not hist.empty:
        line_color = "#34D399" if (hist["Close"].iloc[-1] >= hist["Close"].iloc[0]) else "#F87171"
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=hist.index, y=hist["Close"], mode="lines",
            line=dict(color=line_color, width=2),
        ))
        fig.update_layout(
            height=220, margin=dict(l=0, r=0, t=10, b=0),
            xaxis=dict(gridcolor="#1A2E45", showgrid=False),
            yaxis=dict(gridcolor="#1A2E45"),
            showlegend=False,
        )
        st.plotly_chart(theme_chart(fig), use_container_width=True, key=f"chart_{ticker}_{period_choice}")
    else:
        st.caption("Price history not available for this ticker.")

    earnings_date = fetch_earnings_date(ticker)
    if earnings_date is not None:
        st.markdown(f"**Next/last earnings date:** {earnings_date.strftime('%d %b %Y')}")
    else:
        st.markdown("**Earnings date:** not available")

    st.markdown("")
    render_fundamentals_scorecard(info)
    st.markdown("")

    sym = currency_symbol
    rec = info.get("recommendation")
    num_analysts = info.get("num_analysts")
    target_mean = info.get("target_mean_price")
    if rec or target_mean:
        st.markdown("**Analyst consensus (Yahoo Finance):**")
        cols = st.columns(4)
        cols[0].metric("Rating", (rec or "—").replace("_", " ").title())
        cols[1].metric("Analysts", num_analysts or "—")
        cols[2].metric("Avg target", f"{sym}{target_mean:,.2f}" if target_mean else "—")
        if info.get("target_low_price") and info.get("target_high_price"):
            cols[3].metric(
                "Target range",
                f"{sym}{info['target_low_price']:.0f}–{info['target_high_price']:.0f}",
            )
    else:
        st.markdown("**Analyst consensus:** not available for this ticker")

    st.markdown("**Recent news:**")
    news_items = fetch_news(name or ticker, ticker)
    if news_items:
        for item in news_items:
            published = item["published"]
            try:
                published = datetime.strptime(
                    published, "%a, %d %b %Y %H:%M:%S %Z"
                ).strftime("%d %b %Y")
            except Exception:
                pass
            source = f" — *{item['source']}*" if item["source"] else ""
            st.markdown(f"- [{item['title']}]({item['link']}){source} ({published})")
    else:
        st.markdown("No recent news found.")


def main():
    if not check_password():
        st.stop()

    st.title("Mia's Portfolio")
    st.caption("Manually entered — nothing is connected to any brokerage account.")

    if "holdings" not in st.session_state:
        st.session_state["holdings"] = load_holdings()

    tab_overview, tab_holdings, tab_charts, tab_stocks, tab_watchlist, tab_discover = st.tabs(
        ["Overview", "Holdings", "Charts & Market", "Stock Detail", "Watchlist", "Discover"]
    )

    # Holdings tab renders the editor and produces `edited_df` used everywhere else.
    with tab_holdings:
        st.subheader("Your holdings")
        st.caption(
            "Add a row per stock/ETF you hold. Use the ticker as it appears on "
            "Yahoo Finance — e.g. AAPL for Apple, VOD.L for Vodafone (London)."
        )
        edited_df = st.data_editor(
            st.session_state["holdings"],
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Ticker": st.column_config.TextColumn(required=True),
                "Quantity": st.column_config.NumberColumn(required=True, format="%.4f"),
                "Avg Price": st.column_config.NumberColumn(required=True, format="%.2f"),
            },
            key="editor",
        )
        if st.button("💾 Save holdings"):
            save_holdings(edited_df)
            st.session_state["holdings"] = edited_df
            st.success("Saved.")

    df = edited_df.dropna(subset=["Ticker"]).copy()
    df = df[df["Ticker"].str.strip() != ""]
    if df.empty:
        with tab_overview:
            st.info("Add at least one holding in the Holdings tab to see your dashboard.")
        st.stop()
    df["Ticker"] = df["Ticker"].str.strip().str.upper()

    with st.spinner("Fetching live prices..."):
        market_info = fetch_market_data(tuple(df["Ticker"].unique()))

    for col in ["current_price", "currency", "name", "sector", "trailing_pe"]:
        df[col] = df["Ticker"].map(lambda t: market_info.get(t, {}).get(col))

    missing = df[df["current_price"].isna()]
    if not missing.empty:
        st.warning(f"Couldn't find live prices for: {', '.join(missing['Ticker'])}.")
        df = df.dropna(subset=["current_price"])
    if df.empty:
        st.stop()

    # Convert everything to one base currency (GBP) so totals/allocation are accurate
    # even when you hold a mix of US, UK, and European stocks.
    df["fx_rate"] = df["currency"].apply(fetch_fx_rate)
    unknown_fx = df[df["fx_rate"].isna()]
    if not unknown_fx.empty:
        st.warning(
            f"Couldn't get an exchange rate for: {', '.join(unknown_fx['currency'].unique())} "
            "— these holdings are excluded from totals until that's resolved."
        )
        df = df.dropna(subset=["fx_rate"])
    if df.empty:
        st.stop()

    df["value_native"] = df["Quantity"] * df["current_price"]
    df["value"] = df["value_native"] * df["fx_rate"]  # value in GBP, used for all totals/charts
    df["cost_basis"] = df["Quantity"] * df["Avg Price"] * df["fx_rate"]
    df["pl"] = df["value"] - df["cost_basis"]
    df["return_pct"] = ((df["current_price"] - df["Avg Price"]) / df["Avg Price"] * 100).round(2)

    total_value = df["value"].sum()
    total_cost = df["cost_basis"].sum()
    total_pl = total_value - total_cost
    total_pl_pct = (total_pl / total_cost * 100) if total_cost else 0
    if total_value > 0:
        df["weight_pct"] = (df["value"] / total_value * 100).round(1)

    # --- OVERVIEW TAB -------------------------------------------------
    with tab_overview:
        render_market_overview()
        st.divider()

        m1, m2, m3 = st.columns(3)
        m1.metric("Portfolio value (£)", f"£{total_value:,.2f}")
        m2.metric("Total P&L (£)", f"£{total_pl:,.2f}", f"{total_pl_pct:+.2f}%")
        m3.metric("Holdings", f"{len(df)}")
        st.caption("Totals converted to GBP using current exchange rates for any non-UK holdings.")

        st.divider()

        flags = []
        for _, row in df.iterrows():
            if row["weight_pct"] > CONCENTRATION_WARNING_PCT:
                flags.append(f"⚠️ **{row['name']}** is {row['weight_pct']:.0f}% of your portfolio — concentrated position.")
            if row["return_pct"] < -DRAWDOWN_WARNING_PCT:
                flags.append(f"🔻 **{row['name']}** is down {row['return_pct']:.1f}% from your average buy price.")
        if flags:
            with st.container(border=True):
                st.subheader("Flags")
                for f in flags:
                    st.markdown(f)
        else:
            st.success("No concentration or drawdown flags right now.")

    # --- CHARTS TAB -----------------------------------------------------
    with tab_charts:
        st.subheader("Allocation")
        c1, c2 = st.columns(2)
        with c1:
            st.caption("By holding")
            fig = px.pie(df, values="value", names="name", hole=0.4, color_discrete_sequence=TERMINAL_PALETTE)
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(theme_chart(fig), use_container_width=True)
        with c2:
            st.caption("By sector")
            sector_df = df.groupby("sector", as_index=False)["value"].sum()
            fig2 = px.pie(sector_df, values="value", names="sector", hole=0.4, color_discrete_sequence=TERMINAL_PALETTE)
            fig2.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(theme_chart(fig2), use_container_width=True)

        st.divider()

        st.subheader("Details")
        df["currency_symbol"] = df["currency"].map(lambda c: CURRENCY_SYMBOLS.get(c, c + " "))
        df["Avg price"] = df.apply(lambda r: f"{r['currency_symbol']}{r['Avg Price']:,.2f}", axis=1)
        df["Current price"] = df.apply(lambda r: f"{r['currency_symbol']}{r['current_price']:,.2f}", axis=1)
        display_df = df[[
            "name", "Ticker", "Quantity", "Avg price", "Current price",
            "value", "return_pct", "weight_pct", "sector", "trailing_pe",
        ]].sort_values("value", ascending=False)
        display_df.columns = [
            "Name", "Ticker", "Qty", "Avg price", "Current price",
            "Value (£)", "Return %", "Weight %", "Sector", "P/E",
        ]
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Value (£)": st.column_config.NumberColumn(format="£%.2f"),
                "Return %": st.column_config.NumberColumn(format="%.2f%%"),
                "Weight %": st.column_config.NumberColumn(format="%.1f%%"),
                "P/E": st.column_config.NumberColumn(format="%.1f"),
            },
        )

        st.divider()

        st.subheader("Your top holdings vs S&P 500 (6 months)")
        bench = fetch_benchmark_history(180)
        if not bench.empty:
            bench_norm = bench["Close"] / bench["Close"].iloc[0] * 100
            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(
                x=bench_norm.index, y=bench_norm.values, name="S&P 500",
                line=dict(dash="dash", color="#7B8CA6"),
            ))
            top_holdings = df.sort_values("value", ascending=False).head(5)
            for i, (_, row) in enumerate(top_holdings.iterrows()):
                try:
                    hist = yf.Ticker(row["Ticker"]).history(period="180d")
                    if not hist.empty:
                        norm = hist["Close"] / hist["Close"].iloc[0] * 100
                        fig3.add_trace(go.Scatter(
                            x=norm.index, y=norm.values, name=row["name"],
                            line=dict(color=TERMINAL_PALETTE[i % len(TERMINAL_PALETTE)]),
                        ))
                except Exception:
                    continue
            fig3.update_layout(
                yaxis_title="Indexed to 100", height=450,
                xaxis=dict(gridcolor="#1A2E45"), yaxis=dict(gridcolor="#1A2E45"),
            )
            st.plotly_chart(theme_chart(fig3), use_container_width=True)

    # --- STOCK DETAIL TAB -------------------------------------------------
    with tab_stocks:
        st.caption(
            "Headlines pull from Google News (surfaces FT, BBC, Reuters etc. when "
            "they cover the stock — click through to read on the original site). "
            "Analyst data is Wall Street consensus, not personalised advice."
        )

        for _, row in df.sort_values("value", ascending=False).iterrows():
            info = market_info.get(row["Ticker"], {})
            with st.expander(f"{row['name']} ({row['Ticker']})"):
                render_stock_card(row["Ticker"], row["name"], info, row.get("currency_symbol", "£"))

        st.divider()
        st.caption(
            "This dashboard shows market context and third-party analyst data only — "
            "it does not give financial advice. Decisions are yours."
        )

    # --- WATCHLIST TAB -------------------------------------------------
    with tab_watchlist:
        st.subheader("Stocks you're tracking")
        st.caption(
            "Separate from your holdings — these don't count toward your "
            "portfolio value, they're just ones you want to keep an eye on."
        )

        if "watchlist" not in st.session_state:
            st.session_state["watchlist"] = load_watchlist()

        edited_watch = st.data_editor(
            st.session_state["watchlist"],
            num_rows="dynamic",
            use_container_width=True,
            column_config={"Ticker": st.column_config.TextColumn(required=True)},
            key="watchlist_editor",
        )

        if st.button("💾 Save watchlist"):
            save_watchlist(edited_watch)
            st.session_state["watchlist"] = edited_watch
            st.success("Saved.")

        watch_tickers = edited_watch.dropna(subset=["Ticker"])
        watch_tickers = watch_tickers[watch_tickers["Ticker"].str.strip() != ""]
        watch_tickers = watch_tickers["Ticker"].str.strip().str.upper().unique().tolist()

        if not watch_tickers:
            st.info("Add a ticker above to start tracking it.")
        else:
            with st.spinner("Fetching data..."):
                watch_info = fetch_market_data(tuple(watch_tickers))

            missing = [t for t in watch_tickers if watch_info.get(t, {}).get("current_price") is None]
            if missing:
                st.warning(f"Couldn't find live prices for: {', '.join(missing)}.")

            st.divider()
            for t in watch_tickers:
                info = watch_info.get(t, {})
                if info.get("current_price") is None:
                    continue
                sym = CURRENCY_SYMBOLS.get(info.get("currency", "GBP"), "")
                change = info.get("day_change_pct")
                change_str = f" · {change:+.2f}% today" if change is not None else ""
                with st.expander(f"{info.get('name', t)} ({t}) — {sym}{info['current_price']:,.2f}{change_str}"):
                    render_stock_card(t, info.get("name", t), info, sym)

    # --- DISCOVER TAB -------------------------------------------------
    with tab_discover:
        st.subheader("Analyst upside")
        st.caption(
            "Scanned from a fixed watchlist of well-known US and UK large-cap "
            "stocks — not picks or recommendations, just current analyst data. "
            "Decide for yourself whether any of it is worth a closer look."
        )

        with st.spinner("Scanning watchlist..."):
            watchlist_info = fetch_market_data(tuple(WATCHLIST_UNIVERSE))

        rows = []
        for t in WATCHLIST_UNIVERSE:
            info = watchlist_info.get(t, {})
            if info.get("current_price") is None:
                continue
            upside_pct = None
            if info.get("target_mean_price") and info.get("current_price"):
                upside_pct = (info["target_mean_price"] / info["current_price"] - 1) * 100
            rows.append({
                "ticker": t,
                "name": info.get("name", t),
                "day_change_pct": info.get("day_change_pct"),
                "upside_pct": upside_pct,
                "num_analysts": info.get("num_analysts"),
                "info": info,
            })

        wdf = pd.DataFrame(rows)
        wdf["region"] = wdf["ticker"].apply(lambda t: "UK" if t.endswith(".L") else "US")

        st.markdown("#### Where analysts see the most upside")
        st.caption(
            "Ranked by the gap between current price and the average analyst "
            "price target — a measure of Wall Street sentiment, not a forecast. "
            "Shown separately for US and UK since they don't compete on the same scale."
        )

        eligible = wdf.dropna(subset=["upside_pct"]).copy()
        eligible = eligible[eligible["num_analysts"].fillna(0) >= 3]

        for region, label in [("US", "🇺🇸 US"), ("UK", "🇬🇧 UK")]:
            region_df = eligible[eligible["region"] == region].sort_values("upside_pct", ascending=False).head(5)
            st.markdown(f"**{label}**")
            if region_df.empty:
                st.info(f"No analyst target data available for {region} stocks right now.")
            else:
                for _, r in region_df.iterrows():
                    info = r["info"]
                    sym = CURRENCY_SYMBOLS.get(info.get("currency", "GBP"), "")
                    with st.expander(f"{r['name']} ({r['ticker']}) — analysts see {r['upside_pct']:+.1f}% upside"):
                        render_stock_card(r["ticker"], r["name"], info, sym)

        st.divider()
        st.caption(
            "Discover shows market data only, from a fixed watchlist, not "
            "personalised or curated recommendations. Always do your own "
            "research before making any investment decision."
        )


if __name__ == "__main__":
    main()
