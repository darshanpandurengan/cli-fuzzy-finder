# CLI Fuzzy Finder: Real-Time Subsequence Search Engine

An in-memory fuzzy file and path search engine built in **pure Python**. It combines a **Prefix Trie augmented with 64-bit subtree character bitmasks** for candidate pruning and a **custom array-based Binary Min-Heap** for efficient Top-K result selection.

The project provides a dark-themed Tkinter desktop interface and a command-line mode. It requires no database, AI service, or third-party Python packages.

## 1. Problem Statement

Developer tools such as VS Code's `Ctrl+P`, Sublime Text, and `fzf` help users locate files quickly by typing partial or non-contiguous character sequences. For example, a query such as `smp` may match `src/main.py`.

A straightforward scan checks every path for every query. As the indexed collection grows, repeated scans can become expensive. A standard Trie shares common prefixes but does not, by itself, efficiently prune every branch for subsequence queries.

This project augments Trie nodes with character-presence bitmasks to reject branches that cannot contain the remaining query characters. It ranks matches using a two-pass alignment heuristic and retains only the best K results with a custom Min-Heap.

## 2. Key Features

- **Fuzzy subsequence search:** Find paths even when query characters are not adjacent.
- **Trie indexing:** Store shared path prefixes in a hierarchical structure.
- **64-bit character masks:** Quickly prune branches that cannot satisfy a query.
- **Top-K ranking:** Use a custom array-based Min-Heap instead of sorting every candidate.
- **Relevance scoring:** Reward exact, consecutive, filename, word-boundary, and camelCase matches.
- **Live Tkinter GUI:** Search as you type and highlight matched characters.
- **Keyboard navigation:** Use arrow keys, Enter, Escape, and supported shortcuts.
- **Local folder indexing:** Scan a directory and search its paths.
- **CLI mode:** Query the demo dataset, a path file, or piped input.
- **Telemetry:** Inspect search-related algorithm information in the GUI.
- **Automated tests:** Verify data structures, matching, scoring, and edge cases.

## 3. Data Structures and Algorithms

### Prefix Trie with subtree bitmasks

Each Trie node stores its children, whether a path ends at the node, the associated path, and a 64-bit character-presence mask. During candidate traversal, the query's remaining character mask is compared with the subtree mask. If required characters are missing, that subtree can be pruned.

The mask is a compact filter, not a proof that a subsequence exists. Because multiple characters can map to the same bit, collisions can cause extra traversal, but they must not cause valid candidates to be rejected when the mask is maintained correctly.

### Custom array-based Binary Min-Heap

The Min-Heap keeps the best K candidates during ranking. When its size exceeds K, the minimum-ranked entry is removed. This avoids sorting all C candidates when only a small number of results is required.

### Two-pass alignment and scoring

The scorer first scans forward to find a match, then scans backward to identify a tighter alignment window. The ranking heuristic can reward word boundaries, camelCase transitions, consecutive characters, and filename matches, while penalizing gaps and long paths.

## 4. Complexity Analysis

Let:

- `n` = number of indexed paths
- `L` = average path length
- `m` = query length
- `N` = number of Trie nodes
- `C` = number of matching candidates
- `K` = maximum number of results returned

| Operation | Complexity |
|---|---:|
| Insert a path | `O(L)` |
| Exact Trie lookup | `O(m)` |
| Prefix lookup | `O(m + output)` |
| Fuzzy subsequence candidate search | Worst case `O(N)`; often reduced by pruning |
| Top-K selection | `O(C log K)` |
| Trie storage | `O(N)` nodes, with child-map overhead |

Actual search performance depends on the dataset, query, branching factor, and pruning effectiveness. Bitmask pruning improves typical cases but does not remove the worst-case linear traversal of the Trie.

## 5. Repository Structure

The project is designed to stay within a maximum of five files:

```text
cli-fuzzy-finder/
├── data_structures.py   # Trie, bitmask helpers, and custom Min-Heap
├── fuzzy_search.py      # Candidate search, alignment, scoring, and engine
├── main.py              # Tkinter GUI and CLI entry point
├── test_fuzzy_search.py # Automated unit tests
└── README.md            # Project documentation
```

## 6. Requirements

- Python 3.8 or later
- Python standard library
- Tkinter for the desktop GUI (availability depends on your Python installation)

No `pip install` step is required for the standard-library implementation.

## 7. Run the Project

Run these commands from the project directory.

### Desktop GUI

```bash
python main.py
```

Type a query such as `app`, `src`, `cfg`, or `test`. Use the GUI's folder-selection control to index a real directory.

### CLI: Search the built-in dataset

```bash
python main.py app -k 4
```

### CLI: Search paths from a text file

```bash
python main.py app -f my_paths.txt -k 5
```

### CLI: Search piped input (PowerShell example)

```powershell
Get-ChildItem -Recurse -Name | python main.py main -k 5
```

Check `python main.py --help` if the implementation exposes argparse help, and adjust command flags to match the final `main.py` implementation.

## 8. GUI Controls

The intended controls are:

| Key / Action | Result |
|---|---|
| `↑` / `↓` | Move through results |
| `Enter` | Copy the selected path |
| `Ctrl+E` | Show the selected file in the file manager |
| `Ctrl+Enter` or double-click | Open the selected file |
| `Ctrl+T` | Show or hide algorithmic telemetry |
| `Ctrl+O` | Scan a local folder |
| `Esc` | Clear the query |
| Right-click | Open path actions, where implemented |

Opening or revealing a path requires a real indexed file. Demo dataset paths may be illustrative and may not exist on disk. Exact shortcut behavior depends on the final GUI implementation.

## 9. Run Automated Tests

```bash
python -m unittest test_fuzzy_search.py -v
```

The test suite should cover areas such as:

- Bitmask creation and pruning behavior
- Trie insertion, exact search, prefix search, and deletion
- Min-Heap push, pop, peek, and heap invariants
- Subsequence matching and case-insensitive search
- Alignment and relevance scoring
- Top-K result limits
- Empty queries, no-match queries, duplicate paths, and empty datasets

Only tests actually present in `test_fuzzy_search.py` will run; update this list to reflect the implemented suite.

