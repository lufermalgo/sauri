"""Keep a bounded diagnostic tail without trusting subprocess text as public data."""

import re

# Only fixed diagnostic templates are safe: paths, prompts and even recognized
# names of log functions can otherwise contain arbitrary recording content.
_SAFE_LINE = re.compile(
    r"(?:ggml_metal_buffer_init: error: failed to allocate buffer, size =\s+[0-9.]+ MiB"
    r"|error: failed to (?:initialize whisper context|decode audio data from memory buffer)"
    r"|(?:main|whisper_full_with_state): failed to process audio"
    r"|(?:ggml_backend_sched_alloc_graph|ggml_gallocr_alloc_graph): failed to allocate graph)"
)
_PRIVATE_SUFFIX = re.compile(
    r"(error: (?:input file not found|failed to read audio file|failed to open file)"
    r"|whisper_init_from_file_with_params_no_state: failed to open)[ :].*"
)


def diagnostic_tail(stderr: bytes | str | None) -> str:
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    lines = (stderr or "").splitlines()[-8:]
    safe: list[str] = []
    for line in lines:
        line = line.strip()
        if _SAFE_LINE.fullmatch(line):
            safe.append(line)
        elif match := _PRIVATE_SUFFIX.fullmatch(line):
            safe.append(match[1] + " [redacted]")
        elif line:
            safe.append("[stderr redacted]")
    return "\n".join(safe)[-600:] or "[no stderr]"
