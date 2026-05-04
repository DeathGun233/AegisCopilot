from __future__ import annotations

import json
from pathlib import Path

from app.services.text import split_into_structured_chunks


def test_markdown_headings_populate_logistics_section_path() -> None:
    text = """
# 欧洲 DDP 渠道
## 德国
### 带电产品
德国 DDP 带电产品需要 MSDS、UN38.3、运输鉴定书；纯电池不接。
"""

    chunks = split_into_structured_chunks(text)
    battery = next(chunk for chunk in chunks if "UN38.3" in chunk.text)

    assert battery.metadata["section_path"] == "欧洲 DDP 渠道 > 德国 > 带电产品"
    assert battery.metadata["section_path_parts"] == ["欧洲 DDP 渠道", "德国", "带电产品"]
    assert battery.metadata["section_level"] == 3


def test_markdown_table_rows_become_atomic_rule_chunks_with_headers() -> None:
    text = """
# 欧洲 DDP 渠道清关资料表
## 带电产品清关要求
| 国家/地区 | 渠道 | 品类 | 要求 | 限制 | 生效日期 |
| --- | --- | --- | --- | --- | --- |
| 德国 | DDP空派 | 带电 | 需要 MSDS、UN38.3、运输鉴定书 | 纯电池不接 | 2026-05-01 |
| 法国 | DDP空派 | 液体 | 需要成分说明 | 单票需确认 | 2026-05-01 |
"""

    chunks = split_into_structured_chunks(text)
    table_rows = [chunk for chunk in chunks if chunk.metadata.get("block_type") == "table_row"]

    assert len(table_rows) == 2
    germany = table_rows[0]
    assert germany.metadata["section_path"] == "欧洲 DDP 渠道清关资料表 > 带电产品清关要求"
    assert germany.metadata["table_name"] == "带电产品清关要求"
    assert germany.metadata["row_id"] == "row-de-ddp-battery"
    assert "国家/地区：德国" in germany.text
    assert "要求：需要 MSDS、UN38.3、运输鉴定书" in germany.text
    assert "生效日期：2026-05-01" in germany.text


def test_logistics_qa_expected_table_row_matches_generated_markdown_row_id() -> None:
    text = """
# 欧洲 DDP 渠道清关资料表
## 德国
### 带电产品
| 国家/地区 | 渠道 | 品类 | 要求 | 限制 | 生效日期 |
| --- | --- | --- | --- | --- | --- |
| 德国 | DDP空派 | 带电 | 需要 MSDS、UN38.3、运输鉴定书 | 纯电池不接，内置电池需单独确认 | 2026-05-01 |
"""

    chunks = split_into_structured_chunks(text)
    germany = next(chunk for chunk in chunks if chunk.metadata.get("block_type") == "table_row")
    dataset_path = Path(__file__).resolve().parents[2] / "evaluation" / "logistics_qa.json"
    logistics_cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    expected_rows = {
        row_id
        for item in logistics_cases
        if item["id"] == "logistics-001"
        for row_id in item["expected_table_rows"]
    }

    assert germany.metadata["row_id"] == "row-de-ddp-battery"
    assert germany.metadata["row_id"] in expected_rows


def test_us_fba_remote_fee_row_id_matches_logistics_eval_dataset() -> None:
    text = """
# 美国 FBA 附加费表
## 偏远附加费
| 国家/地区 | 渠道 | 费用项 | 币种 | 计费规则 | 生效日期 |
| --- | --- | --- | --- | --- | --- |
| 美国 | FBA | 偏远附加费 | USD | 命中偏远邮编时按票加收 | 2026-05-01 |
"""

    chunks = split_into_structured_chunks(text)
    fee = next(chunk for chunk in chunks if chunk.metadata.get("block_type") == "table_row")
    dataset_path = Path(__file__).resolve().parents[2] / "evaluation" / "logistics_qa.json"
    logistics_cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    expected_rows = {
        row_id
        for item in logistics_cases
        if item["id"] == "logistics-002"
        for row_id in item["expected_table_rows"]
    }

    assert fee.metadata["row_id"] == "row-us-fba-remote-fee"
    assert fee.metadata["row_id"] in expected_rows


def test_markdown_contiguous_lists_are_kept_as_single_rule_block() -> None:
    text = """
# 禁限运品规则
## 德国 DDP
- 纯电池不接。
- 液体需提供成分说明并单独确认。
- 粉末类产品需提供 MSDS。
"""

    chunks = split_into_structured_chunks(text)
    lists = [chunk for chunk in chunks if chunk.metadata.get("block_type") == "list"]

    assert len(lists) == 1
    assert lists[0].metadata["section_path"] == "禁限运品规则 > 德国 DDP"
    assert "纯电池不接" in lists[0].text
    assert "液体需提供成分说明" in lists[0].text
    assert "粉末类产品需提供 MSDS" in lists[0].text
