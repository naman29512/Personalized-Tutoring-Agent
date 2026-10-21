import os
from pathlib import Path
from langchain_text_splitters import CharacterTextSplitter
import chromadb

# 1. Define folders
PROCESSED_DIR = Path("processed")
DB_DIR = Path("chroma_db")  # Where the database will be saved on your laptop

# 2. Start the Chroma Database
print("Starting Database Engine...")
client = chromadb.PersistentClient(path=str(DB_DIR))
collection = client.get_or_create_collection(name="mit_course_data")

text_splitter = CharacterTextSplitter(
    separator="\n[",
    chunk_size=1000,
    chunk_overlap=0,
    keep_separator=True 
)

print("\nProcessing files...")

# 4. Loop through your processed Markdown files
for filepath in PROCESSED_DIR.glob("*.md"):
    print(f"Chopping and embedding {filepath.name}...")
    
    with open(filepath, "r", encoding="utf-8") as f:
        full_text = f.read()
        
    # Chop the massive text into small chunks
    chunks = text_splitter.split_text(full_text)
    
    # Prepare lists for the database
    documents = []
    metadatas = []
    ids = []
    
    for i, chunk in enumerate(chunks):
        documents.append(chunk)
        metadatas.append({"source": filepath.name})  # Remembers which file the chunk came from
        ids.append(f"{filepath.stem}_chunk_{i}")     # Gives each chunk a unique ID
        
    # 5. Add to ChromaDB (It automatically converts the text to vector numbers here)
    collection.add(
        documents=documents,
        metadatas=metadatas,
        ids=ids
    )
    
    print(f"✅ Saved {len(chunks)} chunks from {filepath.name}")

print("\nDatabase build complete. Your RAG memory is ready.")