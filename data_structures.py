"""
data_structures.py - Core Data Structures for CLI Fuzzy Finder
==============================================================
Implements:
1. Bitmask helpers for 64-bit character signatures.
2. TrieNode and Trie with subtree character bitmask pruning and branch deletion.
3. Custom array-based binary MinHeap for O(C log K) Top-K element retention.

Zero external dependencies - standard library only.
"""

from typing import Any, Dict, Generator, Iterable, List, Optional, Tuple


# =====================================================================
# 1. BITMASK MANIPULATION HELPERS
# =====================================================================

def bit(ch: str) -> int:
    """
    Computes a 64-bit signature for an alphanumeric or punctuation character.
    Maps lowercase character ordinals into a 6-bit bucket (0..63).
    Bitwise collisions only weaken branch pruning slightly; they NEVER
    produce false negatives (soundness property).
    """
    return 1 << (ord(ch.lower()) & 63)


def mask_of(text: str) -> int:
    """
    Computes the cumulative bitwise-OR mask of all characters in text.
    Time Complexity: O(len(text))
    Space Complexity: O(1)
    """
    m = 0
    for ch in text:
        m |= bit(ch)
    return m


# =====================================================================
# 2. TRIE WITH SUBTREE CHARACTER BITMASKS
# =====================================================================

class TrieNode:
    """
    A single node in the prefix Trie.
    Attributes:
        children: Dictionary mapping characters to child TrieNodes.
        is_end: True if a stored string terminates at this node.
        path: The exact full path string stored (only when is_end is True).
        mask: Bitwise-OR of all characters present in the entire subtree below this node.
    """
    __slots__ = ("children", "is_end", "path", "mask")

    def __init__(self) -> None:
        self.children: Dict[str, "TrieNode"] = {}
        self.is_end: bool = False
        self.path: Optional[str] = None
        self.mask: int = 0


class Trie:
    """
    Prefix Trie augmented with per-node 64-bit subtree character masks.
    Enables:
      - O(L) insertion with suffix bitmask caching.
      - O(m) exact search and O(m + output) prefix traversal.
      - O(L) deletion with automatic branch pruning and mask recomputation.
      - Bitmask-pruned DFS for subsequence candidate retrieval.
    """

    def __init__(self) -> None:
        self.root: TrieNode = TrieNode()
        self.size: int = 0          # Number of unique strings stored
        self.total_nodes: int = 1   # Total TrieNode objects allocated (root included)

    def insert(self, s: str) -> None:
        """
        Inserts a string path into the Trie.
        Precomputes suffix bitmasks from back to front in O(L) so that
        each ancestor's mask accurately reflects all characters beneath it.
        Time Complexity: O(L) where L = len(s)
        Space Complexity: O(L) new nodes worst case
        """
        if not s:
            return

        # suffix[i] holds bitwise-OR of s[i:]
        n = len(s)
        suffix = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            suffix[i] = suffix[i + 1] | bit(s[i])

        node = self.root
        for i, ch in enumerate(s):
            node.mask |= suffix[i]
            if ch not in node.children:
                node.children[ch] = TrieNode()
                self.total_nodes += 1
            node = node.children[ch]

        if not node.is_end:
            node.is_end = True
            node.path = s
            self.size += 1

    def _walk(self, s: str) -> Optional[TrieNode]:
        """Traverses the Trie following exact characters of s."""
        node = self.root
        for ch in s:
            node = node.children.get(ch)
            if node is None:
                return None
        return node

    def search(self, s: str) -> bool:
        """
        Exact match query.
        Time Complexity: O(m) where m = len(s)
        Space Complexity: O(1)
        """
        node = self._walk(s)
        return node is not None and node.is_end

    def starts_with(self, prefix: str) -> List[str]:
        """
        Prefix search query. Returns all stored strings that begin with prefix.
        Time Complexity: O(m + output)
        Space Complexity: O(output)
        """
        node = self._walk(prefix)
        if node is None:
            return []
        return sorted(self.traverse(node))

    def traverse(self, node: Optional[TrieNode] = None) -> Generator[str, None, None]:
        """
        Iterative Depth-First Search yielding all stored strings under a node.
        Time Complexity: O(N_sub) where N_sub is nodes in subtree
        Space Complexity: O(depth) stack memory
        """
        start = self.root if node is None else node
        stack = [start]
        while stack:
            curr = stack.pop()
            if curr.is_end and curr.path is not None:
                yield curr.path
            # Push children to stack
            for child in curr.children.values():
                stack.append(child)

    def delete(self, s: str) -> bool:
        """
        Removes a string from the Trie. Prunes empty childless branches
        and recomputes character bitmasks during recursion unwinding.
        Time Complexity: O(L * branching)
        Space Complexity: O(L) recursion stack
        """
        def _rec(node: TrieNode, i: int) -> bool:
            if i == len(s):
                if not node.is_end:
                    return False
                node.is_end = False
                node.path = None
                return True

            ch = s[i]
            child = node.children.get(ch)
            if child is None or not _rec(child, i + 1):
                return False

            # If child has no children and is not a terminal, prune it
            if not child.is_end and not child.children:
                del node.children[ch]
                self.total_nodes -= 1

            # Recompute bitmask from remaining children
            node.mask = 0
            for c, c_node in node.children.items():
                node.mask |= bit(c) | c_node.mask
            return True

        if not s:
            return False
        ok = _rec(self.root, 0)
        if ok:
            self.size -= 1
        return ok

    def candidates(self, q: str) -> Tuple[List[str], Dict[str, int]]:
        """
        Retrieves all stored strings that contain query q as a case-insensitive SUBSEQUENCE.
        
        Pruning Invariant:
        For remaining query suffix q[qi:], if (node.mask & req_mask) != req_mask,
        then the subtree beneath this node lacks at least one required character.
        The entire subtree is pruned in O(1) time without visiting any descendants.

        Returns:
            Tuple of (list of candidate paths, telemetry metrics dict)
        """
        q_low = q.lower()
        m = len(q_low)
        # rem[i] = bitmask of all characters in query suffix q_low[i:]
        rem = [mask_of(q_low[i:]) for i in range(m + 1)]

        out: List[str] = []
        nodes_visited = 0
        subtrees_pruned = 0

        def _dfs(node: TrieNode, qi: int) -> None:
            nonlocal nodes_visited, subtrees_pruned
            nodes_visited += 1

            # Whole query subsequence matched: take every stored string under this node
            if qi == m:
                out.extend(self.traverse(node))
                return

            # O(1) Bitmask Pruning Check
            if (node.mask & rem[qi]) != rem[qi]:
                subtrees_pruned += 1
                return

            # Greedy subsequence branch exploration
            for ch, child in node.children.items():
                matches = (ch.lower() == q_low[qi])
                _dfs(child, qi + 1 if matches else qi)

        _dfs(self.root, 0)

        telemetry = {
            "nodes_visited": nodes_visited,
            "subtrees_pruned": subtrees_pruned,
            "total_nodes": self.total_nodes,
            "candidates_found": len(out),
        }
        return out, telemetry


