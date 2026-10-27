# knot

A local-first ticket planner with a visual task tree and a calendar-based Gantt chart. The interface is in Japanese. The application is a single HTML file and makes no external network requests.

## Start

1. Download `index.html` and open it in desktop Microsoft Edge or Chrome.
2. Use the folder menu in the top-right corner to open a workspace folder.
3. For an empty folder, confirm creation from the current sample tickets. Existing workspace folders load their saved tickets.

No server, build step or installation is needed to run the application. The initial tickets and images are fictional samples.

## Features

- Arrange tasks as parent/child trees with curved hierarchy links and vertical workflow arrows.
- Drag a card and its descendants together; select multiple cards with Shift-drag; group cards and edit selected fields in bulk.
- Drop one card onto another to choose a child, successor or parallel relationship. Cyclic relationships are rejected.
- Fold branches without deleting their descendants.
- Focus on ready tasks, deadlines within seven days or overdue tasks while keeping other cards visible and dimmed.
- Add memo cards with inline content and nonblocking reference links, or mark tasks as not doing.
- Switch the Gantt chart between daily dates, Monday-based weeks and calendar months.
- Undo an entire bulk edit or relationship change in one step. Reparenting also updates the project for the moved subtree.
- Attach files and show uncropped image previews with a capped height.

The operation guide in the app lists shortcuts and detailed behavior.

## Workspace files

```text
your-workspace/
  workspace.json       # Projects, ticket attributes, links, groups and positions
  tickets/<id>.md      # Ticket content
  attachments/         # Attached files
```

The selected folder is the primary store. Browser storage holds a recovery copy and acts as a draft before a folder is selected. Pending recovery data is scoped to each workspace.

Saving detects external file changes and stops instead of silently overwriting them. Reopen the workspace after editing its files in another application. Writes are sequential, with the JSON index written last; saving is not a multi-file filesystem transaction.

Removing a card or attachment unregisters it from the JSON index; existing files remain on disk for recovery. Back up the complete workspace folder. Undo history lasts for the current page session and resets on reload.

## Scope and limits

- Folder access targets desktop Chrome and Edge. Browser filesystem permissions are required for the selected folder.
- This is a standalone prototype. It has no collaboration server, account system, cloud synchronization or SHUKI integration.
- Attachments added through the app are limited to 3 MB per file. Workspace reads are limited to 16 MB per file and 128 MB total.
- Keep personal workspace data outside the source repository. The included ignore rules exclude the app's standard workspace paths, browser artifacts and local development notes.

## Development checks

The browser checks use Python, Playwright and installed Microsoft Edge. The native folder-picker check additionally requires Windows and opens an isolated test browser.

For a local Windows development environment with the Python launcher installed:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe -m unittest discover -v
```

Run the native Windows picker check separately:

```powershell
.\.venv\Scripts\python.exe test_native_workspace.py
```

The automated suite currently has 71 browser checks. Tests use fictional data and isolated temporary workspaces. The loopback servers used by filesystem tests are test fixtures; the app itself needs no server.

## Issues

Use the repository's Issues tab for bug reports and feature requests. For bugs, include the browser, expected behavior, actual behavior and reproduction steps. Share a minimal fictional example instead of a personal workspace or credentials.

## License

A license has not been selected yet.
