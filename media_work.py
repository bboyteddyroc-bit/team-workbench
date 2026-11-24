"""Process-wide budget for heavyweight local media work; never wraps network calls."""
import threading
MEDIA_LOCK = threading.RLock()
