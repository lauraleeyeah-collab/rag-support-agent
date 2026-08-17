import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.base import get_db
from app.db.models import Document, User
from app.api.auth import require_admin
from app.services.doc_service import process_document, delete_document_vectors, UPLOAD_DIR
from app.schemas.schemas import DocumentOut
from app.core.config import settings

router = APIRouter(prefix="/knowledge", tags=["知识库"])


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin)
):
    result = await db.execute(select(Document).order_by(Document.created_at.desc()))
    return result.scalars().all()


@router.post("/upload", response_model=DocumentOut)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    # 检查文件类型
    ext = Path(file.filename).suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型，支持：{settings.ALLOWED_EXTENSIONS}")

    # 检查文件大小
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过 50MB 限制")

    # 保存文件到磁盘
    doc_id = str(uuid.uuid4())
    saved_filename = f"{doc_id}{ext}"
    file_path = UPLOAD_DIR / saved_filename
    file_path.write_bytes(content)

    # 创建数据库记录
    doc = Document(
        id=doc_id,
        filename=saved_filename,
        original_filename=file.filename,
        file_size=len(content),
        status="processing",
        uploaded_by=current_user.id
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # 后台异步处理文档
    background_tasks.add_task(
        process_document, doc_id, str(file_path), file.filename, db
    )

    return DocumentOut.model_validate(doc)


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin)
):
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 删除 ChromaDB 向量
    await delete_document_vectors(doc_id)

    # 删除磁盘文件
    file_path = UPLOAD_DIR / doc.filename
    if file_path.exists():
        file_path.unlink()

    # 删除数据库记录
    await db.delete(doc)
    await db.commit()

    return {"message": "删除成功"}
