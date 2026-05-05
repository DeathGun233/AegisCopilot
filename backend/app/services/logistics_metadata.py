from __future__ import annotations

import re
from typing import Any


COUNTRY_RULES: list[tuple[str, str, str]] = [
    ("DE", "EU", "德国|德國|germany|deutschland"),
    ("US", "North America", "美国|美國|usa|u\\.s\\.|united states"),
    ("UK", "Europe", "英国|英國|uk|united kingdom"),
    ("CA", "North America", "加拿大|canada"),
    ("AU", "Oceania", "澳大利亚|澳洲|australia"),
    ("JP", "Asia", "日本|japan"),
    ("FR", "EU", "法国|法國|france"),
    ("IT", "EU", "意大利|italy"),
    ("ES", "EU", "西班牙|spain"),
]

REGION_RULES: list[tuple[str, str]] = [
    ("EU", "欧盟|欧洲|european union|\\beu\\b"),
    ("North America", "北美|north america"),
    ("Southeast Asia", "东南亚|southeast asia"),
]

PRODUCT_CATEGORIES = ("纯电池", "带电", "液体", "粉末", "食品", "化妆品", "纺织品", "普货")
INCOTERMS = ("DDP", "DAP", "EXW", "FOB")
CHANNELS = ("FBA空派", "FBA海派", "FBA卡派", "DDP空派", "DDP海派", "DHL", "UPS", "FedEx", "FBA", "邮政小包")
CURRENCIES = ("USD", "EUR", "CNY", "RMB", "GBP", "JPY")


def extract_logistics_metadata(text: str, *, base_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    source = " ".join(str(item) for item in (text, *(base_metadata or {}).values()) if item)
    lowered = source.lower()
    metadata: dict[str, Any] = dict(base_metadata or {})

    for country, region, pattern in COUNTRY_RULES:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            metadata.setdefault("country", country)
            metadata.setdefault("region", region)
            break

    if "region" not in metadata:
        for region, pattern in REGION_RULES:
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                metadata["region"] = region
                break

    for incoterm in INCOTERMS:
        if re.search(rf"\b{incoterm}\b", source, flags=re.IGNORECASE):
            metadata.setdefault("incoterm", incoterm)
            break

    for channel in CHANNELS:
        if re.search(re.escape(channel), source, flags=re.IGNORECASE):
            metadata.setdefault("channel", channel)
            break

    explicit_category = _extract_explicit_product_category(source)
    product_categories = []
    if explicit_category:
        product_categories.append(explicit_category)
    product_categories.extend(
        category for category in PRODUCT_CATEGORIES if category in source and category not in product_categories
    )
    if product_categories:
        metadata.setdefault("product_categories", product_categories)
        metadata.setdefault("product_category", product_categories[0])

    effective_date = _extract_effective_date(source)
    if effective_date:
        metadata.setdefault("effective_date", effective_date)

    for currency in CURRENCIES:
        if re.search(rf"\b{currency}\b", source, flags=re.IGNORECASE):
            metadata.setdefault("currency", "CNY" if currency == "RMB" else currency)
            break

    doc_type = _infer_doc_type(source)
    if doc_type:
        metadata.setdefault("doc_type", doc_type)

    return metadata


def _extract_effective_date(text: str) -> str:
    matched = re.search(r"(?:生效日期|生效|effective date)?[:：]?\s*(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", text)
    if not matched:
        return ""
    year, month, day = matched.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _extract_explicit_product_category(text: str) -> str:
    matched = re.search(r"(?:品类|产品品类|product_category|category)\s*[:：]\s*([^\s|，,；;\n]+)", text, flags=re.IGNORECASE)
    if not matched:
        return ""
    value = matched.group(1)
    for category in PRODUCT_CATEGORIES:
        if category in value:
            return category
    return ""


def _infer_doc_type(text: str) -> str:
    lowered = text.lower()
    if any(keyword in text for keyword in ("费用", "运费", "附加费", "价格表", "报价表")):
        return "price_table"
    if any(keyword in text for keyword in ("清关", "申报", "VAT", "vat", "关税", "海关")):
        return "customs_rule"
    if any(keyword in text for keyword in ("禁限运", "禁运", "不接", "限制")):
        return "policy"
    if any(keyword in text for keyword in ("赔付", "退件", "查验", "免责")):
        return "contract"
    if "faq" in lowered or "问答" in text:
        return "faq"
    if "sop" in lowered or "操作流程" in text:
        return "sop"
    if "公告" in text or "notice" in lowered:
        return "notice"
    return ""
