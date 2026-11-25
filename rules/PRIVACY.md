# Privacy and public-safe content

Sauri handles some of the most private data a person has: their conversations. Two promises follow, one to users and
one about this repository.

## Promise to users: nothing leaves the Mac by itself

- Recordings, transcripts, summaries, notes and speaker names are stored in folders the user chose, on their Mac.
- Transcription, speakers and summaries run on local engines by default.
- An external provider (an OpenAI-compatible API, Deepgram, AssemblyAI…) is used only when the user connects it for a
  task. Before anything is sent, the app says what will leave the Mac and where. A change that adds a new outbound path
  must keep this promise, and say so in the pull request.
- The app's services listen on `127.0.0.1` only. The extension and the app pair on the same Mac; no account and no
  server of ours sits in between.
- Logs never contain transcript text, summaries, audio, provider keys or tokens. Log sizes, durations, ids and error
  codes instead.
- The public privacy policy is `landing/privacidad.html` (Spanish and English). Change it in the same pull request when
  behaviour it describes changes.

## Promise about the repository: it never holds anyone's real data

The repository is public, and so are its issues, pull requests and full history. What lands here stays readable by
anyone, even after it is deleted.

Never commit, attach or paste:

- real recordings, transcripts, summaries, meeting titles or screenshots of real meetings;
- names of real people, companies or clients, personal emails or phone numbers;
- absolute paths of your machine (`/Users/<you>/…`): write `~/…`;
- keys, tokens, passwords, `.env` files or anything copied from a keychain.

Use instead:

| Need | Use |
|---|---|
| A person | Laura Méndez, Andrés Ríos, Sofía Vargas (the demo meeting), or "Speaker 1" |
| A company | Acme, Northwind |
| An email | `user@example.com`, `owner@example.test` |
| A path | `~/Sauri/Recordings`, `/Users/test/…` in tests |
| Audio | generated tones or synthetic speech; the media headers in `backend/tests/media_samples.py` |
| A key | `sk-synthetic-…`, `synthetic-token` |
| A screenshot | the demo meeting in `landing/assets/` |

Bug reports work the same way: reproduce with synthetic audio and describe the real case in words, without its content.

## The gate

`make check-private` runs [`scripts/dev/check_private_terms.py`](../scripts/dev/check_private_terms.py). The git
pre-commit hook runs it on staged files, and CI runs it on every pull request. It has two layers:

1. **Public shapes**, everywhere: absolute home paths of a real-looking user, and credential shapes (GitHub, Anthropic,
   AWS and Google keys, private-key headers).
2. **A private word list**, only on machines that have one: `$SAURI_PRIVATE_TERMS`, or `.private-terms.txt` in the
   main checkout. The file is gitignored on purpose, since a list in the repository would publish the words it
   protects. One entry per line: a word (matched whole, ignoring case and accents), `re:<regex>`, `allow:<text>` for a
   line that may stay, or a `# comment`.

When it reports something, replace the value with a placeholder. Never add an `allow:` line for real data. The gate
helps; it does not replace reading your own diff.

## If something private was pushed

Tell a maintainer privately: see [`SECURITY.md`](../SECURITY.md). Do not open a public issue about it. A credential is
revoked first and removed second. Removing it from history does not undo the exposure.
