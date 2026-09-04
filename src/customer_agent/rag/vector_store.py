from dataclasses import dataclass
from math import sqrt
import re
from typing import Iterable

from .chunker import Chunk


def tokenize(text: str) -> list[str]:
    text = text.lower()
    base_tokens = re.findall(r"[\u4e00-\u9fff]{1,6}|[a-z0-9_]+", text)
    tokens: list[str] = []
    for token in base_tokens:
        if re.fullmatch(r"[\u4e00-\u9fff]{2,}", token):
            tokens.append(token)
            tokens.extend(token[index : index + 2] for index in range(len(token) - 1))
        else:
            tokens.append(token)
    return [token for token in tokens if token.strip()]


def vectorize(tokens: Iterable[str]) -> dict[str, float]:
    vector: dict[str, float] = {}
    for token in tokens:
        vector[token] = vector.get(token, 0.0) + 1.0
    return vector


def cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(left[token] * right.get(token, 0.0) for token in left)
    left_norm = sqrt(sum(value * value for value in left.values()))
    right_norm = sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


@dataclass(frozen=True)
class SearchHit:
    chunk: Chunk
    score: float


class LocalVectorStore:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self.chunk_vectors = [vectorize(tokenize(chunk.content + " " + chunk.heading)) for chunk in chunks]

    def search(self, query: str, top_k: int = 3) -> list[SearchHit]:
        query_vector = vectorize(tokenize(query))
        hits = [
            SearchHit(chunk=chunk, score=cosine_similarity(query_vector, chunk_vector))
            for chunk, chunk_vector in zip(self.chunks, self.chunk_vectors)
        ]
        hits = [hit for hit in hits if hit.score > 0]
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]
