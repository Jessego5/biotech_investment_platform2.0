"""
This file fetches the wider trial registry: industry-sponsored interventional
studies from every company, not only the ones in our universe. It answers the
question the company-by-company view cannot, which is who else is developing for
an indication and when their readouts are due.

It writes to registry_trials, deliberately not to trials. That table holds
studies led by a company we track and every pipeline count and signal is computed
from it, so a competitor's Phase 3 landing in it would silently become part of
somebody's own pipeline.
"""

from .data_sources import CT_BASE, _get_with_retry

# industry-sponsored interventional studies. the rest of the registry is
# academic, observational or government work: real research, but nothing with a
# company behind it to compare against.
REGISTRY_FILTER = ("AREA[LeadSponsorClass]INDUSTRY AND "
                   "AREA[StudyType]INTERVENTIONAL")

# the API's maximum, so the whole corpus is about 113 requests rather than 1,130
PAGE_SIZE = 1000


def _date(struct):
    """
    A date and whether it happened. The registry marks a date ACTUAL or
    ESTIMATED, and the difference matters: an estimated completion is when a
    readout is expected, an actual one is when it arrived. Treating a forecast as
    history would invent the thing this whole project exists to avoid.
    """
    if not struct:
        return None, None
    return struct.get("date"), struct.get("type")


def parse_registry_study(study):
    """Flatten one study into the fields a competitive question needs."""
    ps = study.get("protocolSection", {})
    idm = ps.get("identificationModule", {})
    status = ps.get("statusModule", {})
    design = ps.get("designModule", {})
    sponsor = ps.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})

    start, start_type = _date(status.get("startDateStruct"))
    completion, completion_type = _date(status.get("primaryCompletionDateStruct"))
    enrollment = design.get("enrollmentInfo") or {}

    return {
        "nct_id": idm.get("nctId"),
        "sponsor": sponsor.get("name"),
        "sponsor_class": sponsor.get("class"),
        # joined the same way the company trials do it, so a phase string means
        # the same thing in both tables
        "phase": ", ".join(design.get("phases") or []) or "N/A",
        "status": status.get("overallStatus"),
        "conditions": "; ".join(ps.get("conditionsModule", {}).get("conditions") or []),
        "start_date": start,
        "start_date_type": start_type,
        "completion_date": completion,
        "completion_date_type": completion_type,
        "enrollment": enrollment.get("count"),
        "enrollment_type": enrollment.get("type"),
    }


def fetch_registry_page(page_token=None, page_size=PAGE_SIZE):
    """One page of the filtered registry, with the token for the next."""
    params = {"filter.advanced": REGISTRY_FILTER, "pageSize": page_size,
              "countTotal": "true"}
    if page_token:
        params["pageToken"] = page_token
    # a page is several megabytes and the whole corpus is a hundred of them, so a
    # dropped connection partway through should cost one page, not the run
    resp = _get_with_retry(CT_BASE, params=params, timeout=120)
    resp.raise_for_status()
    payload = resp.json()
    return (payload.get("studies", []), payload.get("nextPageToken"),
            payload.get("totalCount"))
