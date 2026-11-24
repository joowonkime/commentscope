"""SQLite records for the immutable debate plan, its report and derived agent."""
from commentscope.product.store import decode, encode

DDL = (
    """CREATE TABLE debates (
       id TEXT PRIMARY KEY, room_id TEXT NOT NULL UNIQUE REFERENCES rooms(id),
       protocol TEXT NOT NULL, plan_sha256 TEXT NOT NULL, revision INTEGER NOT NULL,
       state TEXT NOT NULL, data TEXT NOT NULL)""",
    """CREATE TABLE syntheses (
       id TEXT PRIMARY KEY, debate_id TEXT NOT NULL REFERENCES debates(id),
       cutoff_seq INTEGER NOT NULL, protocol TEXT NOT NULL, transcript_sha256 TEXT NOT NULL,
       revision INTEGER NOT NULL, state TEXT NOT NULL, data TEXT NOT NULL,
       UNIQUE(debate_id,cutoff_seq,protocol))""",
    """CREATE TABLE ratifications (
       synthesis_id TEXT NOT NULL REFERENCES syntheses(id), agent_id TEXT NOT NULL,
       proposal_id TEXT NOT NULL, draft_sha256 TEXT NOT NULL, data TEXT NOT NULL,
       PRIMARY KEY(synthesis_id,agent_id,proposal_id))""",
    """CREATE TABLE synthesis_agents (
       id TEXT PRIMARY KEY, synthesis_id TEXT NOT NULL REFERENCES syntheses(id),
       session_id TEXT NOT NULL REFERENCES app_sessions(id), revision INTEGER NOT NULL,
       artifact_sha256 TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(synthesis_id,artifact_sha256))""",
)


def finish(db, debate, report, draft, votes, agent):
    snapshot = report['snapshot']
    db.execute('INSERT INTO syntheses VALUES(?,?,?,?,?,?,?,?)',
               (report['synthesis_id'], debate['debate_id'], snapshot['cutoff_seq'], report['protocol'],
                snapshot['transcript_sha256'], report['revision'], report['outcome'],
                encode({'report': report, 'draft': draft})))
    db.executemany('INSERT INTO ratifications VALUES(?,?,?,?,?)', [
        (report['synthesis_id'], v['agent_id'], v['proposal_id'], v['draft_sha256'], encode(v)) for v in votes
    ])
    if agent is not None:
        db.execute('INSERT INTO synthesis_agents VALUES(?,?,?,?,?,?)',
                   (agent['agent_id'], report['synthesis_id'], agent['session_id'],
                    agent['revision'], agent['artifact_sha256'], encode(agent)))


def load_debate(db, did):
    row = db.execute('SELECT * FROM debates WHERE id=?', (did,)).fetchone()
    return (row['room_id'], decode(row)) if row else (None, None)


def sync_room(db, room):
    if room.get('kind') == 'structured_debate':
        db.execute('UPDATE debates SET state=?, revision=? WHERE room_id=?',
                   (room['state'], room['revision'], room['room_id']))
