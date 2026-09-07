"""
This fetches the real data for each company, the clinical trials from
ClinicalTrials.gov and the financials from SEC EDGAR. It only works for public
companies, since those are the ones with real filings. Every SEC request goes
through one rate limiter shared across threads and retries on a 429, because the
limit is per requester and not per thread. Imported by ingest.py and by main.py's
live fallback, and it needs SEC_USER_AGENT set to a real contact address.
"""

import json
import os
import re
from functools import lru_cache
import unicodedata
import threading
import time
from datetime import date

import requests

# load backend/.env so SEC_USER_AGENT is picked up even when a script imports this
# directly, not just through the API
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

# SEC wants automated requests to identify themselves with a real contact email.
# set SEC_USER_AGENT in your .env (see .env.example); the default is a placeholder.
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "biotech-agent your-real-email@example.com")

# SEC allows at most about 10 requests per second. when ingestion runs several
# companies in parallel, that ceiling is shared across all the threads, so gate
# every SEC request through one rate limiter (about 0.12s apart, roughly 8 per
# second) and retry when we get a 429.
_sec_lock = threading.Lock()
_sec_last = [0.0]
# about 6 to 7 requests per second, very under SEC's 10 per second cap
_SEC_MIN_INTERVAL = 0.15


# how many times to retry a request that failed at the network level, and the
# first backoff in seconds; the wait doubles each attempt.
RETRY_ATTEMPTS = 4
RETRY_BACKOFF = 1.0


def _get_with_retry(url, params=None, headers=None, timeout=30):
    """
    GET a URL, retrying when the connection itself fails. A bad HTTP response is
    a real answer and is returned as-is, since repeating it returns the same thing.

    Without this a single timeout silently costs a whole company: a full ingest of
    480 lost four that way, Pfizer among them, and every one succeeded on retry.
    """
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return requests.get(url, params=params, headers=headers,
                                timeout=timeout)
        except requests.exceptions.RequestException:
            # out of attempts, so let the caller see the real error
            if attempt == RETRY_ATTEMPTS:
                raise
            time.sleep(RETRY_BACKOFF * 2 ** (attempt - 1))


def _sec_get(url, params=None):
    """
    GET an SEC URL, rate-limited across threads, retrying on 429 and on the
    connection failing. The two are different problems: a 429 means we asked too
    fast and should pace ourselves, a dropped connection means the request never
    landed and should simply be repeated.
    """
    # try up to four times so a throttle doesn't kill the request outright
    for attempt in range(4):
        # only one thread at a time checks the clock and updates the last-call time
        with _sec_lock:
            # figure out how long we still need to wait before the next allowed call
            wait = _SEC_MIN_INTERVAL - (time.monotonic() - _sec_last[0])
            if wait > 0:
                time.sleep(wait)
            # record the time of this call so the next one paces off it
            _sec_last[0] = time.monotonic()
        r = _get_with_retry(url, params=params,
                            headers={"User-Agent": SEC_USER_AGENT}, timeout=30)
        # a 429 means we got throttled, so back off a bit and try again
        if r.status_code == 429:
            # wait longer on each successive attempt
            time.sleep(1.0 * (attempt + 1))
            continue
        return r
    return r

# corporate suffixes to ignore when matching a company name to a trial sponsor.
# ie same company may have slightly different names (suffixes mostly)
# this lets "FATE THERAPEUTICS INC" (the SEC legal name) match a lead sponsor of
# "Fate Therapeutics" without the "INC" throwing off the substring check.
# the corporate form is not part of what a company is called. The non-English
# ones matter as much as "inc": the registry writes uniQure as "UniQure Biopharma
# B.V." and Pharvaris as "Pharvaris Netherlands B.V.", and with "bv" left in
# place both sit two words from their filing name rather than one, which is
# outside what the identity rule will accept.
#
# "kgaa" is deliberately absent. Stripping it turns "Merck KGaA, Darmstadt,
# Germany" into "merck", which is a different company on another continent from
# "Merck & Co., Inc." and exactly the collision the rule exists to prevent.
_SUFFIXES = {"inc", "incorporated", "corp", "corporation", "co", "company",
             "llc", "ltd", "limited", "plc", "ag", "sa", "nv", "holdings",
             # singular as well as plural. Scholar Rock files as "Scholar Rock
             # Holding Corp" and runs its trials as "Scholar Rock, Inc.", and
             # with only the plural listed the two came out a word apart.
             "holding",
             "gmbh", "bv", "pty", "ab", "oy", "srl", "spa", "aps", "sas"}


# the state a company incorporated in, which EDGAR appends to some names:
# "HERON THERAPEUTICS, INC. /DE/". It is not part of what anyone calls them, and
# leaving it in makes the search term "HERON THERAPEUTICS INC DE", which matches
# nothing at all.
# the closing slash is optional: EDGAR writes both "INC. /DE/" and "Inc./NV".
# a space may follow the slash too, as in "VERTEX PHARMACEUTICALS INC / MA".
# without that allowance the marker survived, "inc" stopped being the trailing
# word so the suffix strip left it in place, and the name came out four words
# long as "vertex pharmaceuticals inc ma". sponsor_names_for then rejected the
# registry's own "Vertex Pharmaceuticals Incorporated" for being two words away,
# the search fell back to asking for "VERTEX PHARMACEUTICALS INC MA", found
# nothing, and a company with no trials is dropped from the universe outright.
# two letters are required after the slash, so the Danish "A/S" is left alone
# EDGAR writes the separator both ways: "Inc./NV" and "Viridian Therapeutics,
# Inc.\DE". With only the forward slash matched, the backslash form survived and
# "DE" joined the name, so the company came out as "viridian therapeutics incde"
# and matched nothing at all.
_STATE_MARKER = re.compile(r"[/\\]\s*[A-Za-z]{2}[/\\]?\s*$")


def _core_name(name):
    """Lowercase a company name and drop punctuation + trailing corp suffixes."""
    name = _STATE_MARKER.sub("", (name or "").strip())
    # lowercase each word and strip out everything that isn't a letter or number
    words = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in name.split()]
    # drop any words that came out empty after stripping
    words = [w for w in words if w]
    # peel off trailing corporate suffixes like "inc" or "corp"
    while words and words[-1] in _SUFFIXES:
        words.pop()
    return " ".join(words)


