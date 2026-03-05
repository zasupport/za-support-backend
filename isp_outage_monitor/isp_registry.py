"""
Health Check AI — South African ISP Registry
Known ISPs with their status page URLs, Downdetector slugs, and probe targets.
This supplements the database registry with scraping-specific metadata.
"""

# Downdetector ZA slug mappings
# URL pattern: https://downdetector.co.za/status/{slug}/
DOWNDETECTOR_SLUGS = {
    "stem":         None,                   # not listed on Downdetector
    "x-dsl":        None,                   # not listed — niche provider
    "afrihost":     "afrihost",
    "rain":         "rain",
    "vumatel":      "vumatel",
    "openserve":    "openserve",
    "rsaweb":       "rsaweb",
    "coolideas":    None,
    "webafrica":    "webafrica",
    "herotel":      None,
    "vodacom":      "vodacom",
    "mtn":          "mtn",
    "telkom":       "telkom",
}

# Known status page patterns for scraping
# Each entry: { url, type, up_indicator, down_indicator }
STATUS_PAGE_CONFIGS = {
    "afrihost": {
        "url": "https://status.afrihost.com",
        "type": "statuspage",               # Atlassian StatusPage format
        "up_indicators": ["All Systems Operational", "all systems operational"],
        "down_indicators": ["Major Outage", "Partial Outage", "Degraded Performance",
                           "major outage", "partial outage", "degraded"],
    },
    "rsaweb": {
        "url": "https://status.rsaweb.co.za",
        "type": "statuspage",
        "up_indicators": ["All Systems Operational"],
        "down_indicators": ["Major Outage", "Partial Outage", "Degraded"],
    },
}

# HTTP probe targets — lightweight endpoints to check if ISP DNS/routing works
# These are the ISP's own websites; if we can't reach them, their network may be down
HTTP_PROBE_TARGETS = {
    "stem":         "https://www.stem.co.za",
    "x-dsl":        "https://www.x-dsl.co.za",
    "afrihost":     "https://www.afrihost.com",
    "rain":         "https://www.rain.co.za",
    "vumatel":      "https://www.vumatel.co.za",
    "openserve":    "https://www.openserve.co.za",
    "rsaweb":       "https://www.rsaweb.co.za",
    "coolideas":    "https://www.coolideas.co.za",
    "webafrica":    "https://www.webafrica.co.za",
    "herotel":      "https://www.herotel.com",
    "vodacom":      "https://www.vodacom.co.za",
    "mtn":          "https://www.mtn.co.za",
    "telkom":       "https://www.telkom.co.za",
}

# ISP support contact details for auto-generated call scripts
ISP_SUPPORT_CONTACTS = {
    "stem": {
        "name": "Stem",
        "phone": None,                       # populate when known
        "email": None,
        "hours": "Business hours",
    },
    "x-dsl": {
        "name": "X-DSL Networking Solutions",
        "phone": None,
        "email": None,
        "hours": "Business hours",
    },
    "afrihost": {
        "name": "Afrihost",
        "phone": "011 612 7200",
        "email": "support@afrihost.com",
        "hours": "24/7",
    },
    "rain": {
        "name": "Rain",
        "phone": "087 820 7246",
        "email": None,
        "hours": "Business hours",
    },
    "vumatel": {
        "name": "Vumatel",
        "phone": "086 100 8862",
        "email": None,
        "hours": "24/7",
    },
    "openserve": {
        "name": "Openserve",
        "phone": "080 021 0021",
        "email": None,
        "hours": "24/7",
    },
    "rsaweb": {
        "name": "RSAWEB",
        "phone": "087 470 0000",
        "email": "support@rsaweb.co.za",
        "hours": "24/7",
    },
    "vodacom": {
        "name": "Vodacom",
        "phone": "082 111",
        "email": None,
        "hours": "24/7",
    },
    "mtn": {
        "name": "MTN",
        "phone": "083 123",
        "email": None,
        "hours": "24/7",
    },
    "telkom": {
        "name": "Telkom",
        "phone": "10210",
        "email": None,
        "hours": "24/7",
    },
}
