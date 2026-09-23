"""Correct grade bands that claim a failing range is a pass.

Revision ID: e93a5c17b204
Revises: d82b4f0c17ae

`b71f2c8ea940` introduced `grade_bands.is_pass` with `server_default=true`, which
is the safe-looking choice and was the wrong one: every band that already existed
became a passing band, **including F**. On the live database the ladder read
0–49.99 = "F", `is_pass = true`, against a scheme whose passing mark is 50.

That is not cosmetic. `Performance.is_pass` and `Transcript.is_pass` are both
read straight off the matched band, so every student who had failed was recorded
as having passed -- on the transcript, which is the one document in this system
that gets handed to an employer. Nothing in the product would have shown it,
because a pass is exactly what a correct system also reports for most students.

**A blanket `false` would have been equally wrong** (every student fails, and the
institution's real passing bands would need re-entering), which is presumably why
`true` was chosen. The actual fix is to derive it, and to derive it only where the
stored value is a **contradiction**: a band whose entire range sits below its own
scheme's passing percentage cannot be a pass, whatever anybody typed. That is the
one case where correcting the data cannot be overriding a deliberate decision.

Bands that *straddle* the passing mark (min below it, max at or above) are left
exactly as they are: which side of the line they fall on is a judgement the
institution is entitled to make, and guessing at it is how a migration destroys
a policy it does not understand (§44).

Nothing is flipped **to** true, for the same reason. An institution that has
deliberately marked a high band as non-passing -- a competency scheme, a
distinction-only award -- would not thank a deploy for reversing it.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "e93a5c17b204"
down_revision = "d82b4f0c17ae"
branch_labels = None
depends_on = None


#: A band entirely below its scheme's passing mark, flagged as passing. Joined
#: to `grading_schemes` rather than compared against a constant: the passing
#: percentage is per-scheme and configurable (§13), so hard-coding 50 here would
#: silently mis-correct an institution that passes at 40.
_CONTRADICTORY = sa.text(
    """
    UPDATE grade_bands AS b
       SET is_pass = false
      FROM grading_schemes AS s
     WHERE b.scheme_id = s.id
       AND b.is_pass IS TRUE
       AND b.max_score < s.passing_percentage
    """
)


def upgrade() -> None:
    result = op.get_bind().execute(_CONTRADICTORY)
    # Printed rather than logged silently: a data correction that touches
    # transcript outcomes is something the operator running the upgrade should
    # see a count for.
    print(f"grade_bands: corrected {result.rowcount} band(s) that marked a failing range as a pass.")

    # The default is what created the problem, so it goes. A band inserted from
    # now on must state whether it passes; the application always does, and a
    # fixture that forgets should fail loudly rather than inherit "pass".
    op.alter_column("grade_bands", "is_pass", server_default=None)


def downgrade() -> None:
    op.alter_column("grade_bands", "is_pass", server_default=sa.true())
    # The corrected rows are deliberately not restored. Re-marking a failing
    # band as a pass is the defect, not a state worth being able to return to.
