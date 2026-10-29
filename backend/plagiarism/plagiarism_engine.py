"""
plagiarism_engine.py
Runs pairwise plagiarism detection across every submission in an
assignment and combines the two signals into one score:

    combined_score = 0.6 * structural (winnowing/Jaccard)
                    + 0.4 * textual   (TF-IDF cosine)

Weighted toward structural similarity because it's harder to fool with
cosmetic changes - text similarity mainly acts as a corroborating signal.
Only submissions in the SAME language are compared against each other,
since token streams from different languages aren't comparable.
"""

from itertools import combinations

from .tokenizer import tokenize
from .fingerprint import fingerprint_tokens, jaccard_similarity
from .text_similarity import pairwise_text_similarity

STRUCTURAL_WEIGHT = 0.6
TEXTUAL_WEIGHT = 0.4


def compute_plagiarism(submissions: list, threshold: float = 70.0) -> list[dict]:
    """
    submissions: list of sqlite3.Row with id, language, code

    Returns a list of dicts, one per pair (within the same language):
    {submission_id_1, submission_id_2, token_similarity, text_similarity,
     combined_score, flagged}
    """
    by_language: dict[str, list] = {}
    for sub in submissions:
        by_language.setdefault(sub["language"], []).append(sub)

    results = []
    for language, subs in by_language.items():
        if len(subs) < 2:
            continue

        token_lists = [tokenize(sub["code"], language) for sub in subs]
        fingerprints = [fingerprint_tokens(tokens) for tokens in token_lists]
        text_sim_matrix = pairwise_text_similarity(token_lists)

        for (i, sub_a), (j, sub_b) in combinations(enumerate(subs), 2):
            token_sim = jaccard_similarity(fingerprints[i], fingerprints[j])
            text_sim = text_sim_matrix[i][j]
            combined = round(STRUCTURAL_WEIGHT * token_sim + TEXTUAL_WEIGHT * text_sim, 2)

            results.append({
                "submission_id_1": sub_a["id"],
                "submission_id_2": sub_b["id"],
                "token_similarity": round(token_sim, 2),
                "text_similarity": round(text_sim, 2),
                "combined_score": combined,
                "flagged": combined >= threshold,
            })

    results.sort(key=lambda r: r["combined_score"], reverse=True)
    return results
