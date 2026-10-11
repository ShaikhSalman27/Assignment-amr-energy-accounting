
import csv
import hashlib
import json
from pathlib import Path

from validate_inputs import load_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def calculate_sha256(path):
    """Identify whether the source CSV has changed."""
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def save_checkpoint(checkpoint_path, checkpoint):
    """Write checkpoint atomically to reduce partial-file risk."""
    temporary_path = checkpoint_path.with_suffix(".tmp")

    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(checkpoint, file, indent=2)

    temporary_path.replace(checkpoint_path)


def write_part_file(part_path, fieldnames, rows):
    """Save one completed chunk to a CSV part file."""
    temporary_path = part_path.with_suffix(".tmp")

    with temporary_path.open(
        "w", encoding="utf-8", newline=""
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Rename only after the complete part file has been written.
    temporary_path.replace(part_path)


def process_blockload_chunks(config):
    input_path = PROJECT_ROOT / config["input_dir"] / "hes_blockload.csv"
    output_dir = PROJECT_ROOT / config["output_dir"] / "blockload_parts"
    checkpoint_dir = PROJECT_ROOT / config["checkpoint_dir"]

    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_path = checkpoint_dir / "blockload_checkpoint.json"
    chunk_size = int(config["chunk_size"])
    input_hash = calculate_sha256(input_path)

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero.")

    # Load and validate existing checkpoint.
    if checkpoint_path.exists():
        with checkpoint_path.open("r", encoding="utf-8") as file:
            checkpoint = json.load(file)

        if checkpoint["input_sha256"] != input_hash:
            raise ValueError(
                "Input CSV changed. Use a fresh checkpoint and output "
                "directory before starting a new run."
            )

        if checkpoint["chunk_size"] != chunk_size:
            raise ValueError(
                "Chunk size differs from the saved checkpoint."
            )

        completed_chunks = int(checkpoint["completed_chunks"])

        # Verify that every completed chunk file exists.
        for chunk_id in range(1, completed_chunks + 1):
            part_path = (
                output_dir / f"part_{chunk_id:05d}.csv"
            )
            if not part_path.is_file():
                raise ValueError(
                    f"Missing completed chunk: {part_path}. "
                    "Restore it or start a clean run."
                )

        print(f"Resuming after completed chunk {completed_chunks}.")
    else:
        completed_chunks = 0
        print("Starting a new chunk-processing run.")

    processed_rows = 0
    chunk_number = 0
    rows_in_chunk = []

    with input_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames

        if not fieldnames:
            raise ValueError("Input CSV has no header.")

        for row in reader:
            rows_in_chunk.append(row)

            if len(rows_in_chunk) == chunk_size:
                chunk_number += 1
                processed_rows += len(rows_in_chunk)

                if chunk_number > completed_chunks:
                    part_path = (
                        output_dir / f"part_{chunk_number:05d}.csv"
                    )

                    write_part_file(part_path, fieldnames, rows_in_chunk)

                    save_checkpoint(
                        checkpoint_path,
                        {
                            "input_sha256": input_hash,
                            "chunk_size": chunk_size,
                            "completed_chunks": chunk_number,
                            "processed_rows": processed_rows,
                        },
                    )

                    print(
                        f"Saved chunk {chunk_number}: "
                        f"{processed_rows:,} rows total"
                    )

                    # if chunk_number == 12:
                    #     raise KeyboardInterrupt("Simulated interruption at 60%")

                rows_in_chunk = []

        # Save the final chunk, even when it contains fewer rows.
        if rows_in_chunk:
            chunk_number += 1
            processed_rows += len(rows_in_chunk)

            if chunk_number > completed_chunks:
                part_path = (
                    output_dir / f"part_{chunk_number:05d}.csv"
                )

                write_part_file(part_path, fieldnames, rows_in_chunk)

                save_checkpoint(
                    checkpoint_path,
                    {
                        "input_sha256": input_hash,
                        "chunk_size": chunk_size,
                        "completed_chunks": chunk_number,
                        "processed_rows": processed_rows,
                    },
                )

                print(
                    f"Saved chunk {chunk_number}: "
                    f"{processed_rows:,} rows total"
                )

    if chunk_number != int(
        json.loads(checkpoint_path.read_text(encoding="utf-8"))[
            "completed_chunks"
        ]
    ):
        raise RuntimeError(
            "Chunk count and checkpoint do not match."
        )

    print("\nChunk processing completed.")
    print(f"Source rows: {processed_rows:,}")
    print(f"Chunks: {chunk_number}")
    print(f"Part files: {output_dir}")
    print(f"Checkpoint: {checkpoint_path}")


def main():
    config = load_config()
    process_blockload_chunks(config)


if __name__ == "__main__":
    main()
