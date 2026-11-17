import argparse
import json
import os
from contextlib import closing
from pathlib import Path

from . import stream
from .database import connect
from .embeddings import backfill, embed
from .history import export_history
from .snapshot import publish_snapshot, snapshots_root


def main():
    parser = argparse.ArgumentParser(prog="papersearch")
    commands = parser.add_subparsers(dest="command", required=True)
    save = commands.add_parser("archive")
    save.add_argument("path", type=Path)
    save.add_argument("--format", choices=["arxiv", "fixture"], required=True)
    commands.add_parser("topic").add_argument("topic")
    for name in ("publish", "consume", "lag"):
        command = commands.add_parser(name)
        command.add_argument("topic")
        command.add_argument("--group", default=stream.GROUP)
        if name == "publish":
            command.add_argument("folder", type=Path)
            command.add_argument("--max-lag", type=int, default=4096)
            command.add_argument("--replay", action="store_true")
        if name == "consume":
            command.add_argument("--drain", action="store_true")
    commands.add_parser("snapshot")
    worker = commands.add_parser("embed")
    worker.add_argument("--limit", type=int, default=1024)
    worker.add_argument("--backfill", action="store_true")
    history = commands.add_parser("export-history")
    history.add_argument("output", type=Path)
    history.add_argument("--after-revision", type=int, default=0)
    args = parser.parse_args()
    root = Path(os.environ.get("ARTIFACT_DIR", "artifacts"))
    match args.command:
        case "archive":
            print(stream.archive(args.path, root, args.format))
        case "topic":
            stream.init_topic(args.topic)
        case "publish":
            stream.publish(
                args.folder, args.topic, args.group, args.max_lag, args.replay
            )
        case "consume":
            stream.consume(connect(), args.topic, args.group, args.drain)
        case "snapshot":
            print(json.dumps(publish_snapshot(connect(), snapshots_root())))
        case "embed":
            engine = connect()
            if args.backfill:
                backfill(engine)
            print(json.dumps({"embedded": embed(engine, args.limit)}))
        case "export-history":
            export_history(connect(), args.output, args.after_revision)
        case "lag":
            with closing(stream.group_reader(args.group)) as reader:
                print(json.dumps(stream.offsets(reader, args.topic)))


if __name__ == "__main__":
    main()