def _search_term(name):
    """
    Clean a company name into a good ClinicalTrials.gov sponsor query. Keeps the
    real words (and their casing) but drops punctuation and trailing corporate
    suffixes. The ", Inc." on a SEC legal name makes the sponsor search miss
    (e.g. "Fate Therapeutics, Inc." finds nothing, "Fate Therapeutics" finds it).
    """
    # the incorporation marker goes first, exactly as in _core_name. It was
    # fixed there and not here, so the comparison name was clean while the name
    # actually sent to the registry still asked for "VERTEX PHARMACEUTICALS INC
    # MA", and a search that returns nothing is a company with an empty
    # pipeline, which reads as a fact about the company.
    name = _STATE_MARKER.sub("", (name or "").strip())
    # strip punctuation from each word but keep the original casing this time
    words = [re.sub(r"[^A-Za-z0-9]", "", w) for w in name.split()]
    # drop any words that came out empty
    words = [w for w in words if w]
    # peel off trailing corporate suffixes
    while words and words[-1].lower() in _SUFFIXES:
        words.pop()
    # fall back to the original name if stripping left us with nothing
    return " ".join(words) or name

# What to search the registry for when the filing name will not find it. This is
# for the cases no spelling rule can reach, not for near misses: a company that
# renamed itself is not a variant of its old name. GSK plc was GlaxoSmithKline
# until 2022 and the registry still runs 3,223 studies under the old name, which
# shares not one word with the new one.
SPONSOR_OVERRIDES = {
    "MRNA": "ModernaTX",
    "SDGR": "Schrödinger",
    "GLAXF": "GlaxoSmithKline",
}

CT_BASE = "https://clinicaltrials.gov/api/v2/studies"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
# everything SEC holds for one company, in one response. asking per tag instead
# cannot tell "this company doesn't report that" from "I guessed the wrong name",
# because both are a 404.
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# multiple candidate tags, since companies report under different XBRL tags.
# 10x Genomics, for example, only reports the "excluding acquired IPR&D" variant.
# a tag may name its taxonomy as "dei:Thing"; anything unqualified is us-gaap,
# which is where nearly all financial reporting lives.
# each list ends with its ifrs-full equivalents, for foreign private issuers.
# they file a 20-F and report under IFRS, so a us-gaap-only lookup reads them as
# having no financials at all: BioNTech has no us-gaap R&D tag whatsoever, and
# GlaxoSmithKline the same, despite both filing complete annual accounts.
# the entries themselves are shaped identically, so only the names differ.
RD_TAGS = [
    "ResearchAndDevelopmentExpense",
    "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    "ifrs-full:ResearchAndDevelopmentExpense",
]
CASH_TAGS = [
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    "ifrs-full:CashAndCashEquivalents",
]
# cash actually consumed by running the business. this is the real burn, and the
# reason it beats R&D expense is that R&D isn't a cash figure at all: it excludes
# G&A and includes non-cash charges like stock compensation.
OPERATING_CASH_FLOW_TAGS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    "ifrs-full:CashFlowsFromUsedInOperatingActivities",
]
NET_INCOME_TAGS = ["NetIncomeLoss", "ifrs-full:ProfitLoss"]
# whether a company sells anything yet, which splits the universe into two kinds
# of business that aren't comparable on any other measure.
REVENUE_TAGS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "ifrs-full:RevenueFromContractsWithCustomers",
]
# the cover page of every filing carries this, which makes it the most reliably
# present share count. the us-gaap one is a fallback for filers that omit it.
SHARES_TAGS = [
    "dei:EntityCommonStockSharesOutstanding",
    "CommonStockSharesOutstanding",
    "ifrs-full:NumberOfSharesOutstanding",
]
# money held in securities rather than as cash. biotechs park most of their
# funding here, so cash alone badly understates what they have to spend:
# CRISPR Therapeutics reports $291m of cash against $2.06b of securities.
SECURITIES_TAGS = [
    "AvailableForSaleSecuritiesDebtSecurities",
    "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    "AvailableForSaleSecurities",
    "MarketableSecuritiesCurrent",
    "ShortTermInvestments",
    # us-gaap renamed these elements, and the AvailableForSale* names above are
    # the deprecated spelling. A company that has moved on still reports the
    # figure, under a name this list did not know, so the newest balance found
    # came from whichever old filing last used the old name. Geron's securities
    # then read as $422m at 2024-12-31 while it was reporting $238m at
    # 2026-06-30, and being older than the cash figure they were dropped from
    # the runway entirely: seven months of cash for a company holding thirty-two.
    # The current portion comes first, so a tie on the same balance date takes
    # the money available within the year rather than the larger total.
    "DebtSecuritiesAvailableForSaleExcludingAccruedInterestCurrent",
    "DebtSecuritiesAvailableForSaleExcludingAccruedInterest",
    "OtherShortTermInvestments",
]
# what has to be paid back. runway says nothing about this, so it is reported
# beside the runway rather than folded into it.
DEBT_TAGS = [
    "LongTermDebt",
    "ConvertibleLongTermNotesPayable",
    "ConvertibleNotesPayable",
]


# - ClinicalTrials.gov
def _trial_text(ps):
    """
    Build the free-text blob we embed for semantic search: brief summary,
    conditions, interventions, and eligibility. These are the fields the
    structured columns can't answer over (mechanisms, mutations, therapies).
    Capped in length to keep embeddings focused and cheap.
    """
    parts = []
    # grab the brief summary and add it if it exists
    summary = ps.get("descriptionModule", {}).get("briefSummary", "")
    if summary:
        parts.append(summary)
    # add the list of conditions the trial studies
    conditions = ps.get("conditionsModule", {}).get("conditions", [])
    if conditions:
        parts.append("Conditions: " + ", ".join(conditions))
    # pull out the names of the interventions and add the ones that have a name
    interventions = ps.get("armsInterventionsModule", {}).get("interventions", [])
    names = [i.get("name", "") for i in interventions if i.get("name")]
    if names:
        parts.append("Interventions: " + ", ".join(names))
    # add the eligibility criteria text
    eligibility = ps.get("eligibilityModule", {}).get("eligibilityCriteria", "")
    if eligibility:
        parts.append(eligibility)
    # join it all together and cap the length to keep the embedding focused and cheap
    return "\n".join(parts)[:2000]


# the API returns results a page at a time. this is how many trials we are
# willing to pull for one sponsor before stopping: high enough that every company
# in the universe comes back whole, low enough that a handful of giants (Pfizer
# registers over six thousand studies) can't make one company dominate a run.
MAX_STUDIES_PER_SPONSOR = 1000


