"""Test bootstrap: force deterministic offline mode and isolated temp data dirs *before* app import."""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="deepbrief-tests-"))
os.environ.update({
    "OFFLINE_TEST_MODE": "true",
    "CHROMA_PERSIST_DIR": str(_tmp / "chroma"),
    "SQLITE_DB_PATH": str(_tmp / "research.db"),
    "CHECKPOINT_DB_PATH": str(_tmp / "checkpoints.db"),
    "REPORTS_DIR": str(_tmp / "reports"),
    "TAVILY_API_KEY": "",
})
