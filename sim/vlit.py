"""Verilog literals for the generated benches (M23).

iverilog's scanner holds one line in 16k characters, and at 10 x 10 CLBs the chain is 68,096
bits (17,024 hex digits): a wide constant is written as a concatenation of CHUNK-bit literals,
one per line (continued with a backslash inside a `define, which a statement must not have).
"""

CHUNK = 8192


def hexw(v, w, define=True):
    """v as a w-bit Verilog constant, for a `define (or a statement: define=False)"""
    if w <= CHUNK:
        return f"{w}'h{v:0{(w + 3) // 4}x}"
    parts, lo = [], 0
    while lo < w:
        n = min(CHUNK, w - lo)
        parts.append(f"{n}'h{(v >> lo) & ((1 << n) - 1):0{(n + 3) // 4}x}")
        lo += n
    return "{" + (", \\\n    " if define else ",\n        ").join(reversed(parts)) + "}"
