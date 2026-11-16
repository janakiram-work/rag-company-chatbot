"""Pre-downloads embedding and OCR models so the first server request is fast.
Supports --target DIR for creating offline pre-packaged model bundles for air-gapped servers.
"""

import os
import sys
import time
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")


def download_embedding_model(target_hf_home: str = "") -> bool:
    print("[1/2] Downloading / verifying BGE embedding model (BAAI/bge-small-en-v1.5)...")
    t0 = time.time()
    try:
        from sentence_transformers import SentenceTransformer
        from backend.config import EMBEDDING_MODEL_NAME

        if target_hf_home:
            os.environ["HF_HOME"] = target_hf_home
            os.makedirs(target_hf_home, exist_ok=True)

        model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        test_vec = model.encode("Warmup embedding test", normalize_embeddings=True)
        print(f"      BGE embedding model ready (vector dim={len(test_vec)}, elapsed={time.time()-t0:.2f}s).")
        return True
    except Exception as e:
        print(f"      [WARNING] Failed to download BGE embedding model: {e}")
        return False


def download_ocr_model(target_ocr_dir: str = "") -> bool:
    print("[2/2] Downloading / verifying EasyOCR English model...")
    t0 = time.time()
    try:
        import easyocr

        if target_ocr_dir:
            os.makedirs(target_ocr_dir, exist_ok=True)
            reader = easyocr.Reader(["en"], gpu=False, model_storage_directory=target_ocr_dir)
        else:
            reader = easyocr.Reader(["en"], gpu=False)
        print(f"      EasyOCR reader initialized (elapsed={time.time()-t0:.2f}s).")
        return True
    except Exception as e:
        print(f"      [WARNING] Failed to download EasyOCR model: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Pre-download AI models for offline or production caching.")
    parser.add_argument("--target", help="Custom destination directory to store downloaded models (for offline transfer)")
    args = parser.parse_args()

    target_dir = args.target or os.getenv("MODELS_DIR", "").strip()

    target_hf_home = ""
    target_ocr_dir = ""
    if target_dir:
        abs_target = os.path.abspath(target_dir)
        target_hf_home = os.path.join(abs_target, "huggingface")
        target_ocr_dir = os.path.join(abs_target, "easyocr")
        print(f"[*] Custom models target directory: {abs_target}")
        print(f"[*] Hugging Face cache: {target_hf_home}")
        print(f"[*] EasyOCR cache: {target_ocr_dir}")

    print("=" * 60)
    print("Downloading offline AI models for Enterprise RAG Chatbot")
    print("=" * 60)
    bge_ok = download_embedding_model(target_hf_home)
    ocr_ok = download_ocr_model(target_ocr_dir)
    print("=" * 60)

    if bge_ok and ocr_ok:
        print("All models successfully downloaded and verified.")
        if target_dir:
            print("\n[i] OFFLINE DEPLOYMENT INSTRUCTIONS:")
            print(f"    1. Copy the folder '{os.path.abspath(target_dir)}' to your destination server.")
            print(f"    2. On the destination server, set MODELS_DIR={target_dir} in .env.")
            print("    3. The application will load models locally without needing HuggingFace access.")
        sys.exit(0)
    else:
        print("Warning: One or more models could not be downloaded. Models will retry on demand at runtime.")
        sys.exit(0)


if __name__ == "__main__":
    main()
