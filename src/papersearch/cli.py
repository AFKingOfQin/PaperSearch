import argparse
import json
import os
from contextlib import closing
from pathlib import Path

from . import stream
from .database import connect


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
    args = parser.parse_args()
    root = Path(os.environ.get("ARTIFACT_DIR", "artifacts"))
    match args.command:
        case "archive":
            print(stream.archive(args.path, root, args.format))
        case "topic":
            stream.init_topic(args.topic)
        case "publish":
            stream.publish(args.folder, args.topic, args.group, args.max_lag, args.replay)
        case "consume":
            stream.consume(connect(), args.topic, args.group, args.drain)
        case "lag":
            with closing(stream.group_reader(args.group)) as reader:
                print(json.dumps(stream.offsets(reader, args.topic)))


if __name__ == "__main__":
    main()
