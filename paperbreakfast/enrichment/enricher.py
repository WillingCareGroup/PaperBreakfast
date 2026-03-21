"""
Post-evaluation enrichment: fetch PI name and institution from Crossref and PubMed.

Strategy (from empirical testing on 25 papers):
  - Crossref: 84% PI name coverage, 28% institution coverage
  - PubMed:   56% PI name coverage, 52% institution coverage

Combined approach:
  1. PubMed first — prefers authors with email in affiliation (= corresponding author);
     falls back to last author if none are marked
  2. Crossref fallback — last author used as PI (no corresponding-author flag available)

Only called for papers above score threshold that have a DOI and are missing
institution data. ~2 API calls per paper in the worst case; well within free
rate limits at typical daily volumes (5–20 papers).
"""
import json
import logging
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "PaperBreakfast/1.0 (mailto:paperbreakfast@localhost)"}
_TIMEOUT = 10


def enrich_paper(doi: str) -> tuple[str | None, str | None]:
    """
    Return (pi_name, institution) for the given DOI.
    Either value may be None if the APIs don't have the data.
    Never raises.
    """
    pi_name, institution = _pubmed_lookup(doi)

    if not pi_name or not institution:
        cr_pi, cr_inst = _crossref_lookup(doi)
        pi_name = pi_name or cr_pi
        institution = institution or cr_inst

    return pi_name, institution


# ── Crossref ──────────────────────────────────────────────────────────────────

def _crossref_lookup(doi: str) -> tuple[str | None, str | None]:
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='/')}"
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read())["message"]

        authors = data.get("author", [])
        if not authors:
            return None, None

        # Last author is the PI by convention
        last = authors[-1]
        given = last.get("given", "")
        family = last.get("family", "")
        name = f"{family} {given[:1]}".strip() if family else None

        # Crossref affiliation data is sparse — try last author, then first
        inst = None
        for candidate in [last] + ([authors[0]] if len(authors) > 1 else []):
            affils = candidate.get("affiliation", [])
            if affils:
                inst = affils[0].get("name")
                break

        return name, inst

    except Exception as e:
        logger.debug(f"Crossref lookup failed for {doi}: {e}")
        return None, None


# ── PubMed ────────────────────────────────────────────────────────────────────

def _pubmed_lookup(doi: str) -> tuple[str | None, str | None]:
    pmid = _doi_to_pmid(doi)
    if not pmid:
        return None, None
    return _pmid_to_author_affil(pmid)


def _doi_to_pmid(doi: str) -> str | None:
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?"
        f"db=pubmed&term={urllib.parse.quote(doi + '[doi]')}&retmode=json"
    )
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            result = json.loads(r.read())
        ids = result.get("esearchresult", {}).get("idlist", [])
        return ids[0] if ids else None
    except Exception as e:
        logger.debug(f"PubMed DOI search failed for {doi}: {e}")
        return None


def _pmid_to_author_affil(pmid: str) -> tuple[str | None, str | None]:
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?"
        f"db=pubmed&id={pmid}&retmode=xml"
    )
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            root = ET.fromstring(r.read())

        authors_el = root.findall(".//Author")
        if not authors_el:
            return None, None

        def _parse_author(author):
            last = author.findtext("LastName", "")
            fore = author.findtext("ForeName", "")
            init = (fore[0] if fore else author.findtext("Initials", ""))[:1]
            name = f"{last} {init}".strip() if last else None
            affil = author.findtext(".//AffiliationInfo/Affiliation", "") or ""
            # Strip trailing email / electronic address from institution string
            inst = affil.split(". Electronic")[0].split(". Email")[0].strip()[:200] or None
            has_email = "@" in affil
            return name, inst, has_email

        # Prefer corresponding authors (email in affiliation) — first one wins.
        # Collaborations often have multiple; first corresponding = lead lab by convention.
        # Fall back to last author if no corresponding author is marked.
        pi_name = pi_inst = None
        corresponding = [(n, i) for n, i, e in (_parse_author(a) for a in authors_el) if e]
        if corresponding:
            pi_name, pi_inst = corresponding[0]
        else:
            for name, inst, _ in (_parse_author(a) for a in reversed(authors_el)):
                pi_name = pi_name or name
                pi_inst = pi_inst or inst
                if pi_name and pi_inst:
                    break

        return pi_name, pi_inst

    except Exception as e:
        logger.debug(f"PubMed fetch failed for pmid {pmid}: {e}")
        return None, None
