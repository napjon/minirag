"""minirag serve | index | ask "question" | doctor"""

import argparse
import json
import sys

from .config import settings


def main() -> int:
    ap = argparse.ArgumentParser(prog="minirag")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="start the API and the pages")
    sub.add_parser("index", help="chunk the corpus and embed it (cached)")
    sub.add_parser("doctor", help="check the provider and the models")
    ask = sub.add_parser("ask", help="ask one question in the terminal")
    ask.add_argument("question")
    ask.add_argument("--json", action="store_true", help="print the whole trace")
    args = ap.parse_args()
    s = settings()

    if args.cmd == "serve":
        import uvicorn
        print(f"minirag on http://127.0.0.1:{s.port}  (provider={s.provider})")
        uvicorn.run("minirag.app:api", host="127.0.0.1", port=s.port, log_level="warning")
        return 0

    if args.cmd == "doctor":
        from .llm import get_provider
        health = get_provider(s).health()
        print(f"provider={s.provider}  {health['detail']}")
        return 0 if health["ok"] else 1

    from .pipeline import Engine
    engine = Engine(s)
    if args.cmd == "index":
        ix = engine.index
        print(f"{len(ix.docs)} documents, {len(ix.chunks)} chunks, vectors {ix.vecs.shape} "
              f"({'from cache' if ix.cache_hit else 'embedded now'}) with {engine.provider.embed_model}")
        return 0

    t = engine.answer(args.question)
    if args.json:
        print(json.dumps(t, indent=2))
        return 0
    print(f"\n{t['outcome']['answer']}\n")
    for c in t["outcome"]["citations"]:
        print(f"  [{c['n']}] {c['title']} > {c['section']} (v{c['version']})")
    print(f"\nstatus={t['outcome']['status']} ({t['outcome']['reason']})  {t['total_ms']} ms  trace={t['id']}")
    for c in t["candidates"]:      # read the chunks every time: that habit is most of debugging
        if c["selected"]:
            print(f"  used: {c['chunk_id']:10s} score={c['rerank_score']:.3f}  {c['text'][:70]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
