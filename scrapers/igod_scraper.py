import logging

from sqlalchemy.orm import Session

from database.models import Ministry

logger = logging.getLogger(__name__)

# Exact 47 ministries/departments with confirmed circular URLs.
# (name, abbreviation, org_type, official_url)
STATIC_MINISTRIES: list[tuple[str, str, str, str]] = [
    ("Department of Administrative Reforms and Public Grievances", "DARPG", "department", "https://darpg.gov.in"),
    ("Department of Agricultural Research and Education", "DARE", "department", "https://icar.gov.in"),
    ("Department of Animal Husbandry and Dairying", "DAHD", "department", "https://www.dahd.gov.in"),
    ("Department of Atomic Energy", "DAE", "department", "https://dae.gov.in"),
    ("Department of Chemicals and Petrochemicals", "DCP", "department", "https://chemicals.gov.in"),
    ("Department of Consumer Affairs", "DoCA", "department", "https://consumeraffairs.gov.in"),
    ("Department of Defence", "DoD", "department", "https://www.mod.gov.in"),
    ("Department of Defence Production", "DDP", "department", "https://www.ddpmod.gov.in"),
    ("Department of Defence Research and Development", "DRDO", "department", "https://www.drdo.gov.in"),
    ("Department of Economic Affairs", "DEA", "department", "https://dea.gov.in"),
    ("Department of Empowerment of Persons with Disabilities", "DEPwD", "department", "https://depwd.gov.in"),
    ("Department of Fertilizers", "DoFz", "department", "https://www.fert.gov.in"),
    ("Department of Food and Public Distribution", "DFPD", "department", "https://dfpd.gov.in"),
    ("Department of Investment and Public Asset Management", "DIPAM", "department", "https://dipam.gov.in"),
    ("Department of Land Resources", "DLR", "department", "https://dolr.gov.in"),
    ("Department of Official Language", "DOL", "department", "https://rajbhasha.gov.in"),
    ("Department of Personnel and Training", "DoPT", "department", "https://dopt.gov.in"),
    ("Department of Posts", "DoP", "department", "https://www.indiapost.gov.in"),
    ("Department of Revenue", "DoR", "department", "https://dor.gov.in"),
    ("Department of Science and Technology", "DST", "department", "https://dst.gov.in"),
    ("Department of Social Justice and Empowerment", "DSJE", "department", "https://socialjustice.gov.in"),
    ("Department of Sports", "DoS", "department", "https://www.yas.nic.in"),
    ("Department of Water Resources, River Development and Ganga Rejuvenation", "DWRDGR", "department", "https://cwc.gov.in"),
    ("Department of Youth Affairs", "DoYA", "department", "https://yas.gov.in"),
    ("Ministry of Chemicals and Fertilizers", "MoCF", "ministry", "https://chemicals.gov.in"),
    ("Ministry of Civil Aviation", "MoCA", "ministry", "https://www.civilaviation.gov.in"),
    ("Ministry of Coal", "MoC", "ministry", "https://coal.gov.in"),
    ("Ministry of Cooperation", "MoCoop", "ministry", "https://cooperation.gov.in"),
    ("Ministry of Defence", "MoD", "ministry", "https://www.mod.gov.in"),
    ("Ministry of Environment, Forest and Climate Change", "MoEFCC", "ministry", "https://moef.gov.in"),
    ("Ministry of External Affairs", "MEA", "ministry", "https://www.mea.gov.in"),
    ("Ministry of Food Processing Industries", "MoFPI", "ministry", "https://www.mofpi.gov.in"),
    ("Ministry of Heavy Industries", "MoHI", "ministry", "https://heavyindustries.gov.in"),
    ("Ministry of Home Affairs", "MHA", "ministry", "https://www.mha.gov.in"),
    ("Ministry of Information and Broadcasting", "MIB", "ministry", "https://mib.gov.in"),
    ("Ministry of Jal Shakti", "MoJS", "ministry", "https://jalshakti.gov.in"),
    ("Ministry of Micro, Small and Medium Enterprises", "MoMSME", "ministry", "https://msme.gov.in"),
    ("Ministry of Minority Affairs", "MoMA", "ministry", "https://www.minorityaffairs.gov.in"),
    ("Ministry of New and Renewable Energy", "MNRE", "ministry", "https://mnre.gov.in"),
    ("Ministry of Panchayati Raj", "MoPR", "ministry", "https://panchayat.gov.in"),
    ("Ministry of Ports, Shipping and Waterways", "MoPSW", "ministry", "https://www.shipmin.gov.in"),
    ("Ministry of Railways", "MoR", "ministry", "https://indianrailways.gov.in"),
    ("Ministry of Science and Technology", "MoST", "ministry", "https://dst.gov.in"),
    ("Ministry of Steel", "MoS", "ministry", "https://steel.gov.in"),
    ("Ministry of Tourism", "MoT", "ministry", "https://tourism.gov.in"),
    ("Ministry of Tribal Affairs", "MoTA", "ministry", "https://tribal.gov.in"),
    ("Ministry of Youth Affairs and Sports", "MoYAS", "ministry", "https://yas.gov.in"),
]


def refresh_ministries(db: Session) -> int:
    static_names = {entry[0] for entry in STATIC_MINISTRIES}

    # Deactivate anything not in the static list
    for ministry in db.query(Ministry).filter(Ministry.is_active.is_(True)).all():
        if ministry.name not in static_names:
            ministry.is_active = False
    db.commit()

    updated = 0
    for name, abbreviation, org_type, official_url in STATIC_MINISTRIES:
        existing = db.query(Ministry).filter(Ministry.name == name).first()
        if existing:
            existing.is_active = True
            existing.abbreviation = abbreviation
            existing.org_type = org_type
            existing.official_url = official_url
        else:
            db.add(Ministry(
                name=name,
                abbreviation=abbreviation,
                org_type=org_type,
                official_url=official_url,
                is_active=True,
            ))
        updated += 1

    db.commit()
    logger.info("Synced %s ministries from static list", updated)
    return updated
