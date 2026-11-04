-- v5 SQLite schema for the From simulation Memory subsystem.
--
-- Open with WAL so the tick thread and any read-only consumer don't block
-- each other. Foreign keys ON so a pruned cycle cascades to its dependent
-- per-cycle rows (sub_main_characters and personality_drift intentionally
-- do NOT use a cycle FK — they outlive any one cycle).

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- One row per cycle that the universe has lived through. The currently
-- ongoing cycle's row has outcome="ongoing"; older rows are "wiped".
CREATE TABLE IF NOT EXISTS cycles (
    cycle_no            INTEGER PRIMARY KEY,
    started_real_ts     TEXT NOT NULL,
    ended_real_ts       TEXT,
    outcome             TEXT NOT NULL DEFAULT 'ongoing'
);

-- Journal fragments — the one thing legacy.py persists outside of the
-- in-memory Legacy list. Burned [0,1].
CREATE TABLE IF NOT EXISTS journal_fragments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_no            INTEGER NOT NULL,
    text                TEXT NOT NULL,
    burned              REAL NOT NULL DEFAULT 0.0,
    real_ts             TEXT NOT NULL,
    FOREIGN KEY (cycle_no) REFERENCES cycles(cycle_no) ON DELETE CASCADE
);

-- Character memory rows — the canonical "what happened to this agent"
-- store. Buffered + executemany-flushed on tick.
CREATE TABLE IF NOT EXISTS character_memory (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_no            INTEGER NOT NULL,
    tick                INTEGER NOT NULL,
    character_id        TEXT NOT NULL,
    kind                TEXT NOT NULL,
    subject             TEXT NOT NULL DEFAULT '',
    detail              TEXT NOT NULL DEFAULT '',
    payload             TEXT NOT NULL DEFAULT '',
    real_ts             TEXT NOT NULL,
    FOREIGN KEY (cycle_no) REFERENCES cycles(cycle_no) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_char_mem_lookup
    ON character_memory (character_id, kind, tick DESC);

-- Inventory churn log — every pickup/drop/use writes a row with the new
-- post-change total. Agent B uses this for recall + the snapshot summary
-- is derived directly off the live Character.inventory dict.
CREATE TABLE IF NOT EXISTS character_inventory (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_no            INTEGER NOT NULL,
    tick                INTEGER NOT NULL,
    character_id        TEXT NOT NULL,
    item                TEXT NOT NULL,
    delta               INTEGER NOT NULL,
    total               INTEGER NOT NULL,
    real_ts             TEXT NOT NULL,
    FOREIGN KEY (cycle_no) REFERENCES cycles(cycle_no) ON DELETE CASCADE
);

-- Sub-main characters: promoted NPCs that survive across wipes as
-- tombstones (died_at_cycle non-null means they were lost). These rows
-- are NOT cascade-deleted by cycle prune.
CREATE TABLE IF NOT EXISTS sub_main_characters (
    npc_id              TEXT PRIMARY KEY,
    full_name           TEXT NOT NULL,
    promoted_at_cycle   INTEGER NOT NULL,
    promoted_at_tick    INTEGER NOT NULL,
    reason              TEXT NOT NULL DEFAULT '',
    score               REAL NOT NULL DEFAULT 0.0,
    died_at_cycle       INTEGER,
    died_at_tick        INTEGER,
    cause_of_death      TEXT
);

CREATE INDEX IF NOT EXISTS idx_submain_alive
    ON sub_main_characters (died_at_cycle);

-- Personality drift: persistent per-character trait deltas, mirrored from
-- the in-memory Legacy each flush. Never pruned.
CREATE TABLE IF NOT EXISTS personality_drift (
    character_name      TEXT NOT NULL,
    trait               TEXT NOT NULL,
    delta               REAL NOT NULL,
    updated_at_cycle    INTEGER NOT NULL,
    PRIMARY KEY (character_name, trait)
);

-- Building breach marks — per-cycle so the post-prune Legacy reflects
-- only the cycles we still remember.
CREATE TABLE IF NOT EXISTS building_breach_marks (
    cycle_no            INTEGER NOT NULL,
    building_id         TEXT NOT NULL,
    count               INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (cycle_no, building_id),
    FOREIGN KEY (cycle_no) REFERENCES cycles(cycle_no) ON DELETE CASCADE
);
