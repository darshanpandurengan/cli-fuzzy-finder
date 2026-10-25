"""
fuzzy_search.py - Subsequence Alignment, Scoring, and Search Coordination
==========================================================================
Implements:
1. Two-pass fzf-v1 alignment algorithm (tightest match window).
2. Boundary-, camelCase-, and consecutiveness-aware relevance scoring.
3. Match dataclass for result records with matched character indices.
4. Built-in demonstration dataset (developer filepaths).
5. FuzzyEngine coordinating Trie candidate retrieval, scoring, and MinHeap Top-K selection.

Zero external dependencies - standard library only.
"""

from dataclasses import dataclass
import os
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from data_structures import MinHeap, Trie


# Word boundary separator characters
SEPARATORS = set("/._- ")


# =====================================================================
# 1. MATCH DATA STRUCTURE & SCORING HEURISTICS
# =====================================================================

@dataclass
class Match:
    """
    Encapsulates a ranked search result.
    Attributes:
        path: The matched candidate path.
        score: Normalized relevance score in range [0, 100].
        positions: List of 0-based indices corresponding to matched characters.
    """
    path: str
    score: int
    positions: List[int]


class Scorer:
    """
    Subsequence alignment and relevance scoring engine modeled after fzf-v1.
    """

    @staticmethod
    def align(cand: str, q: str) -> Optional[List[int]]:
        """
        Computes the tightest subsequence alignment window via two passes:
        1. Forward Pass: Finds the earliest occurrence of query chars to locate endpoint.
        2. Backward Pass: Scans backwards from endpoint to minimize window length.
        
        Returns:
            Sorted list of matched character indices, or None if not a subsequence.
        """
        if not q or not cand:
            return None

        cand_low = cand.lower()
        q_low = q.lower()
        len_q = len(q_low)
        len_cand = len(cand_low)

        # 1. Forward Pass: find earliest match end
        qi = 0
        end_idx = -1
        for i in range(len_cand):
            if cand_low[i] == q_low[qi]:
                qi += 1
                if qi == len_q:
                    end_idx = i
                    break

        if end_idx < 0:
            return None  # Query is not a subsequence of candidate

        # 2. Backward Pass: scan from end_idx backwards to tighten matching window
        pos: List[int] = []
        qi = len_q - 1
        for i in range(end_idx, -1, -1):
            if cand_low[i] == q_low[qi]:
                pos.append(i)
                qi -= 1
                if qi < 0:
                    break

        pos.reverse()
        return pos

    @staticmethod
    def score(cand: str, q: str) -> Tuple[int, List[int]]:
        """
        Evaluates relevance score [0, 100] based on contextual character positioning:
          +10 Base score per matched character
          +12 Word-boundary bonus (index 0 or preceded by / . _ - space)
          +8  CamelCase hump bonus (lowercase immediately followed by uppercase)
          +8  Consecutive character run bonus
          -1  Gap penalty per skipped character (capped at 5)
          +6  File name match bonus (first matched char resides after last '/')
          -0.3 Total path length penalty (prioritizes concise, direct paths)
          
        Returns:
            Tuple of (normalized score 0..100, list of matched positions)
        """
        pos = Scorer.align(cand, q)
        if pos is None:
            return 0, []

        raw_score = 0.0
        prev_idx = -2

        for idx in pos:
            raw_score += 10.0  # Base point

            # Word boundary bonus
            if idx == 0 or cand[idx - 1] in SEPARATORS:
                raw_score += 12.0
            # CamelCase hump bonus
            elif cand[idx].isupper() and cand[idx - 1].islower():
                raw_score += 8.0

            # Consecutive character run bonus vs gap penalty
            if idx == prev_idx + 1:
                raw_score += 8.0
            elif prev_idx >= 0:
                gap = idx - prev_idx - 1
                raw_score -= min(float(gap), 5.0)

            prev_idx = idx

        # Bonus if matching starts within the filename (after last slash)
        last_slash = cand.rfind("/")
        if last_slash < 0 or pos[0] > last_slash:
            raw_score += 6.0

        # Subtle penalty for overall path length to favor shorter matches
        raw_score -= 0.3 * len(cand)

        # Normalization factor: theoretical ideal score for query of length m
        theoretical_max = 18.0 * len(q) + 10.0
        normalized = round(100.0 * raw_score / theoretical_max)
        clamped_score = max(0, min(100, int(normalized)))

        return clamped_score, pos


# =====================================================================
# 2. BUILT-IN DEMOSTRATION DATASET
# =====================================================================

DEFAULT_DATASET = [
    "src/App.java",
    "src/main.java",
    "src/main.py",
    "src/components/App.jsx",
    "src/components/Header.jsx",
    "src/components/Footer.jsx",
    "src/components/Sidebar.tsx",
    "src/components/UserProfile.vue",
    "src/utils/string_helpers.py",
    "src/utils/file_parser.py",
    "src/utils/network_client.go",
    "src/controllers/AuthController.cs",
    "src/controllers/PaymentController.cs",
    "src/models/User.kt",
    "src/models/Order.kt",
    "docs/application.md",
    "docs/architecture_overview.pdf",
    "docs/api_v1_specification.yaml",
    "docs/security_audit_report.docx",
    "application.properties",
    "application.yml",
    "config/database.json",
    "config/redis_cluster.conf",
    "config/nginx.conf",
    "config/ssl/cert.pem",
    "config/ssl/private_key.key",
    "scripts/deploy_production.sh",
    "scripts/database_migration.sql",
    "scripts/run_benchmarks.py",
    "tests/unit/test_app.py",
    "tests/integration/test_auth_flow.py",
    "tests/stress/load_test_suite.rs",
    "README.md",
    "LICENSE",
    ".gitignore",
    ".dockerignore",
    "Dockerfile",
    "docker-compose.yml",
    "package.json",
    "tsconfig.json",
    "pyproject.toml",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "Makefile",
    "public/favicon.ico",
    "public/index.html",
    "assets/logo_dark_mode.png",
    "assets/hero_banner.svg",
    "assets/fonts/Inter-Regular.ttf",
]


