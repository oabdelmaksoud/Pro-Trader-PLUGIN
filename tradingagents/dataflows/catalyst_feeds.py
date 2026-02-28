"""
CooperCorp PRJ-002 — ClinicalTrials.gov + USPTO Catalyst Feeds
Tracks upcoming biotech catalysts for scoring bonuses.
"""
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional

_HEADERS = {"User-Agent": "CooperCorp-Trading/1.0 contact@coopercorp.ai"}
_TIMEOUT = 8


def get_clinical_trials(company: str) -> list:
    """Fetch Phase 3 clinical trials for a company from ClinicalTrials.gov API v2."""
    try:
        url = "https://clinicaltrials.gov/api/v2/studies"
        params = {
            "query.term": company,
            "filter.advanced": "AREA[Phase]PHASE3",
            "pageSize": 5,
            "format": "json",
            "fields": "NCTId,BriefTitle,OverallStatus,PrimaryCompletionDate,Phase"
        }
        r = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        if not r.ok:
            return []

        data = r.json()
        trials = []
        now = datetime.now(timezone.utc)
        for study in data.get("studies", []):
            proto = study.get("protocolSection", {})
            id_mod = proto.get("identificationModule", {})
            status_mod = proto.get("statusModule", {})
            design_mod = proto.get("designModule", {})

            completion_str = status_mod.get("primaryCompletionDateStruct", {}).get("date", "")
            catalyst_imminent = False
            days_to_completion = None
            if completion_str:
                try:
                    completion = datetime.strptime(completion_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    days_to_completion = (completion - now).days
                    catalyst_imminent = 0 <= days_to_completion <= 60
                except Exception:
                    pass

            trials.append({
                "nct_id": id_mod.get("nctId", ""),
                "title": id_mod.get("briefTitle", ""),
                "status": status_mod.get("overallStatus", ""),
                "completion_date": completion_str,
                "days_to_completion": days_to_completion,
                "catalyst_imminent": catalyst_imminent,
                "phase": design_mod.get("phases", [""])[0] if design_mod.get("phases") else ""
            })
        return trials
    except Exception:
        return []


def get_fda_calendar() -> list:
    """Get upcoming FDA PDUFA dates. Returns empty list on any failure."""
    try:
        # FDA drug review schedule via FDA API
        url = "https://api.fda.gov/drug/drugsfda.json"
        params = {
            "search": "submissions.submission_type:ORIGINAL AND submissions.submission_status:AP",
            "limit": 10,
            "sort": "submissions.submission_status_date:desc"
        }
        r = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        if not r.ok:
            return []
        results = r.json().get("results", [])
        events = []
        for drug in results[:5]:
            name = drug.get("brand_name", [""])[0] if drug.get("brand_name") else ""
            sponsor = drug.get("sponsor_name", "")
            events.append({
                "drug": name,
                "sponsor": sponsor,
                "type": "FDA_APPROVAL",
                "days_until": None  # PDUFA future dates require different endpoint
            })
        return events
    except Exception:
        return []


def get_catalyst_data(ticker: str, company: Optional[str] = None) -> dict:
    """
    Aggregate catalyst data for a ticker.
    company: company name for ClinicalTrials search (defaults to ticker)
    """
    search_name = company or ticker
    trials = get_clinical_trials(search_name)
    fda_events = get_fda_calendar()

    has_near_term = any(t.get("catalyst_imminent") for t in trials)
    imminent_trials = [t for t in trials if t.get("catalyst_imminent")]
    min_days = min((t["days_to_completion"] for t in imminent_trials if t.get("days_to_completion") is not None), default=None)

    return {
        "clinical_trials": trials,
        "fda_events": fda_events,
        "has_near_term_catalyst": has_near_term,
        "imminent_count": len(imminent_trials),
        "min_days_to_catalyst": min_days
    }
