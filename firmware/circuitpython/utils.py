"""
Utility functions for text formatting and sanitization.
"""
from __future__ import annotations


def hexdump(data: bytes, width: int = 16) -> str:
    """Format bytes as hex string with optional line width."""
    if not data:
        return "<empty>"
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i+width]
        hex_str = " ".join(f"{b:02X}" for b in chunk)
        lines.append(hex_str)
    return "\n".join(lines) if len(lines) > 1 else lines[0]


def sanitize_text(text: str, max_len: int = 100) -> str:
    """Remove problematic characters from text for Nextion display."""
    # Remove CR, LF, quotes, and limit length
    text = text.replace("\r", " ").replace("\n", " ")
    text = text.replace('"', "'").replace("\\", "/")
    if len(text) > max_len:
        text = text[:max_len - 3] + "..."
    return text


def fmt_ms(ms: int) -> str:
    """Format milliseconds as MM:SS."""
    if ms < 0:
        ms = 0
    total_sec = ms // 1000
    minutes = total_sec // 60
    seconds = total_sec % 60
    return f"{minutes:02d}:{seconds:02d}"
