"""
Seed 13 South African ISP providers (idempotent upsert by slug).
"""
import logging
from sqlalchemy.orm import Session
from app.models.models import ISPProvider

logger = logging.getLogger(__name__)

SA_ISPS = [
    {
        "name": "Afrihost",
        "slug": "afrihost",
        "status_page_url": "https://status.afrihost.com",
        "downdetector_slug": "afrihost",
        "probe_targets": ["https://www.afrihost.com", "https://clientzone.afrihost.com"],
    },
    {
        "name": "Axxess",
        "slug": "axxess",
        "status_page_url": None,
        "downdetector_slug": "axxess",
        "probe_targets": ["https://www.axxess.co.za"],
    },
    {
        "name": "Cool Ideas",
        "slug": "cool-ideas",
        "status_page_url": "https://status.coolideas.co.za",
        "downdetector_slug": "cool-ideas",
        "probe_targets": ["https://www.coolideas.co.za"],
    },
    {
        "name": "MWEB",
        "slug": "mweb",
        "status_page_url": None,
        "downdetector_slug": "mweb",
        "probe_targets": ["https://www.mweb.co.za"],
    },
    {
        "name": "Rain",
        "slug": "rain",
        "status_page_url": None,
        "downdetector_slug": "rain",
        "probe_targets": ["https://www.rain.co.za"],
    },
    {
        "name": "RSAWeb",
        "slug": "rsaweb",
        "status_page_url": "https://status.rsaweb.co.za",
        "downdetector_slug": "rsaweb",
        "probe_targets": ["https://www.rsaweb.co.za"],
    },
    {
        "name": "Telkom",
        "slug": "telkom",
        "status_page_url": None,
        "downdetector_slug": "telkom",
        "probe_targets": ["https://www.telkom.co.za"],
    },
    {
        "name": "Vox",
        "slug": "vox",
        "status_page_url": "https://status.voxtelecom.co.za",
        "downdetector_slug": "vox-telecom",
        "probe_targets": ["https://www.voxtelecom.co.za"],
    },
    {
        "name": "WebAfrica",
        "slug": "webafrica",
        "status_page_url": None,
        "downdetector_slug": "webafrica",
        "probe_targets": ["https://www.webafrica.co.za"],
    },
    {
        "name": "Herotel",
        "slug": "herotel",
        "status_page_url": None,
        "downdetector_slug": None,
        "probe_targets": ["https://www.herotel.com"],
    },
    {
        "name": "Metrofibre",
        "slug": "metrofibre",
        "status_page_url": None,
        "downdetector_slug": None,
        "probe_targets": ["https://www.metrofibre.co.za"],
    },
    {
        "name": "Vumatel",
        "slug": "vumatel",
        "status_page_url": "https://status.vumatel.co.za",
        "downdetector_slug": "vumatel",
        "probe_targets": ["https://www.vumatel.co.za"],
    },
    {
        "name": "Stem",
        "slug": "stem",
        "status_page_url": None,
        "downdetector_slug": None,
        "probe_targets": ["https://www.stem.co.za"],
        "gateway_ip": "192.168.1.252",
        "underlying_provider": "X-DSL",
    },
]


def seed_isp_providers(db: Session) -> int:
    """
    Upsert 13 SA ISPs by slug. Returns count of providers created/updated.
    """
    count = 0
    for isp_data in SA_ISPS:
        slug = isp_data["slug"]
        existing = db.query(ISPProvider).filter(ISPProvider.slug == slug).first()
        if existing:
            for key, value in isp_data.items():
                setattr(existing, key, value)
            logger.info(f"Updated ISP provider: {slug}")
        else:
            provider = ISPProvider(**isp_data)
            db.add(provider)
            logger.info(f"Created ISP provider: {slug}")
        count += 1

    db.commit()
    logger.info(f"Seeded {count} ISP providers")
    return count
