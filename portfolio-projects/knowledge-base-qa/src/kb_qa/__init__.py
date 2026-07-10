"""kb_qa —— 企业知识库问答系统（生产级 RAG）。

三层架构：
    ingest   数据层：文档加载 → 结构感知分块 → 向量化 → Chroma 持久化（增量缓存）
    retrieve 检索层：BM25+向量混合召回 → 智谱 reranker 重排 → 引用溯源
    generate 生成层：防幻觉 prompt → 流式回答 → 多轮记忆
独立评估层：ragas 四指标量化检索/生成质量。
"""
