# Code Diver: install and check

Install on macOS or Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/iuriimedvedev-dev/code-diver/HEAD/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

PASS: installation and setup finish; in a terminal, enter the team profile URL
or file path when asked, then credentials at the hidden prompt.
FAIL: stop and follow the printed fix.
This command requires a published compatible release in the configured repository;
availability is not asserted here.

Repair setup or complete it interactively:

```sh
code-diver setup
```

PASS: setup completes. FAIL: follow the printed fix and run setup again.
Enter requested credentials only at the prompt, never in a command.

```sh
code-diver setup --profile /path/to/team-profile.toml
```

PASS: setup completes with the supplied team profile. FAIL: ask your team for
the correct profile and retry.

Check readiness:

```sh
code-diver doctor
```

PASS: all checks pass. FAIL: follow each printed fix, rerun setup, then doctor.
If installation failed before setup, retry the install command after resolving
the reported download or checksum failure. If the command is not found, run the
PATH command above. If a check still fails, send the FAIL and fix lines to your
team, with credentials removed.