"""
test_fuzzy_search.py - Automated Test Suite for CLI Fuzzy Finder
================================================================
Comprehensive unit tests using Python's standard unittest library.
Tests:
1. Exact matches, prefix matches, and non-contiguous subsequence matches.
2. Case-insensitivity and special path characters (/ . _ -).
3. Empty queries, whitespace queries, and non-existent queries.
4. Duplicate paths and empty dataset edge cases.
5. Path deletion with branch pruning and bitmask recomputation.
6. Custom MinHeap invariants, push/pop mechanics, and Top-K bounding.
7. Two-pass fzf alignment and boundary-aware scoring bonuses.
8. Algorithmic telemetry and pruning efficiency measurements.

Execution:
    python -m unittest test_fuzzy_search.py -v
"""

import unittest
from typing import List

from data_structures import MinHeap, Trie, bit, mask_of
from fuzzy_search import DEFAULT_DATASET, FuzzyEngine, Match, Scorer


class TestDataStructures(unittest.TestCase):
    """Unit tests for low-level data structures (Trie, Bitmask, MinHeap)."""

    def setUp(self) -> None:
        self.trie = Trie()

    def test_bitmask_hashing(self) -> None:
        """Verifies that bit() and mask_of() compute accurate 64-bit signatures."""
        b_a = bit("a")
        b_A = bit("A")
        # Case insensitivity property
        self.assertEqual(b_a, b_A)
        # Non-zero bit signature
        self.assertGreater(b_a, 0)

        # Composite mask property
        m_app = mask_of("app")
        self.assertEqual(m_app & bit("a"), bit("a"))
        self.assertEqual(m_app & bit("p"), bit("p"))
        # Character not in text should have 0 bit overlap
        self.assertEqual(m_app & bit("z"), 0)

    def test_trie_insert_and_exact_search(self) -> None:
        """Tests standard Trie insert and exact O(m) lookup."""
        paths = ["src/App.java", "src/main.py", "docs/index.html"]
        for p in paths:
            self.trie.insert(p)

        self.assertEqual(self.trie.size, 3)
        self.assertTrue(self.trie.search("src/App.java"))
        self.assertTrue(self.trie.search("src/main.py"))
        # Prefix exists, but string does not terminate
        self.assertFalse(self.trie.search("src"))
        self.assertFalse(self.trie.search("src/nonexistent.py"))

    def test_trie_starts_with_prefix(self) -> None:
        """Tests prefix search returning subtree paths."""
        self.trie.insert("src/components/Header.jsx")
        self.trie.insert("src/components/Footer.jsx")
        self.trie.insert("src/main.py")

        results = self.trie.starts_with("src/components/")
        self.assertEqual(len(results), 2)
        self.assertIn("src/components/Header.jsx", results)
        self.assertIn("src/components/Footer.jsx", results)
        self.assertNotIn("src/main.py", results)

    def test_trie_delete_and_branch_pruning(self) -> None:
        """Tests recursive branch pruning and mask recomputation upon deletion."""
        self.trie.insert("src/App.java")
        self.trie.insert("src/main.py")

        self.assertEqual(self.trie.size, 2)
        initial_nodes = self.trie.total_nodes

        # Delete nonexistent string
        self.assertFalse(self.trie.delete("does/not/exist.txt"))
        self.assertEqual(self.trie.size, 2)

        # Delete valid string
        deleted = self.trie.delete("src/App.java")
        self.assertTrue(deleted)
        self.assertEqual(self.trie.size, 1)
        self.assertFalse(self.trie.search("src/App.java"))
        self.assertTrue(self.trie.search("src/main.py"))
        # Dead nodes should have been pruned
        self.assertLess(self.trie.total_nodes, initial_nodes)

    def test_min_heap_invariants(self) -> None:
        """Verifies custom MinHeap push, pop, peek, and heapify behavior."""
        heap = MinHeap()
        self.assertEqual(len(heap), 0)
        self.assertFalse(bool(heap))

        with self.assertRaises(IndexError):
            heap.peek()
        with self.assertRaises(IndexError):
            heap.pop()

        elements = [42, 10, 88, 5, 23, 7]
        for x in elements:
            heap.push(x)

        self.assertEqual(len(heap), 6)
        self.assertEqual(heap.peek(), 5)

        # Elements must emerge in strictly non-decreasing order
        popped = [heap.pop() for _ in range(len(heap))]
        self.assertEqual(popped, sorted(elements))

    def test_min_heap_heapify(self) -> None:
        """Tests O(n) bottom-up heap construction."""
        data = [99, 12, 45, 1, 33, 67, 8]
        heap = MinHeap.heapify(data)
        self.assertEqual(heap.peek(), 1)
        popped = [heap.pop() for _ in range(len(heap))]
        self.assertEqual(popped, sorted(data))


