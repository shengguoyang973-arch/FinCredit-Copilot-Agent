"""Build or refresh the configured policy vector collection."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.bootstrap import initialize_application  # noqa: E402
from app.config import get_settings, validate_settings  # noqa: E402
from app.embedding import get_embedding_adapter  # noqa: E402
from app.hybrid_retrieval import HybridPolicyRetriever  # noqa: E402
from app.knowledge_store import list_policies  # noqa: E402
from app.vector_store import get_vector_store  # noqa: E402


def main() -> int:
    settings = get_settings()
    errors = validate_settings(settings)
    if errors:
        raise SystemExit("配置无效：" + "；".join(errors))
    initialize_application()
    embedding = get_embedding_adapter(settings)
    store = get_vector_store(embedding, settings)
    retriever = HybridPolicyRetriever(embedding=embedding, store=store, chunk_size=settings.rag_chunk_size)
    policies = list_policies()
    retriever.index(policies)
    print({
        "status": "indexed", "policy_count": len(policies), "chunk_count": store.count(),
        "embedding_provider": embedding.name, "dimensions": embedding.dimensions,
        "vector_store": store.backend,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
