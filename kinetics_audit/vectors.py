import hashlib
import math
import re

DIM = 256
_SPLIT = re.compile(r"[^。！？；\n]+[。！？；\n]?")


def chunk_sentences(text, limit=80):
    found = []
    for piece in _SPLIT.findall(text or ""):
        sentence = " ".join(piece.split())
        if len(_compact(sentence)) < 8:
            continue
        if len(sentence) > 180:
            for smaller in re.findall(r"[^，,]+[，,]?", sentence):
                smaller = smaller.strip()
                if len(_compact(smaller)) >= 8:
                    found.append(smaller)
        else:
            found.append(sentence.strip())
        if len(found) >= limit:
            break
    return [
        {"id": f"s{index}", "text": sentence, "vector": embed(sentence)}
        for index, sentence in enumerate(found[:limit])
    ]


def rank(query, sentences, limit=4, required=()):
    query_vector = embed(query)
    needed = [_compact(part) for part in required if part]
    scored = []
    for sentence in sentences:
        compact = _compact(sentence["text"])
        scored.append(
            {
                "id": sentence["id"],
                "text": sentence["text"],
                "score": round(cosine(query_vector, sentence["vector"]), 4),
                "covered": all(part in compact for part in needed) if needed else True,
            }
        )
    scored.sort(key=lambda item: (item["covered"], item["score"]), reverse=True)
    return scored[:limit]


def embed(text):
    compact = _compact(text)
    vector = [0.0] * DIM
    grams = [compact[index : index + 1] for index in range(len(compact))]
    grams.extend(compact[index : index + 2] for index in range(len(compact) - 1))
    for gram in grams:
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "little") % DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def cosine(left, right):
    return sum(a * b for a, b in zip(left, right))


def _compact(text):
    return "".join(text.split()).casefold()
