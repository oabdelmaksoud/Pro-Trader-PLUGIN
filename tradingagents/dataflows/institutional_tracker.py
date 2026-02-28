"""
CooperCorp PRJ-002 — 13F Hedge Fund Tracker
Tracks holdings of major funds via SEC EDGAR.
Cached 24h since 13F is quarterly data.
"""
import requests
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

TRACKED_FUNDS = {
    "Berkshire Hathaway": "0001067983",
    "Citadel Advisors": "0001423689",
    "Renaissance Technologies": "0001037389",
    "Bridgewater Associates": "0001350694",
    "Tiger Global Management": "0001167483",
    "Viking Global Investors": "0001103804",
}

_HEADERS = {
    "User-Agent": "CooperCorp Trading coopercorp@trading.ai",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov"
}
_holdings_cache = {}  # cik -> (holdings_dict, timestamp)
_CACHE_TTL = 86400  # 24h


def _get_latest_13f_accession(cik: str) -> Optional[str]:
    """Get accession number of the most recent 13F filing."""
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
        r = requests.get(url, headers=_HEADERS, timeout=10)
        if not r.ok:
            return None
        data = r.json()
        filings = data.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        accessions = filings.get("accessionNumber", [])
        for form, acc in zip(forms, accessions):
            if "13F" in form:
                return acc.replace("-", "")
        return None
    except Exception:
        return None


def get_fund_holdings(cik: str) -> dict:
    """
    Get ticker -> shares dict for a fund's most recent 13F.
    Returns {} on any failure. Cached 24h.
    """
    now = datetime.now(timezone.utc).timestamp()
    if cik in _holdings_cache:
        holdings, ts = _holdings_cache[cik]
        if now - ts < _CACHE_TTL:
            return holdings

    try:
        accession = _get_latest_13f_accession(cik)
        if not accession:
            return {}

        # Fetch the index to find the XML file
        idx_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{accession}-index.json"
        r = requests.get(idx_url, headers={**_HEADERS, "Host": "www.sec.gov"}, timeout=10)
        if not r.ok:
            _holdings_cache[cik] = ({}, now)
            return {}

        idx_data = r.json()
        # Find infotable XML
        xml_file = None
        for item in idx_data.get("directory", {}).get("item", []):
            name = item.get("name", "")
            if "infotable" in name.lower() or name.endswith(".xml"):
                xml_file = name
                break

        if not xml_file:
            _holdings_cache[cik] = ({}, now)
            return {}

        xml_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{xml_file}"
        xr = requests.get(xml_url, headers={**_HEADERS, "Host": "www.sec.gov"}, timeout=15)
        if not xr.ok:
            _holdings_cache[cik] = ({}, now)
            return {}

        # Parse XML
        import re
        holdings = {}
        text = xr.text
        # Extract nameOfIssuer and sshPrnamt pairs
        issuers = re.findall(r'<nameOfIssuer>(.*?)</nameOfIssuer>', text)
        shares = re.findall(r'<sshPrnamt>(\d+)</sshPrnamt>', text)
        cusips = re.findall(r'<cusip>(.*?)</cusip>', text)

        for issuer, share_count in zip(issuers, shares):
            # Convert issuer name to approximate ticker (imperfect but useful)
            ticker_guess = issuer.split()[0].upper().replace(".", "").replace(",", "")
            holdings[ticker_guess] = int(share_count)

        _holdings_cache[cik] = (holdings, now)
        return holdings

    except Exception as e:
        _holdings_cache[cik] = ({}, now)
        return {}


def get_ticker_institutional_ownership(ticker: str) -> dict:
    """
    Check which tracked funds hold a ticker.
    Returns {funds_holding, net_buyers, net_sellers, consensus}
    """
    try:
        ticker_upper = ticker.upper()
        funds_holding = []
        for fund_name, cik in TRACKED_FUNDS.items():
            try:
                holdings = get_fund_holdings(cik)
                if ticker_upper in holdings and holdings[ticker_upper] > 0:
                    funds_holding.append({"fund": fund_name, "shares": holdings[ticker_upper]})
            except Exception:
                continue

        count = len(funds_holding)
        if count >= 3:
            consensus = "bullish"
        elif count >= 1:
            consensus = "neutral"
        else:
            consensus = "bearish"

        return {
            "funds_holding": funds_holding,
            "fund_count": count,
            "net_buyers": count,  # simplified — full quarter-over-quarter would need prev 13F
            "net_sellers": 0,
            "consensus": consensus
        }
    except Exception:
        return {}
