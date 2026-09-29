"""The creative-strategy vocabulary every ad gets tagged with.

Built from the Creative System session (Concept vs Variant, the Angle Library,
Hook Architecture, Funnel-Stage Creative, the Offer as a Variable). Funnel stage is deliberately
not tagged: TOF/MOF/BOF depends on each brand's own funnel, so it does not compare. Keep the
keys stable: they are stored in data/ and compared week over week.
"""

ANGLE_FAMILIES = {
    "problem_agitate": "Problem agitate: names the customer's pain and twists the knife before the fix",
    "proof_efficacy": "Proof & efficacy: results, clinical claims, numbers, demonstrations that it works",
    "price_justification": "Price justification: why it is worth the money, cost-per-use, value framing",
    "social_proof": "Social proof: reviews, ratings, customer counts, testimonials, 'bestseller'",
    "founder_origin": "Founder & origin: the founder, the brand story, why we exist",
    "comparison": "Comparison: us vs them / vs the old way / vs alternatives",
    "objection_handling": "Objection handling: answers a specific doubt (safe? side effects? sensitive skin? does it last?)",
    "occasion_gifting": "Occasion & gifting: festivals, gifting, seasons, life moments",
    "ingredient_transparency": "Ingredient & transparency: hero ingredient, formulation, what's inside / not inside",
    "offer_led": "Offer-led: the discount/sale/deal IS the argument",
    "launch_new": "Launch & new: announcing a new product, variant or drop",
    "brand_lifestyle": "Brand & lifestyle: mood, identity, aspiration; no specific argument",
}

HOOK_FAMILIES = {
    "claim": "A specific, surprising assertion",
    "problem_statement": "Names the viewer's situation first",
    "pattern_interrupt": "Visual/auditory discontinuity unrelated to the message",
    "question": "Direct question to the viewer",
    "demonstration": "Shows the product working immediately",
    "negative": "'Stop doing X' / 'why your Y isn't working'",
    "social_proof_open": "Third-party voice or review from frame one",
    "offer_open": "Leads with the discount/price",
    "product_hero": "Just the product / brand name up front",
}

CREATIVE_STYLES = {
    "ugc_creator": "UGC / creator talking to camera, phone-shot",
    "founder_led": "Founder on camera",
    "celebrity": "Celebrity or big-name influencer",
    "studio_product": "Polished studio product shot / packshot",
    "lifestyle": "Lifestyle imagery, model in context",
    "testimonial_review": "Review screenshot / testimonial card",
    "before_after": "Before/after or result visual",
    "infographic": "Infographic, comparison chart, benefit callouts",
    "text_meme": "Text-heavy, meme, native-post look",
    "catalog": "Catalog / dynamic product ad",
    "animation": "Motion graphics / animation",
    "other": "Anything else",
}

OFFER_TYPES = ["none", "percent_off", "flat_off", "bogo_bundle", "free_gift",
               "free_shipping", "sale_event", "coupon_code", "price_point"]

LANGUAGES = ["english", "hindi", "hinglish", "regional", "other"]

MEDIA_LABELS = {"static": "Static", "video": "Video", "carousel": "Carousel", "catalog": "Catalog/DPA"}


def label(key: str) -> str:
    """Short human label for any taxonomy key."""
    if key in ANGLE_FAMILIES:
        return ANGLE_FAMILIES[key].split(":")[0]
    return MEDIA_LABELS.get(key, (key or "n/a").replace("_", " ").capitalize())


def prompt_block() -> str:
    def fmt(d):
        return "\n".join(f"  - {k}: {v}" for k, v in d.items())
    return (
        f"angle_family (the ARGUMENT, pick one):\n{fmt(ANGLE_FAMILIES)}\n\n"
        f"hook_family (how the first line/frame opens, pick one):\n{fmt(HOOK_FAMILIES)}\n\n"
        f"creative_style (the execution):\n{fmt(CREATIVE_STYLES)}\n\n"
        f"offer_type: one of {OFFER_TYPES}\n"
        f"language: one of {LANGUAGES} (hinglish = Hindi words in Latin script or mixed)\n"
    )
