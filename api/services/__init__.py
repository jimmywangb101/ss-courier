"""
services/ — one module per external system we talk to.

Design rule for everything in this package: a service failure must NEVER crash
a live phone call. Each module returns a small result dict like
    {"ok": True,  "data": {...}}
    {"ok": False, "error": "human readable reason", "skipped": True}
instead of raising. The caller decides what to do; the customer on the phone
never hears a stack trace.
"""