# =====================================================================
# 3. CUSTOM ARRAY-BASED BINARY MIN-HEAP (TOP-K SELECTOR)
# =====================================================================

class MinHeap:
    """
    Custom array-based Binary Min-Heap implemented from scratch (no heapq).
    Used as a bounded priority queue of size K to maintain the Top-K
    highest-scoring candidates in O(C log K) time and O(K) space.

    Min-Heap Property:
    For any node at index i, a[i] <= a[2*i + 1] and a[i] <= a[2*i + 2].
    The minimum element is always accessible at root a[0] in O(1).
    """

    def __init__(self) -> None:
        self.a: List[Any] = []

    def __len__(self) -> int:
        return len(self.a)

    def __bool__(self) -> bool:
        return bool(self.a)

    def peek(self) -> Any:
        """Returns the minimum element without removing it. O(1) time."""
        if not self.a:
            raise IndexError("peek from empty MinHeap")
        return self.a[0]

    def push(self, x: Any) -> None:
        """
        Inserts an item into the heap and restores heap invariant via sift-up.
        Time Complexity: O(log n)
        """
        a = self.a
        a.append(x)
        self._sift_up(len(a) - 1)

    def pop(self) -> Any:
        """
        Removes and returns the minimum element (root) via sift-down.
        Time Complexity: O(log n)
        """
        a = self.a
        if not a:
            raise IndexError("pop from empty MinHeap")
        top = a[0]
        last = a.pop()
        if a:
            a[0] = last
            self._sift_down(0)
        return top

    def _sift_up(self, i: int) -> None:
        """Restores min-heap property by bubbling element at i upwards."""
        a = self.a
        while i > 0:
            parent = (i - 1) // 2
            if a[i] < a[parent]:
                a[i], a[parent] = a[parent], a[i]
                i = parent
            else:
                break

    def _sift_down(self, i: int) -> None:
        """Restores min-heap property by sinking element at i downwards."""
        a = self.a
        n = len(a)
        while True:
            left = 2 * i + 1
            right = 2 * i + 2
            smallest = i

            if left < n and a[left] < a[smallest]:
                smallest = left
            if right < n and a[right] < a[smallest]:
                smallest = right

            if smallest != i:
                a[i], a[smallest] = a[smallest], a[i]
                i = smallest
            else:
                break

    @classmethod
    def heapify(cls, items: Iterable[Any]) -> "MinHeap":
        """
        Builds a MinHeap from an arbitrary iterable in-place.
        Time Complexity: O(n) bottom-up construction
        """
        h = cls()
        h.a = list(items)
        n = len(h.a)
        # Start from the lowest non-leaf node down to root
        for start in range(n // 2 - 1, -1, -1):
            h._sift_down(start)
        return h