def _fold(text):
    """
    Lowercase, drop accents, and strip punctuation the same way _core_name does.

    Word by word, because the two have to agree: replacing punctuation with a
    space turns "A/S" into "a s" while _core_name turns it into "as", and
    Ascendis Pharma A/S then fails to match its own name in the registry.
    """
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    words = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in text.split()]
    return " ".join(w for w in words if w)


def _registry_names():
    """Every sponsor name the registry table holds, or an empty set."""
    if _registry_names.cache is None:
        try:
            from .database import SessionLocal
            from .models import RegistryTrial
            db = SessionLocal()
            try:
                _registry_names.cache = {n for (n,) in db.query(RegistryTrial.sponsor)
                                         .filter(RegistryTrial.sponsor.isnot(None))
                                         .distinct()}
            finally:
                db.close()
        except Exception:
            _registry_names.cache = set()
    return _registry_names.cache


_registry_names.cache = None


@lru_cache(maxsize=4096)
def sponsor_names_for(company_name):
    """
    What this company is actually called in the registry.

    Cached, because it walks all 30,000 distinct registry sponsor names and
    _leads calls it for every study it judges. Uncached it is the reason a scan
    of the universe against the registry does not finish; the answer for a given
    company name cannot change within a run, so the walk is paid once.

    A company does not register trials under the name it files under. Abbott
    Laboratories appears as "Abbott", "Abbott Medical Devices" and "Abbott
    Nutrition"; Genmab A/S as "Genmab"; argenx SE as "argenx". The search matches
    whole terms, so asking for the filing name returns nothing at all and the
    company ingests an empty pipeline while plainly running trials.

    Returns the registry spellings, longest first so the most specific is tried
    before the barest, and an empty list when the registry has nothing to say.
    """
    core = _fold(_core_name(company_name))
    if len(core) < 4:
        return []
    words = len(core.split())
    hits = []
    for name in _registry_names():
        folded = _fold(name)
        mine, theirs = core.split(), folded.split()
        # one name starting the other, compared word by word. as characters
        # "Merckle GmbH" starts with "Merck", and Merckle is a different company
        short, long_ = sorted((mine, theirs), key=len)
        if long_[:len(short)] != short:
            continue
        # and no more than a word apart, because a prefix alone is not identity.
        # "Merck" starts "Merck Healthcare KGaA, Darmstadt, Germany", which is a
        # different company on another continent, and one of Pfizer's sponsor
        # names is the sentence "Pfizer's Upjohn has merged with Mylan to form
        # Viatris Inc."
        if abs(len(theirs) - words) > 1:
            continue
        hits.append(name)
    # the closest name first: an exact spelling, then the fewest words
    return sorted(hits, key=lambda n: (_fold(n) != core, len(_fold(n).split()), len(n)))


def fetch_studies_by_nct(nct_ids, page_size=100):
    """
    Fetch specific studies by their NCT id, in the shape fetch_trials_raw returns.

    The sponsor search is a text search and it is not always reachable. Asking
    it for "Bio-Path Holdings, Inc." returns two studies belonging to LS
    BioPath, and asking for "Schrödinger, Inc." returns none at all, while the
    registry plainly holds studies under both names. When we already know which
    studies a company ran, and registry_trials does know, by id, searching for
    them by name is guessing at something we have.
    """
    studies = []
    ids = list(nct_ids)
    for start in range(0, len(ids), page_size):
        batch = ids[start:start + page_size]
        r = _sec_ct_get(CT_BASE, {
            "filter.ids": ",".join(batch),
            "pageSize": page_size,
            "format": "json",
        })
        if r.status_code != 200:
            continue
        studies.extend(r.json().get("studies", []))
    return {"studies": studies, "totalCount": len(studies), "truncated": False}


def _sec_ct_get(url, params):
    """A plain registry GET with the same retry policy as everything else."""
    return _get_with_retry(url, params=params, timeout=30)


