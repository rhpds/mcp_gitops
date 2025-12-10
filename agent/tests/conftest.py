"""Pytest configuration and fixtures."""
import sys
from unittest.mock import MagicMock

# Mock litellm globally before any test imports
# This allows tests to run without litellm installed (which has heavy dependencies)
if 'litellm' not in sys.modules:
    sys.modules['litellm'] = MagicMock()
