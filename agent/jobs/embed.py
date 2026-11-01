"""Vector embedding and text similarity shortlisting engine."""

import logging
from typing import List, Tuple
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from agent.jobs.schema import Job
from agent.profile.schema import MasterProfile

logger = logging.getLogger(__name__)


def profile_to_text(profile: MasterProfile) -> str:
    """Serialize master profile into a comprehensive document for semantic/lexical vectorization."""
    parts = []

    # Personal & Headline
    if profile.personal_info.headline:
        parts.append(profile.personal_info.headline)
    if profile.summary and profile.summary.text:
        parts.append(profile.summary.text)

    # Skills (emphasized with repeat weighting)
    skills = [s.name for s in profile.skills]
    if skills:
        parts.append("Skills: " + ", ".join(skills))
        parts.append(" ".join(skills))  # Repeat skills to boost term frequency weight

    # Projects
    for p in profile.projects:
        parts.append(f"Project {p.name}: {' '.join(p.stack)}")
        if p.description:
            parts.append(p.description)
        for h in p.highlights:
            parts.append(h.text)

    # Experience
    for exp in profile.experience:
        parts.append(f"Experience {exp.title} at {exp.company}")
        for ach in exp.achievements:
            parts.append(ach.text)

    return " \n".join(parts)


def job_to_text(job: Job) -> str:
    """Serialize job posting into a textual document for vectorization."""
    parts = [
        f"Title: {job.title}",
        f"Company: {job.company}",
    ]
    if job.tags:
        parts.append("Tags: " + " ".join(job.tags))
        parts.append(" ".join(job.tags))  # Repeat tags to boost keyword matches
    if job.location:
        parts.append(f"Location: {job.location}")
    if job.description:
        parts.append(job.description[:4000])

    return " \n".join(parts)


class EmbeddingMatcher:
    """Vector similarity matcher that efficiently shortlists top opportunities."""

    def __init__(self) -> None:
        pass

    def shortlist(
        self,
        profile: MasterProfile,
        jobs: List[Job],
        top_n: int = 15,
    ) -> List[Tuple[Job, float]]:
        """Rank and shortlist jobs against candidate profile by cosine vector similarity.

        Args:
            profile: Candidate MasterProfile.
            jobs: List of active candidate Job objects.
            top_n: Number of top matching jobs to return.

        Returns:
            List of (Job, similarity_score) sorted by score descending.
        """
        if not jobs:
            return []

        profile_doc = profile_to_text(profile)
        job_docs = [job_to_text(j) for j in jobs]

        corpus = [profile_doc] + job_docs

        # Build TF-IDF vector matrix (unigrams + bigrams)
        vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            stop_words="english",
            lowercase=True,
            sublinear_tf=True,
        )

        tfidf_matrix = vectorizer.fit_transform(corpus)
        profile_vec = tfidf_matrix[0:1]
        job_vecs = tfidf_matrix[1:]

        # Compute cosine similarity between profile and all job vectors
        similarities = cosine_similarity(profile_vec, job_vecs)[0]

        scored_jobs: List[Tuple[Job, float]] = []
        for i, sim in enumerate(similarities):
            # Bound similarity to 0.0 - 1.0
            score = max(0.0, min(1.0, float(sim)))
            scored_jobs.append((jobs[i], score))

        # Sort descending by similarity
        scored_jobs.sort(key=lambda x: x[1], reverse=True)

        shortlisted = scored_jobs[:top_n]
        logger.info(
            "Vector shortlisting complete: evaluated %d jobs, selected top %d (score range: %.2f - %.2f)",
            len(jobs),
            len(shortlisted),
            shortlisted[0][1] if shortlisted else 0.0,
            shortlisted[-1][1] if shortlisted else 0.0,
        )
        return shortlisted