class TestFuzzySearchEngine(unittest.TestCase):
    """Unit tests for subsequence matching, alignment, and scoring heuristics."""

    def setUp(self) -> None:
        self.engine = FuzzyEngine()
        self.sample_dataset = [
            "src/App.java",
            "src/main.java",
            "src/components/App.jsx",
            "src/components/Header.jsx",
            "application.properties",
            "README.md",
            "docs/application.md",
            "config/database.json",
        ]
        self.engine.load_dataset(self.sample_dataset)

    def test_exact_match_retrieval(self) -> None:
        """Tests exact match returning highest score."""
        matches, _ = self.engine.search("README.md", k=5)
        self.assertTrue(len(matches) >= 1)
        self.assertEqual(matches[0].path, "README.md")
        self.assertGreaterEqual(matches[0].score, 90)

    def test_non_contiguous_subsequence_match(self) -> None:
        """Tests that 'smp' matches 'src/main.py' and 'src/components/App.jsx'."""
        self.engine.add("src/main.py")
        matches, _ = self.engine.search("smp", k=5)
        matched_paths = [m.path for m in matches]
        # s..m..p appears in src/main.py
        self.assertIn("src/main.py", matched_paths)

    def test_case_insensitive_matching(self) -> None:
        """Tests that UPPERCASE, lowercase, and mixed queries match identically."""
        matches_lower, _ = self.engine.search("app", k=5)
        matches_upper, _ = self.engine.search("APP", k=5)
        matches_mixed, _ = self.engine.search("ApP", k=5)

        paths_lower = [m.path for m in matches_lower]
        paths_upper = [m.path for m in matches_upper]
        paths_mixed = [m.path for m in matches_mixed]

        self.assertEqual(paths_lower, paths_upper)
        self.assertEqual(paths_lower, paths_mixed)

    def test_two_pass_alignment_window_tightness(self) -> None:
        """Verifies fzf-v1 two-pass alignment locates the tightest character window."""
        # Candidate has multiple 'a's: "a/b/c/apple.txt"
        cand = "a/b/c/apple.txt"
        pos = Scorer.align(cand, "app")
        self.assertIsNotNone(pos)
        # Tightest window for 'app' is inside 'apple' (indices 6, 7, 8), not using index 0
        self.assertEqual(pos, [6, 7, 8])

    def test_scoring_word_boundary_bonus(self) -> None:
        """Verifies boundary matches score higher than middle-of-word matches."""
        # 'App' starts right after '/' (word boundary)
        sc1, _ = Scorer.score("src/App.java", "app")
        # 'app' buried inside a word
        sc2, _ = Scorer.score("src/wrapper_tool.java", "app")
        self.assertGreater(sc1, sc2)

    def test_scoring_consecutive_run_bonus(self) -> None:
        """Verifies consecutive matched characters receive higher scores than scattered characters."""
        sc_consec, _ = Scorer.score("xxappxx.txt", "app")
        sc_gapped, _ = Scorer.score("xxaxpxpxx.txt", "app")
        self.assertGreater(sc_consec, sc_gapped)

    def test_top_k_bounding_property(self) -> None:
        """Verifies that Top-K MinHeap returns at most K items even with many matches."""
        # Query 'a' matches almost everything in sample_dataset (7 items)
        matches_k3, telemetry = self.engine.search("a", k=3)
        self.assertEqual(len(matches_k3), 3)
        self.assertGreater(telemetry["heap_evictions"], 0)

        matches_k10, _ = self.engine.search("a", k=10)
        self.assertLessEqual(len(matches_k10), 10)

    def test_empty_query_and_whitespace(self) -> None:
        """Verifies empty or whitespace queries return empty results without error."""
        matches1, tel1 = self.engine.search("")
        self.assertEqual(matches1, [])
        self.assertEqual(tel1["nodes_visited"], 0)

        matches2, tel2 = self.engine.search("   ")
        self.assertEqual(matches2, [])

    def test_no_match_query(self) -> None:
        """Verifies non-matching queries return 0 results with bitmask pruning."""
        matches, telemetry = self.engine.search("xyz123")
        self.assertEqual(matches, [])
        self.assertGreater(telemetry["subtrees_pruned"], 0)

    def test_query_longer_than_candidate(self) -> None:
        """Verifies queries longer than any stored path return cleanly."""
        long_query = "a" * 200
        matches, _ = self.engine.search(long_query)
        self.assertEqual(matches, [])

    def test_duplicate_path_insertion(self) -> None:
        """Verifies inserting duplicates does not corrupt Trie size or cause errors."""
        initial_size = self.engine.trie.size
        self.engine.add("src/App.java")
        self.engine.add("src/App.java")
        self.assertEqual(self.engine.trie.size, initial_size)

    def test_empty_dataset(self) -> None:
        """Verifies search over empty engine does not crash."""
        empty_engine = FuzzyEngine()
        matches, tel = empty_engine.search("app")
        self.assertEqual(matches, [])
        self.assertEqual(tel["total_paths"], 0)


if __name__ == "__main__":
    unittest.main()