# =====================================================================
# 3. FUZZY SEARCH ENGINE & COORDINATOR
# =====================================================================

class FuzzyEngine:
    """
    Search coordination layer.
    Owns the Trie data structure, loads path datasets, retrieves pruned candidates,
    computes scores, and uses MinHeap for Top-K candidate extraction.
    """

    def __init__(self) -> None:
        self.trie = Trie()
        self.source_label = "Built-in Dataset"
        # Absolute folder the stored relative paths came from (None for demo/stdin data)
        self.root_dir: Optional[str] = None

    def add(self, path: str) -> None:
        """Adds a single path to the search index."""
        cleaned = path.strip()
        if cleaned:
            self.trie.insert(cleaned)

    def remove(self, path: str) -> bool:
        """Deletes a path from the search index."""
        return self.trie.delete(path.strip())

    def load_dataset(self, paths: Iterable[str], label: str = "Custom Dataset",
                     root_dir: Optional[str] = None) -> int:
        """Re-initializes the Trie with a specified collection of strings."""
        self.trie = Trie()
        self.root_dir = root_dir
        count = 0
        for p in paths:
            cleaned = p.strip()
            if cleaned:
                self.trie.insert(cleaned)
                count += 1
        self.source_label = label
        return count

    def load_default_dataset(self) -> int:
        """Loads the built-in realistic developer dataset."""
        return self.load_dataset(DEFAULT_DATASET, label="Built-in Demo Data")

    def load_directory(self, root_dir: str, max_files: int = 5000) -> int:
        """
        Scans a local filesystem folder using standard library os.walk.
        Converts paths to forward-slash relative paths.
        """
        if not os.path.exists(root_dir):
            raise FileNotFoundError(f"Directory not found: {root_dir}")

        collected_paths: List[str] = []
        for root, _, files in os.walk(root_dir):
            for file_name in files:
                abs_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(abs_path, root_dir).replace("\\", "/")
                collected_paths.append(rel_path)
                if len(collected_paths) >= max_files:
                    break
            if len(collected_paths) >= max_files:
                break

        return self.load_dataset(
            collected_paths,
            label=f"Folder: {os.path.basename(root_dir) or root_dir}",
            root_dir=os.path.abspath(root_dir),
        )

    def resolve_path(self, path: str) -> Optional[str]:
        """
        Converts a stored result path into a real absolute path on disk.
        Returns None when the path doesn't exist (e.g. built-in demo data).
        """
        if self.root_dir:
            full = os.path.normpath(os.path.join(self.root_dir, path))
        elif os.path.isabs(path):
            full = os.path.normpath(path)
        else:
            return None
        return full if os.path.exists(full) else None

    def search(self, query: str, k: int = 10) -> Tuple[List[Match], Dict[str, Any]]:
        """
        Executes a fuzzy query over all stored paths.
        Steps:
        1. Trim and normalize query string.
        2. Retrieve candidates via Bitmask-pruned Trie DFS traversal.
        3. Score candidates with Scorer.score().
        4. Retain Top-K candidates in O(C log K) using custom MinHeap.
        5. Return sorted results descending by score, along with telemetry metrics.
        """
        q = query.strip()
        if not q:
            return [], {
                "nodes_visited": 0,
                "subtrees_pruned": 0,
                "total_nodes": self.trie.total_nodes,
                "total_paths": self.trie.size,
                "candidates_found": 0,
                "heap_evictions": 0,
                "latency_us": 0,
                "pruning_ratio": 0.0,
            }

        start_time = time.perf_counter_ns()

        # Step 2: Retrieve candidates via Trie DFS with bitmask pruning
        candidates, telemetry = self.trie.candidates(q)

        # Step 3 & 4: Score and Top-K filter via custom MinHeap
        heap = MinHeap()
        heap_evictions = 0

        for cand in candidates:
            score, positions = Scorer.score(cand, q)
            # Tuple: (score, -len(cand), cand, positions)
            # Min-heap orders primarily by score, tie-breaking by shorter path length
            heap.push((score, -len(cand), cand, positions))
            if len(heap) > k:
                heap.pop()  # Evict lowest-scoring candidate in O(log K)
                heap_evictions += 1

        # Step 5: Extract from heap and sort descending
        raw_items = [heap.pop() for _ in range(len(heap))]
        matches = [Match(cand, sc, pos) for sc, _, cand, pos in raw_items]
        # Sort descending: highest score first, then shorter path, then alphabetical
        matches.sort(key=lambda m: (-m.score, len(m.path), m.path))

        elapsed_ns = time.perf_counter_ns() - start_time
        latency_us = round(elapsed_ns / 1000, 2)

        # Compute pruning efficiency ratio
        visited = telemetry["nodes_visited"]
        pruned = telemetry["subtrees_pruned"]
        total_eval = visited + pruned
        pruning_ratio = round((pruned / total_eval * 100), 1) if total_eval > 0 else 0.0

        full_telemetry = {
            "nodes_visited": visited,
            "subtrees_pruned": pruned,
            "total_nodes": self.trie.total_nodes,
            "total_paths": self.trie.size,
            "candidates_found": len(candidates),
            "heap_evictions": heap_evictions,
            "latency_us": latency_us,
            "pruning_ratio": pruning_ratio,
        }

        return matches, full_telemetry
