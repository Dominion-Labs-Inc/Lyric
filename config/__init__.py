"""
Lyric Configuration Module  
Provides access to the main lyric configuration
"""

# Import the main configuration
try:
    import os
    exec(open(os.path.join(os.path.dirname(__file__), "lyric_config.py")).read())
except Exception as e:
    print(f"Warning: Could not load lyric_config.py: {e}")

__all__ = []
