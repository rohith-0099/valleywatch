"""Situation-report copilot (Step 6).

The language model never sees satellite data and knows nothing about the
event. It can only call the functions in `facts.py`, which read the finished
outputs of a run. Every number in its text is then checked against what
those functions returned (`check.py`) before anything is shown.
"""
