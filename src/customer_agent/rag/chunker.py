from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    section: str
    heading: str
    content: str


def chunk_markdown(text: str, source_name: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    current_heading = "政策"
    current_lines: list[str] = []
    section_index = 0

    def flush() -> None:
        nonlocal section_index, current_lines
        content = "\n".join(line.strip() for line in current_lines if line.strip()).strip()
        if content:
            section_index += 1
            chunks.append(
                Chunk(
                    chunk_id=f"{source_name}-chunk-{section_index:02d}",
                    section=source_name,
                    heading=current_heading,
                    content=content,
                )
            )
        current_lines = []

    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            current_heading = line[3:].strip()
        elif line.startswith("# "):
            continue
        else:
            current_lines.append(line)
    flush()
    return chunks
