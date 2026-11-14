import asyncio
import threading
from typing import Callable, Any
from backend.config import MAX_HEAVY_TASKS, MAX_CONCURRENT_CHATS

# Global threading semaphore for heavy tasks (embedding, OCR, Chroma, SIFT)
HEAVY_TASK_SEMAPHORE = threading.BoundedSemaphore(max(1, MAX_HEAVY_TASKS))

# Global chat stream counter
_active_chats_lock = threading.Lock()
_active_chats_count = 0
_queue_size = 0


def run_heavy_task_sync(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a heavy task in worker thread bounded by HEAVY_TASK_SEMAPHORE."""
    with HEAVY_TASK_SEMAPHORE:
        return fn(*args, **kwargs)


async def run_heavy_task_async(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Offload a heavy sync task to asyncio worker thread bounded by HEAVY_TASK_SEMAPHORE."""
    return await asyncio.to_thread(run_heavy_task_sync, fn, *args, **kwargs)


def try_acquire_chat_slot() -> bool:
    """Atomically check and acquire a chat stream slot. Returns False if busy."""
    global _active_chats_count
    with _active_chats_lock:
        if _active_chats_count >= MAX_CONCURRENT_CHATS:
            return False
        _active_chats_count += 1
        return True


def release_chat_slot():
    """Atomically release a chat stream slot."""
    global _active_chats_count
    with _active_chats_lock:
        if _active_chats_count > 0:
            _active_chats_count -= 1


def get_active_streams() -> int:
    with _active_chats_lock:
        return _active_chats_count


def get_queue_size() -> int:
    return _queue_size
