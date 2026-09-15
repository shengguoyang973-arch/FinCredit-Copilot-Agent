from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from app.database import connection as database_connection, database_path
from app.rule_store import required_materials

ALLOWED_TYPES = {"business_license", "financial_statement", "bank_statement"}


def _connection() -> sqlite3.Connection:
    return database_connection()


def initialize() -> None:
    return None


def extract_fields(document_type: str, content: bytes) -> dict:
    """Conservative text extraction for demo documents; no OCR or inference is claimed."""
    text = content.decode("utf-8", errors="replace")[:100_000]
    extracted: dict[str, str | float | int] = {"text_preview": text[:500]}
    patterns = {
        "company_name": r"(?:企业名称|公司名称)\s*[:：]\s*([^\n,，]{2,80})",
        "registration_no": r"(?:统一社会信用代码|注册号)\s*[:：]\s*([A-Za-z0-9*]{8,30})",
        "annual_revenue": r"(?:营业收入|年度营收)\s*[:：]\s*([\d,.]+)",
        "debt_ratio": r"(?:资产负债率|负债率)\s*[:：]\s*([\d.]+)\s*%",
        "account_balance": r"(?:期末余额|账户余额)\s*[:：]\s*([\d,.]+)",
    }
    allowed = {
        "business_license": {"company_name", "registration_no"},
        "financial_statement": {"annual_revenue", "debt_ratio"},
        "bank_statement": {"account_balance"},
    }[document_type]
    for key in allowed:
        match = re.search(patterns[key], text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            extracted[key] = float(value.replace(",", "")) if key in {"annual_revenue", "debt_ratio", "account_balance"} else value
    return extracted


def save_document(application_id: str, document_type: str, filename: str, content_type: str, content: bytes, imported_by: str) -> dict:
    if document_type not in ALLOWED_TYPES:
        raise ValueError("不支持的材料类型")
    if not content:
        raise ValueError("材料内容不能为空")
    document_id = f"DOC-{uuid4().hex[:12].upper()}"
    stored_path = database_path().parent / "uploads" / f"{document_id}.bin"
    stored_path.parent.mkdir(exist_ok=True)
    stored_path.write_bytes(content)
    item = {
        "id": document_id, "application_id": application_id, "document_type": document_type,
        "filename": filename, "content_type": content_type, "byte_size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(), "extracted": extract_fields(document_type, content),
        "imported_by": imported_by, "imported_at": datetime.now(timezone.utc).isoformat(),
    }
    with _connection() as connection:
        connection.execute("INSERT INTO application_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item["id"], item["application_id"], item["document_type"], item["filename"], item["content_type"], item["byte_size"], item["sha256"], json.dumps(item["extracted"], ensure_ascii=False), item["imported_by"], item["imported_at"]))
    return item


def list_documents(application_id: str) -> list[dict]:
    with _connection() as connection:
        rows = connection.execute("SELECT * FROM application_documents WHERE application_id = ? ORDER BY imported_at DESC", (application_id,)).fetchall()
    return [{"id": row["id"], "application_id": row["application_id"], "document_type": row["document_type"], "filename": row["filename"], "content_type": row["content_type"], "byte_size": row["byte_size"], "sha256": row["sha256"], "extracted": json.loads(row["extracted_json"]), "imported_by": row["imported_by"], "imported_at": row["imported_at"]} for row in rows]


def material_check(application_id: str) -> dict:
    documents = list_documents(application_id)
    present = {document["document_type"] for document in documents}
    required = required_materials()
    missing = [{"type": key, "label": label} for key, label in required.items() if key not in present]
    return {"documents": documents, "missing": missing, "complete": not missing}
