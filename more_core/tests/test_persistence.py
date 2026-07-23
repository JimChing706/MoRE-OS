"""Tests for SQLite persistence backends."""


import pytest

from more_core.memory.sqlite_store import SQLiteMemoryStore
from more_core.memory.store import MemoryEntry, MemoryKind
from more_core.evolution.sqlite_archive import SQLiteEvolutionArchive
from more_core.evolution.archive import EvolvedAgent


@pytest.fixture
def mem_db(tmp_path):
    db = tmp_path / "memory.db"
    store = SQLiteMemoryStore(str(db))
    yield store
    store.close()


@pytest.fixture
def evo_db(tmp_path):
    db = tmp_path / "evolution.db"
    archive = SQLiteEvolutionArchive(str(db))
    yield archive
    archive.close()


class TestSQLiteMemoryStore:
    def test_put_and_list(self, mem_db):
        mem_db.put(MemoryEntry(content="hello", kind=MemoryKind.EPISODIC))
        mem_db.put(MemoryEntry(content="world", kind=MemoryKind.SEMANTIC))
        assert len(mem_db.list()) == 2
        assert len(mem_db.list(MemoryKind.EPISODIC)) == 1

    def test_search(self, mem_db):
        mem_db.put(MemoryEntry(content="the quick brown fox", kind=MemoryKind.EPISODIC))
        mem_db.put(MemoryEntry(content="lazy dog", kind=MemoryKind.EPISODIC))
        results = mem_db.search("fox")
        assert len(results) >= 1
        assert "fox" in results[0].content

    def test_stats(self, mem_db):
        mem_db.put(MemoryEntry(content="a", kind=MemoryKind.EPISODIC))
        mem_db.put(MemoryEntry(content="b", kind=MemoryKind.EPISODIC))
        stats = mem_db.stats()
        assert stats.get("episodic", 0) == 2

    def test_persistence_across_instances(self, tmp_path):
        db = str(tmp_path / "persist.db")
        store1 = SQLiteMemoryStore(db)
        store1.put(MemoryEntry(content="persisted", kind=MemoryKind.SEMANTIC))
        store1.close()

        store2 = SQLiteMemoryStore(db)
        results = store2.search("persisted")
        assert len(results) >= 1
        store2.close()


class TestSQLiteEvolutionArchive:
    def test_add_and_get(self, evo_db):
        agent = EvolvedAgent(
            id="a1", parent_id=None, generation=0,
            branch="main", code="test", performance=0.5,
        )
        evo_db.add(agent)
        assert evo_db.get("a1") is not None
        assert evo_db.get("a1").performance == 0.5

    def test_best(self, evo_db):
        evo_db.add(EvolvedAgent(id="a1", parent_id=None, generation=0, branch="main", code="", performance=0.3))
        evo_db.add(EvolvedAgent(id="a2", parent_id="a1", generation=1, branch="main", code="", performance=0.8))
        best = evo_db.best("main")
        assert best.id == "a2"

    def test_persistence_across_instances(self, tmp_path):
        db = str(tmp_path / "evo_persist.db")
        a1 = SQLiteEvolutionArchive(db)
        a1.add(EvolvedAgent(id="x1", parent_id=None, generation=0, branch="main", code="hello", performance=0.9))
        a1.close()

        a2 = SQLiteEvolutionArchive(db)
        assert a2.get("x1") is not None
        assert a2.get("x1").code == "hello"
        a2.close()
