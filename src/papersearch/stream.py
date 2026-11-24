import json
import os
import re
import shutil
from contextlib import closing
from itertools import islice
from uuid import uuid4

from kafka import KafkaConsumer, KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError
from kafka.structs import OffsetAndMetadata, TopicPartition
from sqlalchemy import text

from .database import apply_revision
from .records import MAX_LINE_BYTES, RecordError, parse_record

GROUP = "papersearch-ingest"
WINDOW = 32
INPUT_ERRORS = (ValueError, OverflowError, RecursionError)


def archive(source, root, fmt):
    parent = root / "archives"
    parent.mkdir(parents=True, exist_ok=True)
    batch_id = uuid4().hex
    folder = parent / (".building-" + batch_id)
    folder.mkdir()
    shutil.copyfile(source, folder / "records.jsonl")
    (folder / "batch.json").write_text(json.dumps({"format": fmt}), encoding="utf-8")
    return folder.rename(parent / batch_id)


def raw_lines(path):
    with path.open("rb") as source:
        number = 0
        while line := source.readline(MAX_LINE_BYTES + 1):
            number += 1
            if len(line) <= MAX_LINE_BYTES:
                yield number, line
                continue
            while line and not line.endswith(b"\n"):
                line = source.readline(MAX_LINE_BYTES)
            yield number, None


def broker_address():
    return os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")


def init_topic(topic):
    with closing(KafkaAdminClient(bootstrap_servers=broker_address())) as admin:
        try:
            admin.create_topics([NewTopic(topic, 3, 1)])
        except TopicAlreadyExistsError:
            pass


def group_reader(group):
    return KafkaConsumer(
        bootstrap_servers=broker_address(),
        group_id=group,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        allow_auto_create_topics=False,
        max_poll_records=16,
    )


def offsets(reader, topic):
    partitions = reader.partitions_for_topic(topic)
    if not partitions:
        raise ValueError(f"Kafka topic is unavailable: {topic}")
    parts = [TopicPartition(topic, p) for p in sorted(partitions)]
    starts = reader.beginning_offsets(parts)
    ends = reader.end_offsets(parts)
    lag = {}
    for part in parts:
        committed = reader.committed(part) or 0
        if not starts[part] <= committed <= ends[part]:
            raise ValueError(
                "The group offset is outside retained Kafka data. Replay to a new topic and group."
            )
        lag[part.partition] = ends[part] - committed
    return lag


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(value, file)
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(path)


def publish(folder, topic, group=GROUP, max_lag=4096, replay=False):
    if not re.fullmatch(r"[a-zA-Z0-9_-][a-zA-Z0-9_.-]{0,248}", topic) or max_lag < 1:
        raise ValueError("Provide a valid Kafka topic and positive lag limit")
    fmt = json.loads((folder / "batch.json").read_text(encoding="utf-8"))["format"]
    checkpoint = folder / ("ack-" + topic + ".json")
    if replay:
        atomic_json(checkpoint, 0)
    last = (
        json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else 0
    )
    with (
        closing(group_reader(group)) as reader,
        closing(
            KafkaProducer(bootstrap_servers=broker_address(), acks="all")
        ) as producer,
        closing(raw_lines(folder / "records.jsonl")) as records,
    ):
        remaining = islice(records, last, None)
        while batch := list(islice(remaining, min(WINDOW, max_lag))):
            if sum(offsets(reader, topic).values()) + len(batch) > max_lag:
                raise ValueError(
                    "Consumer lag limit reached. Drain the group and resume publication."
                )
            pending = []
            for number, raw in batch:
                key = None
                if raw is not None:
                    try:
                        key = parse_record(raw, fmt).paper_id.encode()
                    except INPUT_ERRORS:
                        pass  # The consumer records the durable rejection.
                headers = [
                    ("format", fmt.encode()),
                    ("archive", folder.name.encode()),
                    ("line", str(number).encode()),
                ]
                if raw is None:
                    headers.append(("oversize", b"1"))
                pending.append(
                    producer.send(topic, key=key, value=raw or b"", headers=headers)
                )
            for acknowledgement in pending:
                acknowledgement.get(timeout=30)
            atomic_json(checkpoint, batch[-1][0])


def apply_delivery(engine, record, group):
    headers = dict(record.headers)
    raw = record.value or b""
    location = (headers.get("archive") or b"").decode("ascii", "replace")
    line = (headers.get("line") or b"").decode("ascii", "replace")
    try:
        if "oversize" in headers or len(raw) > MAX_LINE_BYTES:
            raise RecordError("record_too_large")
        revision = parse_record(raw, (headers.get("format") or b"").decode("ascii"))
        if record.key != revision.paper_id.encode():
            raise RecordError("invalid_paper_key")
    except INPUT_ERRORS as exc:
        with engine.begin() as conn:
            conn.execute(
                text("""
                INSERT INTO quarantine(group_id,topic,partition_id,offset_id,source_location,reason,raw)
                VALUES(:group,:topic,:part,:offset,:location,:reason,UNHEX(:raw))
                ON DUPLICATE KEY UPDATE offset_id=offset_id
            """),
                dict(
                    group=group,
                    topic=record.topic,
                    part=record.partition,
                    offset=record.offset,
                    location=f"{location}:{line}"[:320],
                    reason=str(exc)[:255],
                    raw=raw[:MAX_LINE_BYTES].hex(),
                ),
            )
        return "rejected"
    with engine.begin() as conn:
        inserted = conn.execute(
            text("""
                INSERT IGNORE INTO processed_deliveries(group_id,topic,partition_id,offset_id)
                VALUES(:group,:topic,:part,:offset)
            """),
            dict(
                group=group,
                topic=record.topic,
                part=record.partition,
                offset=record.offset,
            ),
        )
        if not inserted.rowcount:
            return "duplicate"
        return apply_revision(conn, revision)[1]


def consume(engine, topic, group=GROUP, drain=False):
    with closing(group_reader(group)) as reader:
        offsets(reader, topic)
        reader.subscribe([topic])
        while True:
            polled = reader.poll(timeout_ms=1000)
            for part, messages in polled.items():
                following = reader.committed(part) or 0
                for record in messages:
                    if record.offset != following:
                        raise ValueError(
                            f"Unexpected Kafka offset for {part}: {record.offset}, expected {following}"
                        )
                    apply_delivery(engine, record, group)
                    following += 1
                    reader.commit(
                        {part: OffsetAndMetadata(following, "", -1)}, timeout_ms=10000
                    )
            if drain and not polled and not any(offsets(reader, topic).values()):
                return
