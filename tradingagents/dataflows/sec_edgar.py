"""
CooperCorp PRJ-002 — SEC EDGAR data integration.
Free API, no key needed. Covers 8-K filings, insider transactions, 13F.
"""
import requests
from datetime import date, timedelta


HEADERS = {"User-Agent": "CooperCorp trading@coopercorp.ai"}


def get_cik(sym: str) -> str | None:
    """Resolve ticker to SEC CIK number."""
    try:
        r = requests.get(
            "https://efts.sec.gov/LATEST/search-index?q=%22" + sym + "%22&dateRange=custom&startdt=2020-01-01&forms=10-K",
            headers=HEADERS, timeout=8
        )
        # Use the company tickers JSON instead
        r2 = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=HEADERS, timeout=8
        )
        data = r2.json()
        sym_upper = sym.upper()
        for k, v in data.items():
            if v.get("ticker", "").upper() == sym_upper:
                return str(v["cik_str"]).zfill(10)
        return None
    except Exception:
        return None


def get_recent_filings(sym: str, form_type: str = "8-K", limit: int = 5) -> list:
    """Fetch recent SEC filings for a ticker. 8-K = major events."""
    try:
        cik = get_cik(sym)
        if not cik:
            return [{"note": f"CIK not found for {sym}"}]
        r = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=HEADERS, timeout=10
        )
        data = r.json()
        filings = data.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        dates = filings.get("filingDate", [])
        descriptions = filings.get("primaryDocument", [])
        accessions = filings.get("accessionNumber", [])

        results = []
        for i, form in enumerate(forms):
            if form == form_type and len(results) < limit:
                results.append({
                    "form": form,
                    "date": dates[i] if i < len(dates) else "",
                    "document": descriptions[i] if i < len(descriptions) else "",
                    "accession": accessions[i] if i < len(accessions) else "",
                    "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accessions[i].replace('-','')}/{descriptions[i]}" if i < len(accessions) and i < len(descriptions) else "",
                })
        return results if results else [{"note": f"No {form_type} filings found for {sym}"}]
    except Exception as e:
        return [{"error": str(e)}]


def get_insider_transactions(sym: str, limit: int = 10) -> list:
    """SEC Form 4 insider transactions (buys/sells by officers/directors)."""
    try:
        cik = get_cik(sym)
        if not cik:
            return [{"note": f"CIK not found for {sym}"}]
        r = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=HEADERS, timeout=10
        )
        data = r.json()
        filings = data.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        dates = filings.get("filingDate", [])
        reporters = filings.get("reportingOwner", []) if "reportingOwner" in filings else []

        results = []
        for i, form in enumerate(forms):
            if form == "4" and len(results) < limit:
                results.append({
                    "form": "4",
                    "date": dates[i] if i < len(dates) else "",
                    "reporter": reporters[i] if i < len(reporters) else "insider",
                    "note": "See full filing on SEC EDGAR for transaction details",
                })
        return results if results else [{"note": f"No Form 4 filings found for {sym}"}]
    except Exception as e:
        return [{"error": str(e)}]


def get_recent_8k_summary(sym: str) -> str:
    """Returns a text summary of recent 8-K filings (major events)."""
    filings = get_recent_filings(sym, "8-K", limit=3)
    if not filings or "error" in filings[0]:
        return f"No recent 8-K filings found for {sym}"
    lines = [f"Recent 8-K filings for {sym}:"]
    for f in filings:
        lines.append(f"  {f['date']}: {f['document']} - {f.get('url', '')}")
    return "\n".join(lines)
