import sqlite3, unittest
from script_creation import init_numbers

class NumberTests(unittest.TestCase):
 def test_history_stability_and_no_reuse(self):
  db=sqlite3.connect(':memory:')
  db.execute('CREATE TABLE script_creative_tasks(id TEXT PRIMARY KEY,created REAL)')
  db.executemany('INSERT INTO script_creative_tasks VALUES (?,?)',[('late',20),('early',10),('same-b',30),('same-a',30)])
  init_numbers(db)
  self.assertEqual(db.execute('SELECT task_id,number FROM script_creative_numbers ORDER BY number').fetchall(),[('early',1),('late',2),('same-a',3),('same-b',4)])
  init_numbers(db)
  db.execute("DELETE FROM script_creative_tasks WHERE id='same-b'")
  db.execute("INSERT INTO script_creative_tasks VALUES('new',40)")
  db.execute("INSERT INTO script_creative_numbers(task_id) VALUES('new')")
  init_numbers(db)
  self.assertEqual(db.execute("SELECT number FROM script_creative_numbers WHERE task_id='new'").fetchone()[0],5)
  self.assertEqual(db.execute('SELECT count(*) FROM script_creative_numbers').fetchone()[0],5)
