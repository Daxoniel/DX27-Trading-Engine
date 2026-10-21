"""Restart/hash-seed reproducibility and registered session-date checks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from ledger import Journal, initialize


class DurabilityTests(unittest.TestCase):
    def test_replay_survives_process_restart_and_hash_seed_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'journal'; j=Journal(root)
            days=['2026-01-05','2026-01-06','2026-01-07']
            j.create(initialize(days,[days[0],days[2]],25))
            targets=[dict(symbol=x,sector=x) for x in ['Z','A','C']]
            for day in days:
                req=dict(date=day,closes={'Z':19.317,'A':89.123456789,'C':7.2},source_sha256='a'*64)
                if day in (days[0],days[2]): req.update(targets=targets,rank_plan_sha256='b'*64)
                j.append(req)
            expected=j.replay()[1]
            for seed in ('1','37'):
                env=dict(os.environ,PYTHONHASHSEED=seed)
                output=subprocess.check_output([sys.executable,'-c',
                    'from ledger import Journal; import sys; print(Journal(sys.argv[1]).replay()[1])',str(root)],
                    cwd=Path(__file__).parent,env=env,text=True)
                self.assertEqual(output.strip(),expected)

    def test_registered_calendar_means_second_later_session(self):
        import exchange_calendars as xc
        self.assertEqual(xc.__version__,'4.13.2')
        cal=xc.get_calendar('XNYS'); root=Path(__file__).resolve().parents[2]
        registered=json.loads((root/'docs/research/residual-shadow/calendar.json').read_bytes())
        protocol=json.loads((root/'docs/research/residual-shadow/protocol.json').read_bytes())
        rows=registered['planned_cycles']
        self.assertEqual([r['formation'] for r in rows],protocol['prospective_evaluation_registration']['planned_formations'])
        for row in rows:
            formation=cal.date_to_session(row['formation'])
            execution=cal.sessions[cal.sessions.get_loc(formation)+2]
            self.assertEqual(row['execution'],str(execution.date()))
            self.assertEqual(row['formation_close'],cal.session_close(formation).isoformat())
            self.assertEqual(row['execution_open'],cal.session_open(execution).isoformat())
            self.assertEqual(row['execution_close'],cal.session_close(execution).isoformat())
        self.assertEqual(rows[0]['execution'],'2026-11-03')
        self.assertTrue(cal.is_session(registered['terminal_mark']))


if __name__=='__main__': unittest.main()
