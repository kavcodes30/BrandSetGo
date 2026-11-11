"""Legal guideline registry.

A curated, versioned set of advertising and content rules mapped to Indian
regulatory frameworks. Each entry carries the authority, the citation, what the
obligation actually is, how severe a breach is, and what the creator should
change.

Two honest boundaries, repeated in the API and the UI:

* this is reviewer assistance, not legal advice;
* the citation points at the framework and the provision it comes from, and a
  human (ideally counsel) confirms applicability. Rules change; the registry is
  versioned so a review always records the version it was judged against.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

REGISTRY_VERSION = "2026.02"

DISCLAIMER = (
    "Mapped to Indian advertising and content frameworks for reviewer assistance. "
    "This is not legal advice: confirm applicability with counsel before publishing."
)


@dataclass(frozen=True)
class Guideline:
    code: str
    title: str
    authority: str
    citation: str
    obligation: str
    severity: str  # low | medium | high | critical
    remediation: str
    sectors: tuple[str, ...] = ()  # empty = every sector
    channels: tuple[str, ...] = ()  # empty = every channel
    patterns: tuple[str, ...] = ()
    requires_absent: tuple[str, ...] = ()  # finding only if none of these appear
    tags: tuple[str, ...] = field(default_factory=tuple)

    def applies_to(self, sector: str, channel: str) -> bool:
        sector = (sector or "").lower()
        if self.sectors and sector not in self.sectors:
            return False
        if self.channels and channel not in self.channels:
            return False
        return True

    def compiled(self) -> list[re.Pattern[str]]:
        return [re.compile(p, re.IGNORECASE) for p in self.patterns]


def _g(*args, **kwargs) -> Guideline:
    return Guideline(*args, **kwargs)


# --------------------------------------------------------------------------
# Health, cosmetics and food
# --------------------------------------------------------------------------
CURE_CLAIMS = _g(
    code="IN-DMR-S3",
    title="Claim to cure or treat a disease",
    authority="Drugs and Magic Remedies (Objectionable Advertisements) Act, 1954",
    citation="Section 3(d) read with Schedule I",
    obligation=(
        "Advertisements may not claim that a product cures, treats, prevents or mitigates a disease or "
        "condition listed in Schedule I (for example diabetes, blood pressure, obesity, arthritis, "
        "asthma, cancer). The restriction applies to cosmetics, foods and supplements as much as to drugs."
    ),
    severity="critical",
    remediation=(
        "Remove the disease claim entirely. Describe the cosmetic or sensory benefit instead, keep the "
        "product category accurate, and route the copy to a legal reviewer if the product genuinely has a "
        "therapeutic licence."
    ),
    patterns=(
        r"\b(cures?|treats?|heals?|prevents?|reverses?)\b[^.!?]{0,40}\b(disease|diabetes|cancer|asthma|arthritis|eczema|psoriasis|thyroid|blood\s+pressure|hypertension|obesity|acidity|migraine|piles|anxiety|depression|insomnia|stress|pcos|infertility|hair\s+loss|hairfall|acne|pimples|dandruff|pigmentation|dark\s+spots|warts?|vitiligo|grey\s+hair|greying)\b",
        r"\b(disease|diabetes|cancer|asthma|arthritis|eczema|psoriasis|thyroid|blood\s+pressure|obesity|anxiety|depression|insomnia|acne|dandruff)\b[^.!?]{0,30}\b(cure|treatment|remedy|solution)\b",
    ),
    tags=("health", "regulated"),
)

THERAPEUTIC_COSMETIC = _g(
    code="IN-COSMETIC-CLAIMS",
    title="Therapeutic claim on a cosmetic product",
    authority="Drugs and Cosmetics Act, 1940 — Cosmetics Rules, 2020",
    citation="Cosmetics Rules, 2020 (claims and labelling)",
    obligation=(
        "A cosmetic may only make cleansing, beautifying, promoting attractiveness or altering appearance "
        "claims. Claims that a cosmetic removes, cures or treats a condition move it into the drug "
        "definition and require a drug licence."
    ),
    severity="critical",
    remediation=(
        "Replace the therapeutic verb with an appearance verb: 'removes wrinkles' becomes 'helps skin look "
        "smoother with daily use'. Never promise a clinical outcome for a cosmetic."
    ),
    sectors=("skincare", "beauty", "cosmetics", "perfume", "personal care"),
    patterns=(
        r"\b(removes?|eliminates?|cures?|treats?|eradicates?)\b[^.!?]{0,25}\b(wrinkles?|acne|pimples|pigmentation|dark\s+spots|scars?|dandruff|hair\s+fall|stretch\s+marks)\b",
        r"\b(anti[- ]?ageing|anti[- ]?aging)\s+(treatment|therapy|cure)\b",
    ),
    tags=("health", "regulated"),
)

CLINICAL_SUBSTANTIATION = _g(
    code="IN-ASCI-I4-SUBSTANTIATION",
    title="Unsubstantiated efficacy or clinical claim",
    authority="Advertising Standards Council of India (ASCI) Code",
    citation="Chapter I.4 — substantiation of claims",
    obligation=(
        "Every claim capable of objective substantiation must be backed by evidence that the advertiser "
        "holds before the ad runs. 'Clinically proven', percentages and timeframes are exactly the claims "
        "the ASCI expects to see substantiated on request."
    ),
    severity="high",
    remediation=(
        "Attach the study or test report to the claim record, or qualify the wording. If the evidence is "
        "not on file, drop the number and the timeframe and describe the benefit qualitatively."
    ),
    patterns=(
        r"\b(clinically|dermatologically|scientifically|lab[- ]tested|research[- ]proven)\s+(proven|tested|backed)\b",
        r"\b\d{1,3}\s*%\s*(of\s+)?(users|people|participants|women|men)\b",
        r"\b(proven|tested)\s+to\b",
    ),
    tags=("claims",),
)

DURATION_CLAIM = _g(
    code="IN-ASCI-I4-DURATION",
    title="Specific duration or result-timeframe promise",
    authority="Advertising Standards Council of India (ASCI) Code",
    citation="Chapter I.4 — substantiation of claims",
    obligation=(
        "A stated duration ('lasts 24 hours', 'results in 7 days') is a testable claim. It needs a test "
        "protocol, the sample and the conditions, and it must hold for the average consumer, not the best case."
    ),
    severity="high",
    remediation=(
        "Either cite the test that supports the duration, or replace it with a qualitative descriptor "
        "such as 'long-lasting' that carries the same benefit without a testable promise."
    ),
    patterns=(
        r"\b(lasts?|stays?|lingers?|works?|effective)\s+(for\s+)?(\d+\s*(hours?|hrs?|days?|weeks?)|all\s+day|the\s+whole\s+day|24\s*hours?)\b",
        r"\b(results?|visible\s+results?|difference)\s+(in|within)\s+\d+\s*(days?|weeks?)\b",
        r"\b(in|within)\s+(a|one|\d+)\s*(day|week|month)s?\b",
    ),
    tags=("claims",),
)

GUARANTEE = _g(
    code="IN-CPA-GUARANTEE",
    title="Absolute guarantee or 100% claim",
    authority="Consumer Protection Act, 2019",
    citation="Section 2(28) — misleading advertisement",
    obligation=(
        "An unqualified 'guaranteed', '100%', 'permanent' or 'risk-free' promise is misleading if any "
        "consumer could reasonably not get that outcome. Conditions must be stated as prominently as the claim."
    ),
    severity="medium",
    remediation=(
        "Remove the absolute word, or state the condition next to it in the same size and for the same "
        "duration ('guaranteed' becomes '7-day replacement if unused, terms apply')."
    ),
    patterns=(
        r"\b(guaranteed?|guarantees?)\b",
        r"\b100\s*%\s*(safe|effective|natural|results?|success|organic)\b",
        r"\b(risk[- ]free|permanent(ly)?|never\s+fails?)\b",
    ),
    tags=("claims",),
)

FOOD_HEALTH = _g(
    code="IN-FSSAI-ADV-2018",
    title="Health or immunity claim on a food product",
    authority="Food Safety and Standards Authority of India",
    citation="Food Safety and Standards (Advertising and Claims) Regulations, 2018",
    obligation=(
        "Health claims on foods are restricted to those permitted by the regulations and must be "
        "substantiated. 'Boosts immunity', 'detox', 'fat burning' and disease-risk reduction claims need "
        "an approved claim and the licence details on the pack."
    ),
    severity="high",
    remediation=(
        "Use only permitted nutrition claims, add the FSSAI licence number, and drop disease-risk or "
        "detox language unless it is an approved claim."
    ),
    sectors=("food", "beverage", "fmcg", "nutrition", "supplement"),
    patterns=(
        r"\b(boosts?|strengthens?)\s+(the\s+)?immun(e|ity)\b",
        r"\b(detox|fat[- ]burning|burns?\s+fat|weight\s+loss|slimming)\b",
        r"\b(prevents?|reduces?\s+the\s+risk\s+of)\s+\w+",
    ),
    tags=("health", "regulated"),
)


# --------------------------------------------------------------------------
# Advertising conduct
# --------------------------------------------------------------------------
MISLEADING = _g(
    code="IN-CPA-S2-28",
    title="Misleading or ambiguous representation",
    authority="Consumer Protection Act, 2019",
    citation="Section 2(28) — misleading advertisement",
    obligation=(
        "An advertisement is misleading if it falsely describes a product, makes a false guarantee, or "
        "conveys an express or implied representation that would mislead a reasonable consumer about "
        "the nature, quantity, quality or price of the goods."
    ),
    severity="high",
    remediation=(
        "Make the qualifier explicit and adjacent to the claim, and remove any implication the product "
        "does not support."
    ),
    patterns=(
        r"\b(miracle|magic|instant(ly)?\s+(results?|glow|fairness)|overnight\s+(results?|glow))\b",
        r"\b(works?\s+like\s+magic|secret\s+formula|doctors?\s+hate\s+this)\b",
    ),
    tags=("claims",),
)

COMPARATIVE = _g(
    code="IN-ASCI-I4-COMPARATIVE",
    title="Comparative or superlative claim without evidence",
    authority="Advertising Standards Council of India (ASCI) Code",
    citation="Chapter I.4 — comparisons and superlatives",
    obligation=(
        "Superlatives ('best', 'No.1', 'cheapest') and direct comparisons must be true, verifiable and "
        "based on a named, objective study. A comparison must not disparage a competitor's product "
        "without factual basis."
    ),
    severity="medium",
    remediation=(
        "Name the study and the year, or soften to a non-comparative benefit. Drop 'No.1' unless the "
        "ranking, its scope and its date are stated."
    ),
    patterns=(
        r"\b(best\s+(in|seller|selling)|no\.?\s*1|number\s+one|#1|cheapest|fastest|most\s+(effective|trusted|popular))\b",
        r"\bbetter\s+than\s+(every|all|any)\b",
        r"\b(outperforms?|beats?)\s+\w+",
    ),
    tags=("claims",),
)

DISCLAIMER_CLAUSE = _g(
    code="IN-CCPA-DISCLAIMER-2022",
    title="Required disclaimer is missing, or not as prominent as the claim",
    authority="Central Consumer Protection Authority",
    citation="Prevention of Misleading Advertisements Guidelines, 2022",
    obligation=(
        "Where a claim needs a disclaimer, the disclaimer must be in the same language as the claim, "
        "legible and for the same duration as the claim, and not hidden in fine print. Conditions such "
        "as 'results may vary' or 'terms apply' cannot be smaller than the promise they qualify."
    ),
    severity="medium",
    remediation=(
        "Place the disclaimer next to the claim, in the same language and weight, and keep it on screen "
        "for as long as the claim is on screen."
    ),
    patterns=(
        r"\b(clinically\s+proven|dermatologically\s+tested|guaranteed?|100\s*%|visible\s+results?|proven\s+results?)\b",
    ),
    requires_absent=("terms and conditions", "t&c", "results may vary", "results vary", "*", "conditions apply"),
    tags=("claims", "disclosure"),
)

BAIT_URGENCY = _g(
    code="IN-CPA-BAIT",
    title="Bait or unqualified urgency offer",
    authority="Consumer Protection Act, 2019",
    citation="Section 2(28) — misleading advertisement; bait advertising",
    obligation=(
        "An offer that creates urgency must be genuine and its conditions stated: the period, the stock, "
        "the eligibility and whether a substitute will be offered. Advertising a price or discount that "
        "is not actually available is bait advertising."
    ),
    severity="medium",
    remediation=(
        "State the offer period, the stock basis and the eligibility in the same creative, or drop the "
        "urgency wording."
    ),
    patterns=(
        r"\b(only\s+today|last\s+chance|while\s+stocks?\s+last|hurry|limited\s+(time|period|stock))\b",
        r"\b(\d{1,2}\s*%\s*off)\b",
    ),
    requires_absent=("terms", "t&c", "conditions", "valid till", "valid until", "onwards", "from "),
    tags=("offer",),
)

TESTIMONIAL = _g(
    code="IN-ASCI-TESTIMONIAL",
    title="Testimonial or before-after claim without basis",
    authority="Advertising Standards Council of India (ASCI) Code",
    citation="Chapter I.4 — testimonials and endorsements",
    obligation=(
        "Testimonials must be genuine, from real users, and must not imply results that the average "
        "consumer cannot expect. Before/after visuals must be unretouched and representative."
    ),
    severity="low",
    remediation=(
        "Keep the proof of the testimonial on file, add 'individual results may vary', and never "
        "retouch before/after imagery."
    ),
    patterns=(
        r"\b(before\s*(and|&)\s*after|real\s+results?|customer\s+says?|i\s+lost\s+\d+\s*kg)\b",
    ),
    tags=("claims",),
)

INFLUENCER_DISCLOSURE = _g(
    code="IN-ASCI-INFLUENCER-2021",
    title="Paid partnership not disclosed",
    authority="Advertising Standards Council of India",
    citation="Guidelines for Influencer Advertising in Digital Media, 2021",
    obligation=(
        "A creator disclosing a paid or barter partnership must label it clearly and upfront, in the "
        "same language as the content — '#ad', '#sponsored' or 'paid partnership' — not buried in "
        "hashtags or a 'collab' tag alone."
    ),
    severity="high",
    remediation=(
        "Add '#ad' or 'paid partnership with <brand>' in the first two lines of the caption and as an "
        "on-screen label for the whole video, in the same language as the content."
    ),
    channels=("instagram_caption", "linkedin_post", "video_reel", "youtube", "social_post"),
    patterns=(
        r"\b(collab|collaboration|sponsored|barter|gifted|pr\s+package|ambassador)\b",
    ),
    requires_absent=("#ad", "#sponsored", "paid partnership", "advertisement", "विज्ञापन", "जाहिरात"),
    tags=("disclosure", "creator"),
)


# --------------------------------------------------------------------------
# Commercial and technical
# --------------------------------------------------------------------------
LEGAL_METROLOGY = _g(
    code="IN-LM-PACKAGED-2011",
    title="Price shown without mandatory package declaration",
    authority="Legal Metrology Act, 2009 and Packaged Commodities Rules, 2011",
    citation="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6",
    obligation=(
        "A pre-packaged product offered for sale must declare the maximum retail price, the net quantity, "
        "the manufacturer or packer details and the consumer-care contact. Advertising a price without "
        "stating whether it is the MRP and tax-inclusive is a declaration gap."
    ),
    severity="medium",
    remediation=(
        "Show the price as 'MRP ₹X (inclusive of all taxes)' and include the net quantity in the same "
        "creative or on the pack."
    ),
    channels=("product_page", "website_banner", "print_poster", "email"),
    patterns=(r"(₹|rs\.?|inr)\s*\d",),
    requires_absent=("inclusive of all taxes", "incl. taxes", "mrp", "net quantity"),
    tags=("commerce",),
)

BIS_MARK = _g(
    code="IN-BIS-S17",
    title="Standard mark or certification claim without a licence",
    authority="Bureau of Indian Standards Act, 2016",
    citation="Section 17 — improper use of a standard mark",
    obligation=(
        "Using the ISI mark, 'BIS certified', 'hallmark', 'AGMARK' or 'FSSAI approved' without a valid "
        "licence is an offence. A certification claim must carry the licence number."
    ),
    severity="high",
    remediation=(
        "Add the licence number next to the mark, or remove the certification claim until the licence is "
        "issued."
    ),
    patterns=(
        r"\b(isi\s+(mark|certified)|bis\s+(certified|approved)|hallmark(ed)?|agmark|fssai\s+(approved|certified))\b",
    ),
    requires_absent=("licence no", "license no", "lic. no", "licence:", "license:"),
    tags=("commerce", "regulated"),
)

TRADEMARK = _g(
    code="IN-TM-S29",
    title="Third-party brand name or mark used without permission",
    authority="Trade Marks Act, 1999",
    citation="Section 29 — infringement of registered trade marks",
    obligation=(
        "Using another brand's name, logo or distinctive mark in your creative, even comparatively, can "
        "infringe a registered trade mark and implies an association that does not exist."
    ),
    severity="medium",
    remediation=(
        "Remove the third-party mark, or replace it with a generic description and get written permission "
        "before any comparative use."
    ),
    patterns=(
        r"\b(nike|adidas|puma|gucci|rolex|chanel|dior|louis\s+vuitton|apple|iphone|samsung|boat|l'?oreal|dove|nivea|amazon|flipkart|zomato|swiggy)\b",
    ),
    tags=("ip",),
)

PERSONAL_DATA = _g(
    code="IN-DPDP-2023",
    title="Personal data in the creative",
    authority="Digital Personal Data Protection Act, 2023",
    citation="Sections 4 and 6 — consent and lawful processing",
    obligation=(
        "Publishing an identifiable person's email, phone number, address or identity requires their "
        "consent for that purpose. Creative is a publication, so a customer's contact details in an ad "
        "are a processing event without a stated basis."
    ),
    severity="high",
    remediation=(
        "Remove or mask the personal data before publishing. If the person is a testimonial subject, "
        "keep a signed consent on file and name the purpose."
    ),
    patterns=(
        r"[\w.+-]+@[\w-]+\.[\w.]{2,}",
        r"(?:\+91[\s-]?)?[6-9]\d{9}\b",
        r"\b\d{4}\s?\d{4}\s?\d{4}\b",
    ),
    tags=("privacy", "regulated"),
)

SYNTHETIC_MEDIA = _g(
    code="IN-ITR-SYNTHETIC",
    title="AI-generated or synthetic media not disclosed",
    authority="Information Technology (Intermediary Guidelines and Digital Media Ethics Code) Rules, 2021",
    citation="Rule 3(1)(b) with the MeitY advisory on synthetic content (2024)",
    obligation=(
        "Synthetic or AI-generated media that could be mistaken for a real person or event must be "
        "labelled, and must not impersonate a person without consent. Platforms are required to remove "
        "such content when it is deceptive."
    ),
    severity="high",
    remediation=(
        "Add a clear 'AI-generated' label on the creative and in the caption, and never synthesise a real "
        "person's likeness or voice without written consent."
    ),
    patterns=(
        r"\b(ai[- ]generated|deepfake|synthetic\s+media|voice\s+clone|cloned\s+voice|ai\s+avatar)\b",
    ),
    requires_absent=("ai-generated", "ai generated", "synthetic", "label"),
    tags=("disclosure", "regulated"),
)

TOBACCO_ALCOHOL = _g(
    code="IN-COTPA-S5",
    title="Tobacco or alcohol promotion",
    authority="Cigarettes and Other Tobacco Products Act, 2003",
    citation="Section 5 — prohibition of advertisement and promotion",
    obligation=(
        "Direct and indirect advertisement of cigarettes and other tobacco products is prohibited. "
        "Alcohol promotion is restricted by state excise law and the ASCI Code, and cannot target minors "
        "or imply health benefits."
    ),
    severity="critical",
    remediation=(
        "Remove the product from the creative entirely. Surrogate advertising that promotes a brand "
        "sharing a tobacco or alcohol identity is treated as the advertisement itself."
    ),
    patterns=(
        r"\b(cigarettes?|beedi|bidi|tobacco|gutkha|pan\s+masala|vape|vaping)\b",
        r"\b(whisk(e)?y|vodka|beer|rum|gin|wine|liquor|alcohol)\b",
    ),
    tags=("regulated", "restricted"),
)

FINANCIAL_RETURNS = _g(
    code="IN-SEBI-RETURNS",
    title="Assured or guaranteed investment return",
    authority="Securities and Exchange Board of India / Reserve Bank of India",
    citation="SEBI (Mutual Funds) Regulations, 1996 — advertising code; RBI Fair Practices Code",
    obligation=(
        "No advertisement may promise or imply assured returns on a market-linked product. Past "
        "performance must carry the standard warning that it is not indicative of future results, and "
        "the scheme's risk factors must be shown."
    ),
    severity="critical",
    remediation=(
        "Remove the return promise, add the standard past-performance disclaimer and the risk-factor "
        "statement, and route the creative to a compliance reviewer."
    ),
    sectors=("finance", "fintech", "insurance", "investing", "banking"),
    patterns=(
        r"\b(assured|guaranteed|fixed)\s+(returns?|profits?|income)\b",
        r"\b\d{1,3}\s*%\s*(p\.?a\.?|annual(ised)?|returns?|interest)\b",
        r"\b(double\s+your\s+money|risk[- ]free\s+investment)\b",
    ),
    tags=("regulated", "finance"),
)

GREENWASHING = _g(
    code="IN-CCPA-GREENWASH-2024",
    title="Unsubstantiated environmental claim",
    authority="Central Consumer Protection Authority",
    citation="Guidelines for Prevention and Regulation of Greenwashing, 2024",
    obligation=(
        "Terms such as 'eco-friendly', '100% natural', 'biodegradable', 'carbon neutral' and "
        "'sustainable' must be substantiated with verifiable evidence and must state the specific aspect "
        "of the product they refer to."
    ),
    severity="medium",
    remediation=(
        "Name the specific attribute and the evidence ('pack made from 60% recycled paper, certified by "
        "X'), or remove the environmental claim."
    ),
    patterns=(
        r"\b(eco[- ]friendly|environment[- ]friendly|green|sustainable|carbon[- ]neutral|biodegradable|compostable)\b",
        r"\b100\s*%\s*(natural|organic|recycled)\b",
    ),
    tags=("claims", "environment"),
)

CHILDREN = _g(
    code="IN-ASCI-CHILDREN",
    title="Advertising addressed to children",
    authority="Advertising Standards Council of India (ASCI) Code",
    citation="Chapter III — advertising to children",
    obligation=(
        "Advertising that addresses children must not exploit their inexperience, must not suggest that "
        "the product gives a physical, social or psychological advantage, and must not urge them to ask "
        "parents to buy."
    ),
    severity="high",
    remediation=(
        "Remove the direct appeal to the child, drop 'ask your parents to buy' style prompts, and add an "
        "age-appropriate qualifier."
    ),
    patterns=(
        r"\b(kids?|children|toddlers?|school\s+(kids?|children)|teens?)\b[^.!?]{0,40}\b(buy|ask|get|win|be\s+the\s+best|smartest)\b",
        r"\bask\s+your\s+(mom|dad|parents)\b",
    ),
    tags=("children",),
)


GUIDELINES: tuple[Guideline, ...] = (
    CURE_CLAIMS,
    THERAPEUTIC_COSMETIC,
    CLINICAL_SUBSTANTIATION,
    DURATION_CLAIM,
    GUARANTEE,
    FOOD_HEALTH,
    MISLEADING,
    COMPARATIVE,
    DISCLAIMER_CLAUSE,
    BAIT_URGENCY,
    TESTIMONIAL,
    INFLUENCER_DISCLOSURE,
    LEGAL_METROLOGY,
    BIS_MARK,
    TRADEMARK,
    PERSONAL_DATA,
    SYNTHETIC_MEDIA,
    TOBACCO_ALCOHOL,
    FINANCIAL_RETURNS,
    GREENWASHING,
    CHILDREN,
)

BY_CODE: dict[str, Guideline] = {g.code: g for g in GUIDELINES}


def get(code: str) -> Guideline | None:
    return BY_CODE.get(code)


def applicable(sector: str, channel: str) -> list[Guideline]:
    return [g for g in GUIDELINES if g.applies_to(sector, channel)]


def catalogue() -> list[dict]:
    return [
        {
            "code": g.code,
            "title": g.title,
            "authority": g.authority,
            "citation": g.citation,
            "obligation": g.obligation,
            "severity": g.severity,
            "remediation": g.remediation,
            "sectors": list(g.sectors),
            "channels": list(g.channels),
            "tags": list(g.tags),
        }
        for g in GUIDELINES
    ]
