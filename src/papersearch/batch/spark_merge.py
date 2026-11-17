import argparse
from pathlib import Path
from uuid import uuid4

from pyspark.sql import SparkSession, functions as F

FIELDS = ["paper_id", "version_rank", "source_updated_at", "payload"]


def winners(history, column):
    priority = ["paper_id", "version_rank", "source_updated_at"]
    unique = history.select(*FIELDS).dropDuplicates()
    grouped = unique.groupBy(*priority).agg(
        F.count("*").alias("variants"), F.first("payload").alias("payload")
    )
    return (
        grouped.where(F.col("variants") == 1)
        .groupBy("paper_id")
        .agg(
            F.max(F.struct("version_rank", "source_updated_at", "payload")).alias(
                column
            )
        )
    )


def merge(base, updates):
    previous = winners(base, "previous")
    current = winners(base.unionByName(updates), "current")
    return (
        previous.join(current, "paper_id", "full")
        .withColumn(
            "change",
            F.when(F.col("previous").isNull(), "new")
            .when(F.col("current").isNull(), "withdrawn")
            .when(F.col("current") == F.col("previous"), "unchanged")
            .otherwise("changed"),
        )
        .select("paper_id", "change", "previous", "current")
    )


def main():
    parser = argparse.ArgumentParser()
    for name in ("base", "updates", "output"):
        parser.add_argument(name)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(output)
    staging = output.with_name(f".{output.name}.{uuid4().hex}.tmp")
    spark = SparkSession.builder.appName("PaperSearch merge").getOrCreate()
    try:
        spark.sparkContext.setLogLevel("WARN")
        merge(
            spark.read.parquet(args.base), spark.read.parquet(args.updates)
        ).write.parquet(str(staging))
        staging.rename(output)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
