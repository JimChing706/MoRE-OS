"""Tests for layer components."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestL0ExecutionLayer:
    """Test suite for L0 Execution Layer."""

    def test_import_layer(self):
        """Test L0 layer can be imported."""
        from more_core.layers import l0_execution
        assert l0_execution is not None


class TestL1Orchestration:
    """Test suite for L1 Orchestration Layer."""

    def test_import_layer(self):
        """Test L1 layer can be imported."""
        from more_core.layers import l1_orchestration
        assert l1_orchestration is not None


class TestL2DGM:
    """Test suite for L2 DGM Evolution Engine."""

    def test_import_dgm(self):
        """Test DGM can be imported."""
        from more_core.evolution import dgm
        assert dgm is not None


class TestL3Symbolic:
    """Test suite for L3 Symbolic Layer."""

    def test_import_layer(self):
        """Test L3 layer can be imported."""
        from more_core.layers import l3_symbolic
        assert l3_symbolic is not None


class TestL4Cognition:
    """Test suite for L4 Cognitive Layer."""

    def test_import_layer(self):
        """Test L4 layer can be imported."""
        from more_core.layers import l4_cognition
        assert l4_cognition is not None


class TestL5Metacognition:
    """Test suite for L5 Metacognition Layer."""

    def test_import_hyperagent(self):
        """Test HyperAgent can be imported."""
        from more_core.metacognition import hyperagent
        assert hyperagent is not None