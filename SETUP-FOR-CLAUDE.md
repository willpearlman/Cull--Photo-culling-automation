# Instructions for Claude: set up this teammate's machine (WiJoZa / Cull)

You are helping a teammate on a hackathon project finish the machine setup
described in `README-KIRO.md` ("Machine setup"). Windows, PowerShell. Do the
steps for them where you can, explain simply, and check each one before moving on.

## Steps

1. **Repo**: clone `https://github.com/willpearlman/WiJoZa.git` if it isn't
   on their computer yet, then `git pull`.
2. **Tools**: check for Python 3.11 (`py -3.11 --version`), Git, AWS CLI,
   ExifTool. Install any missing ones with the winget commands in
   README-KIRO.md. After installing, open a new terminal, or the new commands
   won't be found.
3. **Python env**: `py -3.11 -m venv .venv`, then install requirements.txt
   into it. Use 3.11, not 3.14.
4. **.env**: copy `.env.example` to `.env` and set these model IDs:
   ```
   AWS_REGION=us-east-1
   BEDROCK_AGENT_MODEL_ID=us.anthropic.claude-sonnet-5
   BEDROCK_TASTE_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0
   ```
   The workshop account blocks the 5.5 models (AccessDenied). Leave CULL_ROOT
   and SCORES_PATH to their lane file.
5. **AWS login**: they get credentials from the hackathon's AWS Workshop page
   (Kiro Pro keys are NOT AWS credentials). Create
   `%USERPROFILE%\.aws\credentials` with blank lines for them to fill in, and
   open it in Notepad:
   ```
   [default]
   aws_access_key_id=
   aws_secret_access_key=
   aws_session_token=
   ```
   They paste only the values after each `=` (no quotes, no `export`/`$env:`).
   Never ask them to paste keys into chat. The credentials expire after a few
   hours, and they refresh by pasting a new set into the same file.
6. **Verify**: `aws sts get-caller-identity` prints an account, then one
   Bedrock Converse call to each model ID in .env replies. `pytest -q` failing
   is expected until the solver lands.

## Rules

- Never commit `.env` or credentials (.gitignore covers `.env`).
- Setup changes no repo files, so there is nothing to push.
- Commit or push only when the user asks; this team commits to `main`, in its
  own files only (see the ownership table in README-KIRO.md).
