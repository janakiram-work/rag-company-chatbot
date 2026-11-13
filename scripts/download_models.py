"""Pre-downloads embedding and OCR models so the first server request is fast."""

import sys
import time

def download_embedding_model():
    print("[1/2] Downloading / verifying BGE embedding model (BAAI/bge-small-en-v1.5)...")
    t0 = time.time()
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("BAAI/bge-small-en-v1.5")
        test_vec = model.encode("Warmup embedding test", normalize_embeddings=True)
        print(f"      BGE embedding model ready (vector dim={len(test_vec)}, elapsed={time.time()-t0:.2f}s).")
        return True
    except Exception as e:
        print(f"      [WARNING] Failed to download BGE embedding model: {e}")
        return False

def download_ocr_model():
    print("[2/2] Downloading / verifying EasyOCR English model...")
    t0 = time.time()
    try:
        import easyocr
        reader = easyocr.Reader(["en"], gpu=False)
        print(f"      EasyOCR reader initialized (elapsed={time.time()-t0:.2f}s).")
        return True
    except Exception as e:
        print(f"      [WARNING] Failed to download EasyOCR model: {e}")
        return False

def main():
    print("=" * 60)
    print("Downloading offline AI models for Enterprise RAG Chatbot")
    print("=" * 60)
    bge_ok = download_embedding_model()
    ocr_ok = download_ocr_model()
    print("=" * 60)
    if bge_ok and ocr_ok:
        print("All models successfully downloaded and verified.")
        sys.exit(0)
    else:
        print("Warning: One or more models could not be downloaded. Models will retry on demand at runtime.")
        sys.exit(0)

if __name__ == "__main__":
    main()
