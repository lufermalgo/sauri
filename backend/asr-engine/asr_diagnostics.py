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


# whisper.cpp v1.9.5 (the pinned build), examples/cli/cli.cpp: these lines end the run with exit code 3 when the
# model file is gone or ``whisper_init_from_file_with_params`` returns no context (bad magic, a file that cannot be
# opened, no memory for the weights). They are printed before any audio is read.
_LOAD_FAILURES = ("error: failed to initialize whisper context", "error: model file not found")
# Printed by cli.cpp right before inference starts: after it, a failure is never about loading the model.
_PROCESSING = ": processing '"
_SIGABRT_EXIT = -6  # subprocess return code of a process stopped by SIGABRT


def whisper_load_failed(returncode: int, stderr: bytes | str | None) -> bool:
    """True when whisper-cli stopped while loading its model, before processing any audio.

    Besides the classified exit above, a file of another architecture can trip a ``GGML_ASSERT`` inside
    ``whisper_model_load``, which aborts the process (checked with the pinned binary and a Silero VAD file).
    """
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    text = stderr or ""
    if _PROCESSING in text:
        return False
    if any(marker in text for marker in _LOAD_FAILURES):
        return True
    return returncode == _SIGABRT_EXIT and "whisper_model_load:" in text
