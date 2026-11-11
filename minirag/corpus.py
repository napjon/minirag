"""Quest Level 1 (load) and Level 3 (chunk by section).

The corpus is a folder of markdown policies. Each file starts with a small
front-matter block (id, title, version, ...), then `## Section` headings.
A chunk never crosses a section, and carries its section as a prefix so the
embedding and the model both see where the text comes from.
"""

from pathlib import Path

MAX_CHARS = 800


def load_docs(corpus_dir: Path) -> list[dict]:
    docs = []
    for path in sorted(corpus_dir.glob("*.md")):
        meta, body = {}, path.read_text(encoding="utf-8")
        if body.startswith("---"):
            _, front, body = body.split("---", 2)
            for line in front.strip().splitlines():
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip()
        meta.setdefault("id", path.stem)
        meta.setdefault("title", path.stem)
        docs.append({**meta, "file": path.name, "body": body.strip()})
    return docs


def chunk_docs(docs: list[dict]) -> list[dict]:
    chunks: list[dict] = []
    for doc in docs:
        _chunk_one(doc, chunks)
    return chunks


def _chunk_one(doc: dict, chunks: list[dict]) -> None:
    section, buf, n = "Overview", [], 0

    def flush():
        nonlocal n
        if buf:
            n += 1
            chunks.append({
                "id": f"{doc['id']}#{n}",
                "doc": doc["id"],
                "title": doc["title"],
                "version": doc.get("version", ""),
                "section": section,
                "text": f"[{doc['title']} > {section}]\n" + "\n".join(buf),
            })
            buf.clear()

    for line in doc["body"].splitlines():
        line = " ".join(line.split())
        if not line or line.startswith("# "):
            continue
        if line.startswith("## "):          # a new section starts: close the old chunk
            flush()
            section = line[3:].strip()
            continue
        if buf and sum(len(x) + 1 for x in buf) + len(line) > MAX_CHARS:
            flush()                          # full: close it before adding this line
        buf.append(line)
    flush()
