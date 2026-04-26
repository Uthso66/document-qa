import os
import uuid
from io import BytesIO
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
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

class QuestionRequest(BaseModel):
    question: str
    top_k: int = 3

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
    metadatas = [{"source": file.filename, "chunk_index": i} for i in range(len(chunks))]
    
    collection.add(ids=chunk_ids, documents=chunks, metadatas=metadatas)
    return {"message": f"Uploaded {file.filename} with {len(chunks)} chunks", "doc_id": doc_id}

@app.post("/ask", response_model=AnswerResponse)
async def ask_question(request: QuestionRequest):
    # Retrieve relevant chunks
    results = collection.query(query_texts=[request.question], n_results=request.top_k)
    
    if not results['documents'] or not results['documents'][0]:
        return AnswerResponse(answer="No relevant information found.", sources=[])
    
    context_chunks = results['documents'][0]
    sources = [f"{meta['source']} (chunk {meta['chunk_index']})" for meta in results['metadatas'][0]]
    context = "\n\n---\n\n".join(context_chunks)
    
    # Generate answer using Ollama chat (local)
    prompt = f"""You are a helpful assistant that answers questions based ONLY on the provided context.
If the answer is not in the context, say "I don't have enough information to answer that."

Context:
{context}

Question: {request.question}

Answer:"""
    
    response = ollama.chat(model="llama3.2:3b", messages=[{"role": "user", "content": prompt}])
    answer = response['message']['content'].strip()
    
    return AnswerResponse(answer=answer, sources=sources)

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)