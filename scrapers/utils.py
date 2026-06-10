import hashlib
import re
from urllib.parse import urljoin, urlparse

INCLUDE_KEYWORDS = ("circular", "circulars", "office-order", "orders-circulars", "order")
EXCLUDE_KEYWORDS = (
    "press-release",
    "press",
    "media",
    "tender",
    "recruitment",
    "notification",
    "photo",
    "gallery",
    "video",
    "news",
    "pressrelease",
)

KNOWN_CIRCULAR_RSS_FEEDS: dict[str, str] = {
    "Income Tax Department": "https://incometaxindia.gov.in/RSS/GetRSSFeed.aspx?Type=Circular",
}

# Keyed by a substring of the ministry name in the DB (case-insensitive match).
# For each ministry/department, this points directly to the circulars/orders listing page.
KNOWN_CIRCULAR_PAGES: dict[str, str] = {
    # ── Agriculture & allied ──────────────────────────────────────────────────
    "Agriculture and Farmers Welfare":
        "https://agricoop.nic.in/circulars-notifications-listing",
    "Agricultural Research and Education":
        "https://icar.gov.in/en/circulars-data",
    "Animal Husbandry and Dairying":
        "https://www.dahd.gov.in/office_order_circular/notifications",
    "Fisheries":
        "https://dof.gov.in/circulars",
    "Consumer Affairs":
        "https://consumeraffairs.gov.in/pages/circulars",

    # ── Finance ───────────────────────────────────────────────────────────────
    "Economic Affairs":
        "https://dea.gov.in/orders-and-circulars",
    "Expenditure":
        "https://doe.gov.in/orders-circulars",
    "Financial Services":
        "https://dfs.gov.in/financial-inclusion/circulars",
    "Revenue":
        "https://dor.gov.in/office-circulars",
    "Investment and Public Asset Management":
        "https://dipam.gov.in/",
    "Public Enterprises":
        "https://www.dpe.gov.in/documents/orders-and-notices",

    # ── Defence ───────────────────────────────────────────────────────────────
    "Department of Defence Production":
        "https://www.ddpmod.gov.in/documents/orders-and-notices",
    "Defence Research and Development":
        "https://www.drdo.gov.in/whats-new/press-release",
    "Department of Defence":
        "https://www.mod.gov.in/dod/oms_orders",
    "Ministry of Defence":
        "https://www.mod.gov.in/dod/oms_orders",

    # ── Education ─────────────────────────────────────────────────────────────
    "Higher Education":
        "https://www.education.gov.in/en/circulars-orders-notification",
    "School Education":
        "https://dsel.education.gov.in/circular-order-notification",
    "Ministry of Education":
        "https://www.education.gov.in/en/circulars-orders-notification",

    # ── Health ────────────────────────────────────────────────────────────────
    "Health and Family Welfare":
        "https://mohfw.gov.in/acts-rules-and-guidelines/guidelines",
    "Health Research":
        "https://dhr.gov.in/documents/acts-circulars",

    # ── Home Affairs / Personnel ──────────────────────────────────────────────
    "Home Affairs":
        "https://www.mha.gov.in/en/notifications/circular",
    "Administrative Reforms and Public Grievances":
        "https://darpg.gov.in/circulars",
    "Personnel and Training":
        "https://dopt.gov.in/notifications/orders",
    "Pension":
        "https://doppw.gov.in/en/circulars-pension",
    "Official Language":
        "https://rajbhasha.gov.in/en/orders-and-circulars",

    # ── Industry & Trade ──────────────────────────────────────────────────────
    "Promotion of Industry and Internal Trade":
        "https://www.dpiit.gov.in/documents/orders-and-notices/circulars-gTO5kDNtQWa",
    "Commerce":
        "https://www.commerce.gov.in/",
    "Corporate Affairs":
        "https://www.mca.gov.in/content/mca/global/en/acts-rules/ebooks/circulars.html",
    "Micro, Small":
        "https://msme.gov.in/circulars",
    "Heavy Industries":
        "https://heavyindustries.gov.in/en/notifications",
    "Steel":
        "https://steel.gov.in/documents-publications",
    "Textiles":
        "https://texmin.gov.in/notification",
    "Food Processing":
        "https://www.mofpi.gov.in/notifications/office-order-and-circulars",
    "Chemicals and Petro":
        "https://chemicals.gov.in/chemicals-quality-control-orders",
    "Pharmaceuticals":
        "https://pharmaceuticals.gov.in/circulars",
    "Fertilizers":
        "https://www.fert.gov.in/en/what-s-new",

    # ── Infrastructure & Energy ───────────────────────────────────────────────
    "Road Transport and Highways":
        "https://morth.gov.in/OMs-Circular-Other-Notification",
    "Railways":
        "https://indianrailways.gov.in/railwayboard/view_section.jsp?lang=0&id=0,1,304,366,554",
    "Civil Aviation":
        "https://www.civilaviation.gov.in/ministry-documents/circulars",
    "Ports, Shipping":
        "https://www.shipmin.gov.in/orders/circulars",
    "Ministry of Power":
        "https://powermin.gov.in/en/circular",
    "Coal":
        "https://coal.gov.in/whats-new",
    "Ministry of Mines":
        "https://mines.gov.in/webportal/notifications",
    "Petroleum and Natural Gas":
        "https://mopng.gov.in/en/notices/circular",
    "New and Renewable Energy":
        "https://mnre.gov.in/en/notifications-circulars/",
    "Housing and Urban Affairs":
        "https://mohua.gov.in/publication.php?sa=circulars.php",

    # ── Water & Environment ───────────────────────────────────────────────────
    "Water Resources":
        "https://cwc.gov.in/en/orders_and_circulars",
    "Jal Shakti":
        "https://cwc.gov.in/en/orders_and_circulars",
    "Drinking Water and Sanitation":
        "https://jalshakti-ddws.gov.in/letters-circulars-all?category_tid=All",
    "Environment":
        "https://moef.gov.in/circular-orders",

    # ── Rural & Social Development ────────────────────────────────────────────
    "Rural Development":
        "https://www.rural.gov.in/",
    "Land Resources":
        "https://dolr.gov.in/document-category/policy-circular/",
    "Panchayati Raj":
        "https://panchayat.gov.in/en/document-category/office-orders/",
    "Tribal Affairs":
        "https://tribal.nic.in/",
    "Social Justice and Empowerment":
        "https://socialjustice.gov.in/common/1250",
    "Empowerment of Persons with Disabilities":
        "https://depwd.gov.in/en/circulars/",
    "Minority Affairs":
        "https://www.minorityaffairs.gov.in/",
    "Women and Child Development":
        "https://wcd.nic.in/fnb/notifications",

    # ── Science & Technology ──────────────────────────────────────────────────
    "Science and Technology":
        "https://dst.gov.in/circulars",
    "Scientific and Industrial Research":
        "https://www.dsir.gov.in/circulars/archive",
    "Biotechnology":
        "https://dbtindia.gov.in/notices-circular",
    "Atomic Energy":
        "https://dae.gov.in/dae-secretariat-matters/",
    "Earth Sciences":
        "https://www.moes.gov.in/documents/Circulars-Notifications-Memorandums",
    "Electronics and Information Technology":
        "https://www.meity.gov.in/documents/orders-and-notices",
    "Telecommunications":
        "https://dot.gov.in/circulars",

    # ── Labour, Skills, Employment ────────────────────────────────────────────
    "Labour and Employment":
        "https://labour.gov.in/acts-rules/circulars",
    "Skill Development":
        "https://www.msde.gov.in/en/reports-documents/orders-circulars",

    # ── Law & Legislature ─────────────────────────────────────────────────────
    "Justice":
        "https://doj.gov.in/document-category/circulars-notifications/",
    "Legislative":
        "https://legislative.gov.in/document-category/orders-circulars/",
    "Legal Affairs":
        "https://dola.gov.in/",

    # ── Posts & Communications ────────────────────────────────────────────────
    "Posts":
        "https://www.indiapost.gov.in/documents/ordersandnotices",

    # ── Miscellaneous ─────────────────────────────────────────────────────────
    "AYUSH":
        "https://main.ayush.gov.in/circulars/",
    "Cooperation":
        "https://cooperation.gov.in/notices-circulars",
    "Culture":
        "https://www.indiaculture.gov.in/current-circulars",
    "External Affairs":
        "https://www.mea.gov.in/circulars-notifications.htm",
    "Food and Public Distribution":
        "https://dfpd.gov.in/index.htm",
    "Information and Broadcasting":
        "https://mib.gov.in/en/documents/notification/notices",
    "Parliamentary Affairs":
        "https://mpa.gov.in/notifications/circulars",
    "Sports":
        "https://www.yas.nic.in/sports/circulars",
    "Statistics and Programme Implementation":
        "https://mospi.gov.in/iss-circulars",
    "Tourism":
        "https://tourism.gov.in/circulars",
    "Youth Affairs":
        "https://yas.gov.in/",
}


def make_fingerprint(source_url: str, content: str) -> str:
    payload = f"{source_url}{content[:500]}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_circular_url(url: str) -> bool:
    path = urlparse(url.lower()).path
    if any(excluded in path for excluded in EXCLUDE_KEYWORDS):
        if "circular" not in path:
            return False
    return any(keyword in path for keyword in INCLUDE_KEYWORDS)


def is_excluded_feed(title: str, url: str) -> bool:
    combined = f"{title} {url}".lower()
    if "circular" in combined:
        return False
    return any(keyword in combined for keyword in EXCLUDE_KEYWORDS)


def normalize_url(base: str, href: str) -> str | None:
    if not href or href.startswith("#") or href.startswith("javascript:"):
        return None
    return urljoin(base, href)


def extract_abbreviation(name: str) -> str | None:
    match = re.search(r"\(([^)]+)\)\s*$", name)
    return match.group(1) if match else None


def clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()
