import asyncio
from typing import List
from pathlib import Path

import chromadb
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader

from app.core.config import settings
from app.db.models import Document
import dashscope
from dashscope import TextEmbedding

dashscope.api_key = settings.DASHSCOPE_API_KEY

UPLOAD_DIR = Path(settings.UPLOAD_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def get_chroma_client():
    return chromadb.HttpClient(host=settings.CHROMA_HOST, port=settings.CHROMA_PORT)


def get_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(
        name="knowledge_base",
        metadata={"hnsw:space": "cosine"}
    )


def embed_texts(texts: List[str]) -> List[List[float]]:
    """调用阿里云 DashScope 向量模型"""
    embeddings = []
    batch_size = 25  # DashScope 单次最多 25 条
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        resp = TextEmbedding.call(
            model=settings.EMBEDDING_MODEL,
            input=batch
        )
        if resp.status_code != 200:
            raise RuntimeError(f"向量化失败: {resp.message}")
        for item in resp.output["embeddings"]:
            embeddings.append(item["embedding"])
    return embeddings


def load_document(file_path: str, filename: str):
    """根据文件类型加载文档"""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        loader = PyPDFLoader(file_path)
    elif ext == ".docx":
        loader = Docx2txtLoader(file_path)
    else:  # .txt .md
        loader = TextLoader(file_path, encoding="utf-8")
    return loader.load()


async def process_document(doc_id: str, file_path: str, original_filename: str, db_session):
    """异步处理文档：解析 → 切片 → 向量化 → 存入 ChromaDB"""
    from sqlalchemy import update

    async def update_status(status, chunk_count=0, error=None):
        await db_session.execute(
            update(Document)
            .where(Document.id == doc_id)
            .values(status=status, chunk_count=chunk_count, error_message=error)
        )
        await db_session.commit()

    try:
        # 1. 加载文档
        docs = await asyncio.to_thread(load_document, file_path, original_filename)
        full_text = "\n".join([d.page_content for d in docs])

        # 2. 切片
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]
        )
        chunks = splitter.split_text(full_text)
        if not chunks:
            await update_status("failed", error="文档内容为空")
            return

        # 3. 向量化
        embeddings = await asyncio.to_thread(embed_texts, chunks)

        # 4. 存入 ChromaDB
        collection = await asyncio.to_thread(get_collection)
        ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
        # source_type=upload 与爬虫来源区分（架构 §7.3）；module 可空，运营补录时填写
        metadatas = [{"doc_id": doc_id, "source": original_filename, "chunk_index": i,
                      "source_type": "upload", "module": ""}
                     for i in range(len(chunks))]

        await asyncio.to_thread(
            collection.add,
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas
        )

        await update_status("ready", chunk_count=len(chunks))

    except Exception as e:
        await update_status("failed", error=str(e))


async def delete_document_vectors(doc_id: str):
    """从 ChromaDB 删除某文档的所有向量"""
    collection = await asyncio.to_thread(get_collection)
    results = await asyncio.to_thread(
        collection.get,
        where={"doc_id": doc_id}
    )
    if results["ids"]:
        await asyncio.to_thread(collection.delete, ids=results["ids"])
