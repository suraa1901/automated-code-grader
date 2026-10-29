"""
fingerprint.py
Structural similarity via k-gram winnowing - the same family of algorithm
MOSS and JPlag use, simplified for a college project.

How it works:
1. Join the normalized token stream and slide a window of K tokens across
   it, hashing each window ("k-gram") -> a list of rolling hashes.
2. Winnowing: instead of keeping every hash (too many, too slow to
   compare), slide a second window of size W over the hash list and keep
   only the minimum hash in each window (ties -> keep the rightmost).
   This selects a small, position-independent "fingerprint set" such that
   any shared substring of length >= K+W-1 between two files is guaranteed
   to produce at least one matching fingerprint.
3. Similarity between two files = Jaccard index of their fingerprint sets.

This is robust to variable renaming (handled upstream by the tokenizer),
reordering of unrelated statements, and formatting changes - all of which
defeat naive text-diff comparisons.
"""

K = 5   # k-gram length, in tokens
W = 4   # winnowing window size


def _hash_kgrams(tokens: list[str], k: int) -> list[int]:
    joined_units = ["\x1f".join(tokens[i:i + k]) for i in range(len(tokens) - k + 1)]
    return [hash(unit) & 0xFFFFFFFF for unit in joined_units]


def winnow(hashes: list[int], w: int) -> set[int]:
    if len(hashes) <= w:
        return set(hashes)

    fingerprints = set()
    min_pos = -1
    for i in range(len(hashes) - w + 1):
        window = hashes[i:i + w]
        # Rightmost minimum, per the standard winnowing algorithm.
        window_min_pos = i + max(
            (j for j, v in enumerate(window) if v == min(window)), default=0
        )
        if window_min_pos != min_pos:
            min_pos = window_min_pos
            fingerprints.add(hashes[min_pos])
    return fingerprints


def fingerprint_tokens(tokens: list[str]) -> set[int]:
    hashes = _hash_kgrams(tokens, K)
    return winnow(hashes, W)


def jaccard_similarity(set_a: set, set_b: set) -> float:
    if not set_a and not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union) * 100
