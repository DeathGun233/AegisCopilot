from __future__ import annotations

from .config import settings
from .deps import get_container


SAMPLE_DOCS = [
    {
        "title": "员工请假制度",
        "content": """
员工请假需至少提前 1 个工作日发起申请。
病假需要补充医院证明，年假需由直属主管审批后同步给 HR。
连续请假超过 3 天时，需要部门负责人额外审批。
        """,
        "department": "hr",
        "tags": ["人事", "请假"],
    },
    {
        "title": "差旅报销流程",
        "content": """
差旅报销需在出差结束后 5 个工作日内提交。
员工需上传发票、行程单和费用明细，直属主管审批后由财务复核。
报销金额将在财务复核通过后的最近一个付款周期内打款。
        """,
        "department": "finance",
        "tags": ["财务", "报销"],
    },
    {
        "title": "生产发布规范",
        "content": """
所有生产发布必须完成测试、风险评估和回滚预案。
发布前需提交变更单，并在发布群同步影响范围、负责人和回滚方案。
高风险变更需要值班同学在线观察 30 分钟。
        """,
        "department": "engineering",
        "tags": ["发布", "上线"],
    },
]


def main() -> None:
    container = get_container()
    if container.document_service.list_documents():
        print("示例文档已存在，跳过初始化。")
        return
    should_index = not (
        settings.vector_store_provider == "milvus"
        and not container.embedding_service.is_enabled()
    )
    for item in SAMPLE_DOCS:
        document = container.document_service.create_document(
            title=item["title"],
            content=item["content"],
            source_type="seed",
            department=item["department"],
            version="v1",
            tags=item["tags"],
        )
        if not should_index:
            continue
        container.document_service.index_document(document.id)
    if should_index:
        print("已初始化示例文档。")
    else:
        print("已初始化示例文档；当前 Milvus 模式未启用 embedding，已跳过启动期示例索引。")


if __name__ == "__main__":
    main()
