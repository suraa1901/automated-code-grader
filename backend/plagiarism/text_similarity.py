"""
text_similarity.py
Surface-level similarity signal: TF-IDF vectorization of the raw
(normalized-token) code + cosine similarity between every pair.

This is intentionally the "dumb but fast" second opinion that complements
the structural fingerprinting in fingerprint.py - it catches near-verbatim
copies quickly and gives a sanity check when the two scores disagree
(e.g. high text similarity + low structural similarity can mean two
students solved it the same *obvious* way rather than copying).
"""

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def pairwise_text_similarity(token_lists: list[list[str]]) -> list[list[float]]:
    """
    token_lists: one normalized token list per submission, same order as
    the submissions passed in.

    Returns an NxN matrix of similarity scores in [0, 100].
    """
    documents = [" ".join(tokens) for tokens in token_lists]
    if len(documents) < 2 or all(not d.strip() for d in documents):
        n = len(documents)
        return [[0.0] * n for _ in range(n)]

    vectorizer = TfidfVectorizer(token_pattern=r"[^\s]+")
    matrix = vectorizer.fit_transform(documents)
    sim = cosine_similarity(matrix)
    return (sim * 100).tolist()
