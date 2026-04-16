import sys
import os

# Ensure the sync-worker source directory is always on sys.path,
# regardless of the working directory pytest is invoked from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
