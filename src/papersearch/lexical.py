import re
import sqlite3
from contextlib import closing


# Common technical abbreviations and the terminology used in titles and abstracts.
VOCABULARY = (
    (
        "vlm",
        "vlms",
        "vision language model",
        "vision language models",
        "mllm",
        "mllms",
        "multimodal large language model",
        "multimodal large language models",
    ),
    ("kv cache", "kv caches", "key value cache", "key value caches"),
    ("gnn", "gnns", "graph neural network", "graph neural networks"),
    ("asr", "automatic speech recognition"),
)
ALIASES = {tuple(phrase.split()): group for group in VOCABULARY for phrase in group}
MAX_ALIAS = max(map(len, ALIASES))


def search_terms(words):
    groups, title_phrases = [], []
    expanded = False
    i = 0
    while i < len(words):
        for width in range(min(MAX_ALIAS, len(words) - i), 0, -1):
            group = ALIASES.get(tuple(words[i : i + width]))
            if group:
                clause = "(" + " OR ".join(f'"{phrase}"' for phrase in group) + ")"
                groups.append(clause)
                if width > 1:
                    title_phrases.append(clause)
                expanded = True
                i += width
                break
        else:
            groups.append(f'"{words[i]}"')
            i += 1
    return (" AND " if expanded else " OR ").join(
        dict.fromkeys(groups)
    ), title_phrases if len(groups) > 1 else []


def search_lexical(path, query, field, offset, limit):
    words = re.findall(r"[^\W_]+", query.lower(), re.UNICODE)
    if not words or len(words) > 32:
        raise ValueError("Enter between 1 and 32 search terms")
    expression, title_phrases = search_terms(words)
    name = re.fullmatch(r"[^\W_]+(?:[-‐‑–][^\W_]+)+", query.strip())
    if name:
        expression = '"' + " ".join(words) + '"'
    if field in ("title", "abstract"):
        expression = f"{field} : ({expression})"
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        select = "SELECT paper_id,revision_id,title,bm25(documents,3,1) AS score,rowid"
        matched = " FROM documents WHERE documents MATCH ?"
        args = [expression]
        sql = select + matched
        order = "score,rowid"
        if name and field != "abstract":
            order = """CASE WHEN lower(trim(title)) = ? OR
                lower(trim(substr(title,1,instr(title,':')-1))) = ? THEN 0 ELSE 1 END,score,rowid"""
            args.extend([query.strip().lower()] * 2)
        elif title_phrases and field == "all":
            title = "title : (" + " AND ".join(title_phrases) + ")"
            sql = (
                select
                + ",0 AS tier"
                + matched
                + " UNION ALL "
                + select
                + ",1 AS tier"
                + matched
            )
            args = [
                f"({expression}) AND ({title})",
                f"({expression}) NOT ({title})",
            ]
            order = "tier,score,rowid"
        rows = db.execute(
            sql + f" ORDER BY {order} LIMIT ? OFFSET ?", [*args, limit + 1, offset]
        ).fetchall()
    return [
        dict(
            paper_id=row["paper_id"],
            revision_id=row["revision_id"],
            title=row["title"],
            score=row["score"],
            rank=i,
        )
        for i, row in enumerate(rows[:limit], offset + 1)
    ], len(rows) > limit
