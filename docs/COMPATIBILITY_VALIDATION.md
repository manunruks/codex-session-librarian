# Bounded compatibility validation: assistant tool phases

On 2026-11-02, a synthetic Claude/canonical assistant event containing commentary
text and tool calls lost the tool-call phase when converted through Codex. Codex
stores text and calls as separate response items; CSL now retains the call phase
in top-level `portability_phase` metadata and restores it on normalization.
No native tool schema or execution permission is translated.

The regression failed before the correction for both JSON and text tool arguments.
It now checks phase and block content through Claude → Codex → Claude. An
additional CLI test checks export/import installation between conversions.
The offline suite at that checkpoint ran 183 tests: 167 passed and 16 were skipped.
The separate secret-review change adds its own deterministic coverage.

Installed Codex CLI 0.166.0 and Claude Code 2.1.308 each reconstructed a request
against rejecting localhost endpoints using disposable homes and fake keys.
The requests contained the synthetic tool facts and excluded quarantined source
policy. All three historical tool calls retained commentary metadata during CSL
normalization. This checks native loading/transport, without model generation.

Three actual Codex continuations then passed with `gpt-6.1-sol`, confirmed in the
synthetic sessions' turn context: original Codex history, Codex → Codex and
Claude → Codex. Fixtures included mixed commentary/tool messages, parallel JSON
and text calls, a failed historical result, corrected decisions and references.
The recall question did not supply the expected values. Zero tools executed;
source hashes stayed unchanged; all three historical call phases remained present
after continuation. Reported consumption was 25,732 input and 137 output tokens,
with zero cached input, charged to the existing ChatGPT plan rather than assigned
an invented dollar price. Three model attempts were used out of a maximum 24.

Claude live continuation was not attempted because the existing private credential
helper could not retrieve its dedicated credentials. No login, consent, account
change or automatic retry was performed. Claude reservation and reported spend
were USD 0. Thus Claude has native loader evidence for this fixture, while the
real-model continuation evidence covers destination Codex only. This is bounded
synthetic evidence, not universal CLI/backend compatibility or model-context fit.
Raw synthetic histories, credentials and provider reports remain outside Git.

## 0.1.0 release-candidate regression

The integrated candidate was checked on 2026-11-02 using the installed optional
media environment, required bubblewrap, and both native localhost loader checks.
All **197 tests passed**, with no skipped tests. HOME, CODEX_HOME and
CLAUDE_CONFIG_DIR were temporary isolated directories. This run did not perform
paid inference or use personal histories. Python 3.11/3.13 CI results must be
reported separately for the final pushed commit; a local pass is not a CI pass.