def fetch_trials_raw(sponsor_name, page_size=100,
                     max_studies=MAX_STUDIES_PER_SPONSOR):
    """
    The network half: follow the pages and return what ClinicalTrials.gov said,
    keeping the API's own shape plus totalCount (what the sponsor really has) and
    truncated (whether we stopped early). Kept separate from parsing so the
    payload can be archived exactly as fetched.

    The search returns one page at a time. Asking once and keeping the first page
    silently truncated every large sponsor: Pfizer registers 6,061 studies and
    only 100 were stored, and a wrong trial count feeds a wrong pipeline label.
    """
    # search by what the registry calls this company, not what it files under.
    # the API matches whole terms, so "ABBOTT LABORATORIES" finds three studies
    # and none of them Abbott's, while "Abbott" finds 293
    # a registry name is used exactly as it is. it is already the string the API
    # indexes, so cleaning it can only break it: _search_term turns "Ascendis
    # Pharma A/S" into "Ascendis Pharma AS", which matches nothing, while the
    # name as written matches all 31
    known = sponsor_names_for(sponsor_name)
    search_term = known[0] if known else _search_term(sponsor_name)
    studies = []
    total = None
    page_token = None

    while True:
        # search ClinicalTrials.gov by sponsor, cleaning the name so ", Inc." doesn't blank it
        params = {
            "query.spons": search_term,
            "pageSize": page_size,
            "countTotal": "true",
        }
        # every page after the first is requested with the previous page's token
        if page_token:
            params["pageToken"] = page_token
        # retry the page, not the company. a large sponsor takes ten requests, so
        # it has ten chances to hit a timeout, and losing the whole company to one
        # of them is how the biggest sponsors became the most likely to go missing.
        resp = _get_with_retry(CT_BASE, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()

        studies.extend(payload.get("studies", []))
        # the total is only reported on the first page, so keep the first one seen
        if total is None:
            total = payload.get("totalCount")

        page_token = payload.get("nextPageToken")
        # stop at the last page, or once this sponsor has had its share of the run
        if not page_token or len(studies) >= max_studies:
            break

    # a page is fetched whole, so the last one usually overshoots the ceiling.
    # trim, so max_studies is an actual limit rather than a rough one.
    studies = studies[:max_studies]

    return {
        "studies": studies,
        "totalCount": total if total is not None else len(studies),
        # true only when the sponsor really has more than we fetched, so a company
        # that happens to land exactly on the limit isn't wrongly flagged
        "truncated": bool(total is not None and len(studies) < total),
    }


def _squash(name):
    """The core name with every gap removed, so "CEL-SCI" and "CEL SCI" agree."""
    return _core_name(name).replace(" ", "")


_alias_index_cache = None
def _alias_index():
    """
    Normalised company name -> the normalised names of its subsidiaries.

    Built from the alias table, which is mostly Exhibit 21 to the 10-K: the
    company's own annual statement of what it owns. Empty when that table has
    not been built, which makes the sponsor test stricter rather than broken.

    Only the most recent Exhibit 21 for each company counts, because ownership
    is as of today and Exhibit 21 is a statement about one year. Illumina listed
    GRAIL through 2024 and spun it off; its 2026 exhibit does not mention it,
    and GRAIL files its own 10-K here under GRAL. Reading every year at once
    gave Illumina eight trials that belong to a company it no longer owns, and
    counted them twice across the universe. 264 companies have an alias that has
    since dropped out of their own latest filing.
    """
    global _alias_index_cache
    if _alias_index_cache is None:
        index = {}
        try:
            from sqlalchemy import func
            from .database import SessionLocal
            from .models import Alias, Company
            db = SessionLocal()
            try:
                newest = (db.query(Alias.company_ticker.label("ticker"),
                                   func.max(Alias.fiscal_year).label("year"))
                            .group_by(Alias.company_ticker).subquery())
                rows = (db.query(Company.name, Alias.alias_key)
                          .join(Alias, Alias.company_ticker == Company.ticker)
                          .join(newest,
                                (Alias.company_ticker == newest.c.ticker)
                                & (Alias.fiscal_year == newest.c.year))
                          .all())
            finally:
                db.close()
            for name, key in rows:
                if name and key:
                    index.setdefault(_norm(name), set()).add(key)
        except Exception:
            index = {}
        _alias_index_cache = index
    return _alias_index_cache


# Words that say what a company does rather than which company it is. A name
# that differs only by these is the same company under a fuller or shorter form
# of its own name; a name that differs by anything else may not be.
#
# This is an allowlist and not a blocklist on purpose. "Merck" against "Merck
# KGaA" and "Nova" against "Nova Scotia" are the two matches that did real
# damage here, and what makes them wrong is not that KGaA and Scotia are known
# to be dangerous, it is that they are not known to be harmless. Anything
# unrecognised stays rejected.
_DESCRIPTORS = {
    "pharma", "pharmaceutical", "pharmaceuticals", "therapeutic", "therapeutics",
    "science", "sciences", "bioscience", "biosciences", "biopharma",
    "biopharmaceutical", "biopharmaceuticals", "biotechnology", "biotechnologies",
    "biotech", "biotherapeutics", "therapeutix", "bio", "biologics",
    "laboratory", "laboratories", "labs", "medical",
    "medicine", "medicines", "health", "healthcare", "oncology", "diagnostics",
    "technology", "technologies", "research", "operations", "innovations",
    "treasury", "group", "international", "global", "worldwide",
}


# A sponsor trading under another name states both. "TheRas, Inc., d/b/a BBOT
# (BridgeBio Oncology Therapeutics)" is the registered entity, the trading name
# and the full name in one string, and only the last of the three is what the
# company files under.
_TRADES_AS = re.compile(r"\b(?:d/?b/?a|doing\s+business\s+as|formerly)\b(.*)",
                        re.I)


def _traded_names(candidate):
    """The names a sponsor says it also goes by: after "d/b/a", and in brackets."""
    names = []
    m = _TRADES_AS.search(candidate)
    if m:
        names.append(m.group(1))
    names.extend(re.findall(r"\(([^)]{4,})\)", candidate))
    # a bracket inside the d/b/a tail is one name, not two joined
    return [n.strip(" .,;-()") for n in names if n.strip(" .,;-()")]


def _distinctive(normalised):
    """
    Whether a company name is particular enough that another name starting with
    all of it is the same company.

    Two words, or one of at least six letters. "Nova" took 355 studies from a
    Canadian health authority and a Portuguese university, and "Merck" took 61
    from a German company of the same name on another continent; they are four
    and five letters, and so is every name that has caused trouble here.

    Six rather than eight because eight was guesswork and six is measured. The
    band between them is 30 sponsor pairs across the whole registry, Stryker's
    divisions, Incyte Biosciences, Grifols Biologicals, uniQure Biopharma,
    Arvinas Androgen Receptor, Immutep Australia, and every one of them is the
    company it was matched to.
    """
    words = normalised.split()
    return len(words) >= 2 or (len(words) == 1 and len(words[0]) >= 6)


def _descriptor_gap(mine, theirs):
    """
    Whether two normalised names differ only by descriptor words.

    "EyePoint" against "EyePoint Pharmaceuticals" and "Capricor Therapeutics"
    against "Capricor" are the same company writing its name at two lengths.
    "Merck" against "Merck KGaA" is not, and the difference is that "KGaA" is
    not in the list above.
    """
    short, long_ = sorted((mine, theirs), key=len)
    if not short or long_[:len(short)] != short:
        return False
    extra = long_[len(short):]
    return bool(extra) and all(w in _DESCRIPTORS for w in extra)


def _leads(sponsor_name, lead):
    """
    Whether this trial is led by the company we asked about.

    This used to ask whether the filing name appeared anywhere inside the lead
    sponsor's name, and containment is not identity. "Merck" sits inside "Merck
    KGaA, Darmstadt, Germany", which is a different company on another
    continent, and it took 61 of its trials into Merck & Co's pipeline. "Nova"
    sits inside "Nova Scotia Health Authority", and Nova Ltd, which makes
    semiconductor metrology equipment, ended up holding 355 studies run by a
    Canadian health service, an American university and a Portuguese one.

    So a lead sponsor now has to be the company by one of four routes, each of
    which is an identity rather than a resemblance:

    1. the same name, compared word by word
    2. a sponsor that names its parent in plain text: "Cubist Pharmaceuticals
       LLC, a subsidiary of Merck & Co., Inc."
    3. a spelling the registry itself uses for this company, which is what
       reaches "Abbott" from "Abbott Laboratories"
    4. a subsidiary the company listed in its own Exhibit 21
    5. the same name written at a different length, where everything that
       differs is a word describing what the company does
    """
    if identity(sponsor_name, lead) == "exact":
        return True

    named = parent_named_in(lead)
    if named and identity(sponsor_name, named) == "exact":
        return True

    # a sponsor stating the name it trades under, which is the name the company
    # files with the SEC: BridgeBio Oncology Therapeutics registers its studies
    # as "TheRas, Inc., d/b/a BBOT (BridgeBio Oncology Therapeutics)"
    if any(identity(sponsor_name, alt) == "exact" for alt in _traded_names(lead)):
        return True

    folded = _fold(lead)
    if any(_fold(name) == folded for name in sponsor_names_for(sponsor_name)):
        return True

    if _norm(lead) in _alias_index().get(_norm(sponsor_name), ()):
        return True

    # 5. a sponsor whose name begins with the whole of the company's own,
    #    where the company's name is distinctive enough to carry it. "Medtronic
    #    France SAS" and "Matinas BioPharma Nanotechnologies" are the parent's
    #    beyond doubt, and they need no exhibit to say so: what Exhibit 21 is
    #    for is the subsidiary you cannot recognise by name, which is also the
    #    one where as-of-today ownership matters. A subsidiary can drop off an
    #    exhibit for being too small to report rather than for being sold.
    #
    #    The threshold is what keeps this away from "Nova" and "Merck". Four
    #    and five letters collide with anything, and both did.
    if _distinctive(_norm(sponsor_name)):
        mine, theirs = _norm(sponsor_name).split(), _norm(lead).split()
        if len(theirs) > len(mine) and theirs[:len(mine)] == mine:
            return True

    # 6. the same name at a different length, where the difference is only what
    #    the company does. Exhibit 21 is the better mechanism and does not
    #    reach these: Telix, QIAGEN and Capricor have no alias rows at all, and
    #    EyePoint's 38 list its subsidiaries but not the name it runs trials
    #    under. Without this the registry holds their trials and the app shows
    #    an empty pipeline, which reads as a fact about the company.
    return _descriptor_gap(_norm(sponsor_name).split(), _norm(lead).split())



def _norm(name):
    """
    A name reduced to comparable words: accents folded away first, then
    punctuation and trailing corporate suffixes.

    The order matters twice over. _core_name strips anything that is not a letter
    or digit from each word, so on its own it turns the registry's "Daré
    Bioscience" into "dar bioscience" while EDGAR's "Dare Bioscience" becomes
    "dare bioscience", and the company matches nothing. _fold normalises the
    accent away first.

    But folding cannot come first either, because it flattens the slashes in
    "HERON THERAPEUTICS, INC. /DE/" to "de" before the state marker can be
    recognised as one. That silently undid the earlier fix and cost Heron,
    Windtree and Dianthus their pipelines a second time. So the marker goes
    first, then the fold, then the suffixes.
    """
    name = _STATE_MARKER.sub("", (name or "").strip())
    return _core_name(_fold(name))


def _squashed(name):
    """_norm with every gap removed, so "CEL-SCI" and "CEL SCI" agree."""
    return _norm(name).replace(" ", "")


# The registry often names the parent in plain text rather than leaving it to be
# guessed: "K-Group Alpha, Inc., a wholly owned subsidiary of Zentalis
# Pharmaceuticals, Inc.", "Stiefel, a GSK Company", "Cubist Pharmaceuticals LLC,
# a subsidiary of Merck & Co., Inc. (Rahway, New Jersey USA)". Reading it is
# better than any string-distance rule, because it is the registry stating the
# relationship rather than us inferring one from a spelling.
_PARENT = re.compile(
    r"(?:wholly[-\s]owned\s+)?subsidiar(?:y|ies)\s+of\s+(?P<sub>.+)$"
    r"|[,\-\u2013]\s*an?\s+(?P<brand>[^,]+?)\s+company\s*$",
    re.I)


def parent_named_in(sponsor):
    """The parent a sponsor name spells out, or None."""
    m = _PARENT.search(sponsor or "")
    if not m:
        return None
    parent = m.group("sub") or m.group("brand") or ""
    # "Merck & Co., Inc. (Rahway, New Jersey USA)" carries an address
    parent = re.sub(r"\(.*?\)", " ", parent).strip(" .,;-")
    return parent or None


def identity(filing_name, candidate, authoritative=False):
    """
    How confidently `candidate` names the same company as `filing_name`:
    "exact", "near", or None.

    This is deliberately stricter than what the SIC sweep needed. Inside a dozen
    medical codes a loose match is usually right; over eight thousand filers it
    is the dominant source of error. Matching the first word as a substring, the
    rule this replaces, admitted Tesla, Boeing, Shell, Vale and Rocky Mountain
    Chocolate Factory, at a rate of 5.7% of a random sample.
    """
    mine = _norm(filing_name).split()
    theirs = _norm(candidate).split()
    if not mine or not theirs:
        return None
    if mine == theirs:
        # a short name is not an identity even when it matches exactly. "ATI"
        # is ATI Inc, which makes steel pipe, and it is also ATI Holdings, which
        # runs physical therapy clinics. Three letters collide with anything, so
        # a short name goes to the corroborated tier rather than standing alone.
        return "exact" if len("".join(mine)) >= 5 else "near"
    # the registry naming its own parent, which is stronger than any spelling
    # comparison but weaker than identity, because the name it states can itself
    # be ambiguous: "Alpine Immune Sciences, a Vertex Company" means Vertex
    # Pharmaceuticals, and matched Vertex, Inc., which sells tax software. So
    # this is corroborated by the filing code like any other near match.
    named = parent_named_in(candidate)
    if named and _norm(named).split() == mine:
        return "near"
    # the same name with the gaps moved. EDGAR files Novo Nordisk as "NOVO
    # NORDISK A S" and the registry writes "Novo Nordisk A/S", which come out
    # three words against four; Bristol-Myers is the same story with a hyphen.
    # This compares the whole name with every gap removed, so it is an equality
    # and not a containment: "nova" sits inside "novascotiahealthauthority",
    # and containment is what put 260 Nova Scotia Health Authority studies in a
    # semiconductor company's pipeline.
    if (_squashed(filing_name) and _squashed(filing_name) == _squashed(candidate)):
        return "exact" if len(_squashed(filing_name)) >= 5 else "near"
    # too short to be an identity on its own: two or three letters collide with
    # anything
    if len("".join(mine)) < 5:
        return None
    # one name starting the other, compared word by word. as characters
    # "Merckle GmbH" starts with "Merck", and Merckle is a different company
    short, long_ = sorted((mine, theirs), key=len)
    if long_[:len(short)] != short:
        return None
    # and no more than a word apart, because a prefix alone is not identity.
    # A recorded alias is exempt: it is a hand-made judgement that these are one
    # company, so the registry piling extra words on top of it does not weaken
    # the claim. "TheRas" leads "TheRas, Inc., d/b/a BBOT (BridgeBio Oncology
    # Therapeutics)", which is seven words further on and still the same company.
    if not authoritative and abs(len(theirs) - len(mine)) > 1:
        return None
    return "exact" if authoritative else "near"


def _date_struct(struct):
    """
    A date and whether it happened.

    The registry marks a date ACTUAL or ESTIMATED, and the difference is the
    whole point: an estimated completion is when a readout is expected, an actual
    one is when it arrived. Treating a forecast as history would manufacture
    exactly the kind of fact this project exists not to manufacture.
    """
    if not struct:
        return None, None
    return struct.get("date"), struct.get("type")


def parse_trials(payload, sponsor_name):
    """
    The parsing half: flatten a ClinicalTrials.gov response into trial dicts,
    keeping only the trials whose lead sponsor actually matches (this is what
    avoids the Illumina-style over-matching where the search pulls in unrelated
    orgs). No network here, so it can be re-run over an archived snapshot.
    """
    studies = payload.get("studies", [])

    trials = []
    # loop through each study the search returned
    for s in studies:
        # dig into the nested modules that hold the fields we want
        ps = s.get("protocolSection", {})
        idm = ps.get("identificationModule", {})
        stm = ps.get("statusModule", {})
        dsm = ps.get("designModule", {})
        spm = ps.get("sponsorCollaboratorsModule", {})
        lead = spm.get("leadSponsor", {}).get("name", "")

        # Lead or collaborator, and which one is recorded rather than flattened.
        #
        # An industry-funded trial run by a university or a cooperative group
        # lists the institution as lead and the company as a collaborator. It is
        # still the company's asset and its readout, so dropping it loses real
        # involvement, and loses it unevenly, penalising exactly the companies
        # that partner. But it is not a trial the company controls: it cannot set
        # the timeline and does not own the data. So the role is stored and
        # pipeline counts keep using lead alone.
        if _leads(sponsor_name, lead):
            role = "lead"
        elif any(_leads(sponsor_name, (c or {}).get("name", ""))
                 for c in spm.get("collaborators") or []):
            role = "collaborator"
        else:
            continue

        start, start_type = _date_struct(stm.get("startDateStruct"))
        done, done_type = _date_struct(stm.get("primaryCompletionDateStruct"))
        enrollment = dsm.get("enrollmentInfo") or {}
        design = dsm.get("designInfo") or {}

        # flatten the fields we care about into a simple trial dict
        trials.append({
            "nct_id": idm.get("nctId"),
            "title": idm.get("briefTitle"),
            "status": stm.get("overallStatus"),
            "phase": ", ".join(dsm.get("phases", []) or []) or "N/A",
            "lead_sponsor": lead,
            "role": role,
            # the free-text blob used later for semantic search
            "summary": _trial_text(ps),
            # what it treats, joined the same way the registry table does it so a
            # condition means the same thing in both
            "conditions": "; ".join(ps.get("conditionsModule", {})
                                      .get("conditions") or []) or None,
            # What the study is actually testing. The registry states this as
            # a structured list, and it was being folded into the embedding
            # text and then thrown away, which left the candidate a company is
            # developing recorded nowhere except inside a trial's title.
            # {name: [other names]} exactly as filed. See Trial.intervention_aliases.
            "intervention_aliases": json.dumps({
                i["name"].strip(): i["otherNames"]
                for i in (ps.get("armsInterventionsModule", {})
                            .get("interventions") or [])
                if i.get("name") and i.get("otherNames")
            }) or None,
            "interventions": "; ".join(
                i.get("name", "").strip()
                for i in (ps.get("armsInterventionsModule", {})
                            .get("interventions") or [])
                if i.get("name")) or None,
            "start_date": start,
            "start_date_type": start_type,
            "completion_date": done,
            "completion_date_type": done_type,
            "enrollment": enrollment.get("count"),
            "enrollment_type": enrollment.get("type"),
            # hasResults sits at the top of the study, not inside protocolSection
            "has_results": s.get("hasResults"),
            "allocation": design.get("allocation"),
            "masking": (design.get("maskingInfo") or {}).get("masking"),
        })
    return trials


def fetch_trials(sponsor_name, page_size=100):
    """Fetch and parse in one call, which is what most callers want."""
    return parse_trials(fetch_trials_raw(sponsor_name, page_size), sponsor_name)


def summarize_pipeline(trials):
    """
    Turn a trial list into pipeline signal: counts by phase and status.

    Counts the trials the company LEADS. A collaborator trial is real
    involvement but not a programme the company runs, it cannot set the
    timeline or own the data, and a large pharma partnering on academic studies
    would otherwise show a pipeline it does not control. The collaborator count
    is reported alongside rather than folded in, so nothing is hidden and
    nothing is double-counted.

    Rows written before the role was recorded have none, and are treated as
    lead, which is what they were filtered to at the time.
    """
    led = [t for t in trials if (t.get("role") or "lead") == "lead"]
    collaborating = len(trials) - len(led)
    by_phase, by_status = {}, {}
    # tally up how many trials fall under each phase and each status
    for t in led:
        by_phase[t["phase"]] = by_phase.get(t["phase"], 0) + 1
        by_status[t["status"]] = by_status.get(t["status"], 0) + 1
    # a trial counts as active if it is recruiting or otherwise still running
    active = sum(1 for t in led
                 if t["status"] in ("RECRUITING", "ACTIVE_NOT_RECRUITING",
                                     "ENROLLING_BY_INVITATION"))
    # terminated trials are the ones marked TERMINATED
    terminated = by_status.get("TERMINATED", 0)
    return {
        # the trials this company runs. assess_pipeline reads this, so it must
        # not include trials somebody else runs with the company alongside.
        "total_trials": len(led),
        "by_phase": by_phase,
        "by_status": by_status,
        "active_trials": active,
        "terminated_trials": terminated,
        # reported, never added in
        "collaborator_trials": collaborating,
    }


# - SEC EDGAR
_ticker_map = None
_name_map = None

def _load_ticker_map():
    global _ticker_map
    # only fetch and build the map once, then reuse it
    if _ticker_map is None:
        r = _sec_get(SEC_TICKERS)
        r.raise_for_status()
        # map each ticker to its 10-digit zero-padded CIK
        _ticker_map = {row["ticker"].upper(): f"{int(row['cik_str']):010d}"
                       for row in r.json().values()}
    return _ticker_map


def company_name(ticker):
    """
    Look up a company's name from SEC's ticker file. Used by the API's live
    fallback so we can analyze a ticker that isn't in our sourced universe yet.
    """
    global _name_map
    # build the ticker to name map once, then reuse it
    if _name_map is None:
        r = _sec_get(SEC_TICKERS)
        r.raise_for_status()
        _name_map = {row["ticker"].upper(): row["title"] for row in r.json().values()}
    return _name_map.get(ticker.upper())


# annual-report forms: US companies file a 10-K, foreign private issuers
# (like BioNTech) file a 20-F. accept both so foreign biotechs aren't blanked out.
ANNUAL_FORMS = ("10-K", "10-K/A", "20-F", "20-F/A")

# every form we'll take a balance-sheet figure from. quarterly reports included,
# because a balance is only useful if it is the most recent one.
REPORTED_FORMS = ANNUAL_FORMS + ("10-Q", "10-Q/A", "6-K", "6-K/A")


def _covers_a_year(start, end):
    """
    Whether a reported period is a full financial year.

    Annual filings restate shorter periods too, and a fiscal year isn't exactly
    365 days (companies with a 52/53-week year, or one that shifted its year end,
    run a few weeks over or under), so this allows a window rather than an exact
    length. A quarter can't reach it and two years can't stay under it.
    """
    if not start or not end:
        return False
    try:
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    # a malformed date is a reason to skip the entry, not to fail the whole fetch
    except ValueError:
        return False
    return 300 <= days <= 400


def fetch_company_facts(cik):
    """
    Everything SEC holds for one company, in one request, which is roughly 300
    tags for a typical biotech and makes each new metric free.

    This replaces asking per tag, and the reason is not speed. Companies report
    the same figure under different tag names, so a request for a name a company
    doesn't use returns 404 whether or not it has the thing. Reading that as "no
    debt" is how you report a company has none when it has $586m of it.
    """
    r = _sec_get(SEC_FACTS.format(cik=cik))
    # a company with no XBRL data at all, which is rare but not an error
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    return r.json()


def _entries_for(facts, tag):
    """
    Every reported entry for one tag, each carrying the unit it was reported in.
    Tags are us-gaap unless they say otherwise, since share counts live in the
    dei taxonomy.

    XBRL keys facts by unit, and the unit is part of the fact: Novo Nordisk
    reports cash in DKK and Takeda in JPY, and flattening the unit key away left
    26,464,000,000 and 385,113,000,000 sitting in the same column as Amgen's
    dollars, to be filtered against a dollar threshold and printed with a dollar
    sign. The number is only true with its unit attached, so it travels with it
    from here to the column and on to the screen.

    "shares" and "pure" appear here too. This keeps whatever XBRL said rather
    than assuming currency, so a share count is never mistaken for money.
    """
    taxonomy, _, name = tag.rpartition(":")
    concept = facts.get("facts", {}).get(taxonomy or "us-gaap", {}).get(name)
    if not concept:
        return []
    return [dict(e, unit=unit)
            for unit, entries in concept.get("units", {}).items()
            for e in entries]


def _pick_key(entry, end):
    """
    Which of two entries for the same figure wins.

    Newest period first, then the most recently filed version of that period,
    since a later filing restating an earlier year is the current view of it.
    Dollars break a remaining tie: a company that reports the same period in two
    units has one that compares against the rest of this universe and one that
    does not.
    """
    return (end, entry.get("filed") or "", entry.get("unit") == "USD")


def _was_public_by(entry, as_of):
    """
    Whether a figure had been filed by a given date.

    This is the whole of point-in-time reconstruction. A 10-K covering 2021 is
    not public until early 2022, so asking what a company looked like at the end
    of 2021 has to exclude it: the period a figure covers says nothing about when
    anyone could see it. Selecting on the period instead of the filing date is
    how a backtest ends up trading on information that did not exist yet, and
    every signal it produces looks prescient.

    An entry with no filing date is excluded rather than assumed public, since
    assuming would reintroduce exactly the bias this exists to remove.
    """
    if as_of is None:
        return True
    filed = entry.get("filed")
    return bool(filed) and filed <= as_of


def _latest_annual(facts, tags, as_of=None):
    """
    Return the most recent annual value across ALL candidate tags.

    Important: we scan every tag and keep the newest period, instead of
    returning the first tag that happens to have data. A company that switched
    which XBRL tag it reports cash under (Illumina did) would otherwise get
    stuck on a stale year from the abandoned tag.
    """
    best = None
    # check every candidate tag, not just the first that has data
    for tag in tags:
        # walk every reported entry under this tag
        for e in _entries_for(facts, tag):
            # only keep figures that came from an annual report form
            if e.get("fp") != "FY" or e.get("form") not in ANNUAL_FORMS:
                continue
            # and, when reconstructing a past date, only what was public by then
            if not _was_public_by(e, as_of):
                continue
            start, end = e.get("start"), e.get("end")
            # an expense is a total over a period, so it must have both dates,
            # and the period must actually be a year: a 10-K also restates
            # shorter periods, and a partial year compared against cash on hand
            # would overstate runway
            if not _covers_a_year(start, end):
                continue
            # newest period wins, and where the same period was reported more
            # than once the most recently filed version is the current one
            key = _pick_key(e, end)
            if best is None or key > best["_key"]:
                best = {"value": e["val"],
                        # taken from the period itself, not from the entry's
                        # "fy" field: that is the fiscal year of the FILING,
                        # and one 10-K reports several years of comparatives
                        # all carrying the filing's year
                        "fiscal_year": int(end[:4]),
                        "fiscal_period": "FY", "period_end": end,
                        "unit": e.get("unit"),
                        "tag": tag, "_key": key}
    if best is not None:
        del best["_key"]
    return best


def _latest_balance(facts, tags, as_of=None):
    """
    Return the most recent balance-sheet value across ALL candidate tags. These
    are the entries with an end date and no start; anything covering a period
    carries both and is skipped.

    Cash is a point in time, so the right figure is the newest reported, whatever
    filing it came from. Taking the newest ANNUAL one shows what a company had at
    its last year end: Recursion's 10-K says $743m against $546m in its latest
    10-Q, and runway is computed from it.
    """
    best = None
    for tag in tags:
        for e in _entries_for(facts, tag):
            # a period total, not a balance: not comparable, so skip it
            if e.get("start") is not None:
                continue
            if e.get("form") not in REPORTED_FORMS:
                continue
            if not _was_public_by(e, as_of):
                continue
            end = e.get("end")
            if not end:
                continue
            # newest balance date wins; where the same date was reported more
            # than once (a restatement, or the prior year shown for comparison
            # in a later filing) the most recently filed one is the current view
            key = _pick_key(e, end)
            if best is None or key > best["_key"]:
                best = {"value": e["val"], "fiscal_year": e.get("fy"),
                        "fiscal_period": e.get("fp"), "period_end": end,
                        "unit": e.get("unit"),
                        "tag": tag, "_key": key}
    if best is not None:
        # sorting detail, not something callers should see
        del best["_key"]
    return best


# How many fiscal years of history to keep. A companyfacts response goes back
# further than this for older companies, and the point of the series is the
# trend rather than the archive: ten years covers a company's whole life for
# most of this universe and still bounds the table at roughly 60,000 rows.
HISTORY_YEARS = 10


def _annual_series(facts, tags, as_of=None, years=HISTORY_YEARS):
    """
    Every annual value, newest first, one per fiscal year.

    Same rules as _latest_annual, which is this function's first element: the
    period must cover a year, and where a year was reported more than once the
    most recently filed version wins. A 10-K restates the two prior years as
    comparatives, so without that a company's 2023 revenue would appear three
    times with whatever value the iteration happened to end on.
    """
    best = {}
    for tag in tags:
        for e in _entries_for(facts, tag):
            if e.get("fp") != "FY" or e.get("form") not in ANNUAL_FORMS:
                continue
            if not _was_public_by(e, as_of):
                continue
            start, end = e.get("start"), e.get("end")
            if not _covers_a_year(start, end):
                continue
            year = int(end[:4])
            key = _pick_key(e, end)
            if year not in best or key > best[year]["_key"]:
                best[year] = {"value": e["val"], "fiscal_year": year,
                              "fiscal_period": "FY", "period_end": end,
                              "unit": e.get("unit"),
                              "tag": tag, "_key": key}
    out = [best[y] for y in sorted(best, reverse=True)[:years]]
    for row in out:
        del row["_key"]
    return out


def _balance_series(facts, tags, as_of=None, years=HISTORY_YEARS):
    """
    One balance per fiscal year, newest first: the last one reported in each.

    A balance is a value on a date and a company reports one every quarter, so a
    raw series would mix year ends with quarter ends and a year-on-year
    comparison would be against whatever quarter happened to be last. Taking the
    latest balance within each year makes the years comparable. This is why the
    first element here can differ from _latest_balance, which deliberately takes
    the newest balance of any form so that runway is computed from the freshest
    cash figure rather than the last year end.
    """
    best = {}
    for tag in tags:
        for e in _entries_for(facts, tag):
            if e.get("start") is not None:
                continue
            if e.get("form") not in ANNUAL_FORMS:
                continue
            if not _was_public_by(e, as_of):
                continue
            end = e.get("end")
            if not end:
                continue
            year = int(end[:4])
            key = _pick_key(e, end)
            if year not in best or key > best[year]["_key"]:
                best[year] = {"value": e["val"], "fiscal_year": year,
                              "fiscal_period": "FY", "period_end": end,
                              "unit": e.get("unit"),
                              "tag": tag, "_key": key}
    out = [best[y] for y in sorted(best, reverse=True)[:years]]
    for row in out:
        del row["_key"]
    return out


def fetch_financials(ticker, cik=None, as_of=None):
    """
    Return real financials for a public company, or a reason it's unavailable.
    Everything is keyed by CIK, EDGAR's stable identifier.

    Pass the CIK when known. Resolving it from the ticker goes through SEC's
    ticker file, which lists only currently-listed companies and changes over
    time, so a company sourced into the universe earlier can drop out and start
    reading as "not found in EDGAR" despite having perfectly good filings.
    """
    # only fall back to the ticker file when we weren't told the CIK
    cik = cik or _load_ticker_map().get(ticker.upper())
    if not cik:
        # a company that got acquired or delisted (Verve, bought by Lilly) drops
        # out of EDGAR's ticker file even though its old trials still exist.
        return {"available": False, "reason": f"ticker {ticker} not found in EDGAR"}

    # one request for everything this company has ever reported. every figure
    # below is then selected from what is actually there, rather than guessed at
    # by name, and adding another metric costs no further requests.
    facts = fetch_company_facts(cik)

    # totals over a period only mean something over a full year: quarterly
    # filings report both the quarter and the year to date under the same tag and
    # period, so "the newest one" is ambiguous, and a three-month total compared
    # against cash on hand would overstate runway roughly fourfold.
    figures = {metric: _latest_annual(facts, tags, as_of) for metric, tags in (
        ("rd_expense", RD_TAGS),
        # the real burn. R&D leaves out G&A and everything else, so using it as
        # the denominator of runway makes every company look longer-lived.
        ("operating_cash_flow", OPERATING_CASH_FLOW_TAGS),
        ("net_income", NET_INCOME_TAGS),
        # whether the company sells anything yet
        ("revenue", REVENUE_TAGS),
    )}
    # balances are a value on a date, so the newest one reported is the right
    # one, quarterly filings included
    figures.update({metric: _latest_balance(facts, tags, as_of) for metric, tags in (
        ("cash", CASH_TAGS),
        # kept separate from cash rather than summed here: whether the two can be
        # added depends on their dates matching, which is a judgement the analysis
        # layer makes and explains, not something to bake silently into a total
        ("marketable_securities", SECURITIES_TAGS),
        ("debt", DEBT_TAGS),
        ("shares_outstanding", SHARES_TAGS),
    )})

    # if nothing at all came back, the company almost certainly files under IFRS
    # (foreign private issuers like BioNTech file a 20-F with ifrs-full tags,
    # not us-gaap), so say that plainly instead of showing a blank.
    if not any(figures.values()):
        return {
            "available": False,
            "cik": cik,
            "reason": "no annual figures found under us-gaap or ifrs-full",
        }

    # The same facts response, read as a series rather than a point. It costs no
    # further request: everything a company has ever reported already arrived.
    # Kept under its own key so the shape callers already read is unchanged, and
    # a metric's newest entry stays exactly what it was.
    history = {metric: _annual_series(facts, tags, as_of) for metric, tags in (
        ("rd_expense", RD_TAGS),
        ("operating_cash_flow", OPERATING_CASH_FLOW_TAGS),
        ("net_income", NET_INCOME_TAGS),
        ("revenue", REVENUE_TAGS),
    )}
    history.update({metric: _balance_series(facts, tags, as_of)
                    for metric, tags in (
        ("cash", CASH_TAGS),
        ("marketable_securities", SECURITIES_TAGS),
        ("debt", DEBT_TAGS),
        ("shares_outstanding", SHARES_TAGS),
    )})

    return {"available": True, "cik": cik, "history": history, **figures}