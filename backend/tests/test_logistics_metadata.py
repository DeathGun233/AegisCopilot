from __future__ import annotations

from app.services.logistics_metadata import extract_logistics_metadata


def test_extracts_customs_metadata_from_germany_ddp_battery_title() -> None:
    metadata = extract_logistics_metadata("德国 DDP 带电产品清关资料，需要 MSDS 和 UN38.3。")

    assert metadata["country"] == "DE"
    assert metadata["region"] == "EU"
    assert metadata["incoterm"] == "DDP"
    assert metadata["product_category"] == "带电"
    assert metadata["doc_type"] == "customs_rule"


def test_extracts_pure_battery_before_general_battery_category() -> None:
    metadata = extract_logistics_metadata("德国 DDP 纯电池不接，带电产品需单独确认。")

    assert metadata["product_category"] == "纯电池"
    assert metadata["product_categories"] == ["纯电池", "带电"]


def test_explicit_table_category_takes_priority_over_restriction_text() -> None:
    metadata = extract_logistics_metadata("品类：带电 限制：纯电池不接，内置电池需单独确认")

    assert metadata["product_category"] == "带电"
    assert metadata["product_categories"] == ["带电", "纯电池"]


def test_extracts_fee_metadata_from_us_fba_remote_surcharge_text() -> None:
    metadata = extract_logistics_metadata("美国 FBA 偏远附加费表，生效日期：2026-05-01，币种 USD。")

    assert metadata["country"] == "US"
    assert metadata["region"] == "North America"
    assert metadata["channel"] == "FBA"
    assert metadata["doc_type"] == "price_table"
    assert metadata["effective_date"] == "2026-05-01"
    assert metadata["currency"] == "USD"


def test_extracts_eu_vat_rule_metadata_and_preserves_structure_fields() -> None:
    metadata = extract_logistics_metadata(
        "欧盟 VAT 申报规则，适用于 DAP 渠道。",
        base_metadata={
            "section_path": "欧盟规则 > VAT 申报",
            "table_name": "VAT 申报资料表",
        },
    )

    assert metadata["region"] == "EU"
    assert metadata["incoterm"] == "DAP"
    assert metadata["doc_type"] == "customs_rule"
    assert metadata["section_path"] == "欧盟规则 > VAT 申报"
    assert metadata["table_name"] == "VAT 申报资料表"
