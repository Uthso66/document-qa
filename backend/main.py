import os
import uuid
from io import BytesIO
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import chromadb
from chromadb.utils import embedding_functions
import ollama
from PyPDF2 import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Custom embedding function using Ollama
class OllamaEmbeddingFunction(embedding_functions.EmbeddingFunction):
    def __init__(self, model_name: str = "llama3.2:3b"):
        self.model_name = model_name

    def __call__(self, texts: List[str]) -> List[List[float]]:
        embeddings = []
        for text in texts:
            response = ollama.embeddings(model=self.model_name, prompt=text)
            embeddings.append(response['embedding'])
        return embeddings

# Chroma setup
chroma_client = chromadb.PersistentClient(path="./chroma_db")
embed_fn = OllamaEmbeddingFunction(model_name="llama3.2:3b")
collection = chroma_client.get_or_create_collection(
    name="documents",
    embedding_function=embed_fn
)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Track active document IDs (in-memory for simplicity)
active_doc_ids: List[str] = []

class QuestionRequest(BaseModel):
    question: str
    top_k: int = 3
    doc_ids: Optional[List[str]] = None  # Filter by specific documents

class AnswerResponse(BaseModel):
    answer: str
    sources: List[str]

def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(file_bytes))
    return "".join(page.extract_text() or "" for page in reader.pages)

def chunk_text(text: str, chunk_size=1000, overlap=200):
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
    return splitter.split_text(text)


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.endswith('.pdf'):
        raise HTTPException(400, "Only PDF files allowed")

    contents = await file.read()
    text = extract_text_from_pdf(contents)
    if not text.strip():
        raise HTTPException(400, "No text extracted from PDF")

    chunks = chunk_text(text)
    doc_id = str(uuid.uuid4())
    chunk_ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
    metadatas = [
        {"source": file.filename, "chunk_index": i, "doc_id": doc_id}
        for i in range(len(chunks))
    ]

    try:
        collection.add(ids=chunk_ids, documents=chunks, metadatas=metadatas)
    except Exception as e:
        print(f"ChromaDB add error: {e}")
        raise HTTPException(500, f"Failed to store embeddings: {str(e)}")

    active_doc_ids.append(doc_id)
    return {
        "message": f"Uploaded {file.filename} with {len(chunks)} chunks",
        "doc_id": doc_id
    }


@app.post("/ask", response_model=AnswerResponse)
async def ask_question(request: QuestionRequest):
    # Build filter for specific documents
    doc_ids = request.doc_ids if request.doc_ids else active_doc_ids

    where_filter = None
    if doc_ids:
        if len(doc_ids) == 1:
            where_filter = {"doc_id": doc_ids[0]}
        else:
            where_filter = {"doc_id": {"$in": doc_ids}}

    try:
        query_params = {
            "query_texts": [request.question],
            "n_results": request.top_k,
        }
        if where_filter:
            query_params["where"] = where_filter

        results = collection.query(**query_params)
    except Exception as e:
        print(f"ChromaDB query error: {e}")
        raise HTTPException(500, f"Failed to query documents: {str(e)}")

    if not results['documents'] or not results['documents'][0]:
        return AnswerResponse(answer="No relevant information found.", sources=[])

    context_chunks = results['documents'][0]
    sources = [
        f"{meta['source']} (chunk {meta['chunk_index']})"
        for meta in results['metadatas'][0]
    ]
    context = "\n\n---\n\n".join(context_chunks)

    prompt = f"""You are a helpful assistant that answers questions based ONLY on the provided context.
If the answer is not in the context, say "I don't have enough information to answer that."

Context:
{context}

Question: {request.question}

Answer:"""

    try:
        response = ollama.chat(
            model="llama3.2:3b",
            messages=[{"role": "user", "content": prompt}]
        )
        answer = response['message']['content'].strip()
    except Exception as e:
        print(f"Ollama error: {e}")
        raise HTTPException(500, f"Failed to generate answer: {str(e)}")

    return AnswerResponse(answer=answer, sources=sources)


@app.delete("/clear")
async def clear_documents():
    """Delete ALL documents from the collection and reset active docs."""
    global active_doc_ids
    try:
        # Delete and recreate the collection
        chroma_client.delete_collection("documents")
        global collection
        collection = chroma_client.get_or_create_collection(
            name="documents",
            embedding_function=embed_fn
        )
        active_doc_ids = []
        return {"message": "All documents cleared."}
    except Exception as e:
        print(f"Clear error: {e}")
        raise HTTPException(500, f"Failed to clear documents: {str(e)}")


@app.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    """Delete a specific document by its doc_id."""
    global active_doc_ids
    try:
        # Get all chunk IDs for this document
        results = collection.get(
            where={"doc_id": doc_id}
        )
        if results['ids']:
            collection.delete(ids=results['ids'])
            active_doc_ids = [d for d in active_doc_ids if d != doc_id]
            return {"message": f"Deleted {len(results['ids'])} chunks for document {doc_id}"}
        else:
            raise HTTPException(404, "Document not found")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Delete error: {e}")
        raise HTTPException(500, f"Failed to delete document: {str(e)}")


@app.get("/documents")
async def list_documents():
    """List all unique documents in the collection."""
    try:
        results = collection.get()
        if not results['metadatas']:
            return {"documents": []}

        # Get unique documents
        docs = {}
        for meta in results['metadatas']:
            doc_id = meta.get('doc_id', 'unknown')
            if doc_id not in docs:
                docs[doc_id] = {
                    "doc_id": doc_id,
                    "source": meta.get('source', 'unknown'),
                    "chunks": 0
                }
            docs[doc_id]["chunks"] += 1

        return {"documents": list(docs.values())}
    except Exception as e:
        print(f"List error: {e}")
        raise HTTPException(500, f"Failed to list documents: {str(e)}")


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)