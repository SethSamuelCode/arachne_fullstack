# Chat Files + Pinning Sidebar Design

## Summary

Integrate file management and context pinning into a unified, resizable sidebar on the `/chat` page. The sidebar coexists with the existing Sheet-based file browser and pin buttons in the action bar.

## Layout

```
+----------+-------------------------+------------------+
| Convo    |                         |                  |
| Sidebar  |     Chat Area           |  Files+Pin       |
| (80px)   |     (flex: 1)           |  Sidebar         |
|          |                         |  (resizable)     |
|          |                         |                  |
|          |  +------------------+   |                  |
|          |  | Input + Actions  |   |                  |
|          |  +------------------+   |                  |
+----------+-------------------------+------------------+
```

- **Toggle**: Icon button in the chat action bar (`PanelRightOpen`/`PanelRightClose` from Lucide). Toggles sidebar visibility. Chat area takes full width when sidebar is hidden.
- **Resize**: Draggable handle between chat and sidebar panels using `react-resizable-panels`.
- **Default size**: 40% of available width.
- **Constraints**: Min chat panel 40%, min sidebar panel 25%.
- **Persistence**: `react-resizable-panels` `useDefaultLayout` hook with a stable `id` handles resize persistence. A Zustand store (`files-sidebar-store.ts`) tracks `isOpen` only, persisted to localStorage.
- **Mobile**: Sidebar hidden below `md` breakpoint. Existing Sheet-based file browser and pin buttons remain the mobile interface.
- **Toggle indicator**: The toggle button shows a dot badge when pinned files are stale, even when sidebar is closed.

## Sidebar Internal Layout

Single unified view (no tabs). Top to bottom:

### Pinned Content Summary (collapsible)

Shown when the active conversation has pinned content.

- Pin icon, file count, token count, "pinned 5m ago"
- Staleness indicator: amber warning + changed file count if files modified since last pin
- Action buttons: "Repin All", "Clear All"
- Collapses to a single-line summary bar

### File Tree (main area)

- Same tree structure as existing files sidebar: folders, files, drag-and-drop upload zone at top
- **Pinned file indicators**: Small pin icon overlay on file icon + subtle background tint (`bg-primary/5`)
- **Clicking filename**: Toggles file selection (checkbox)
- **Checkboxes**: Visible on each file for multi-select. Checkboxes use `pointer-events-none` and are purely visual — the parent row's `onClick` drives selection, avoiding double-toggle bugs with the custom Checkbox component.
- **Folder checkboxes**: Each folder has a checkbox that selects/deselects all files within it (recursively). Shows checked when all files are selected, partial opacity when some are selected.
- **Folder hover actions**: Rename, delete
- **File hover actions**: Eye (preview), download, rename, delete
- No quick-pin action on hover -- all pinning goes through explicit selection flow

### Floating Actions (bottom)

Two sections:

**Pin action bar** (visible when files are selected):
- Shows selected file count badge
- "Pin Selected" button to start pinning
- Clicking starts the pin flow; progress displays inline in the pinned summary section

**Upload actions** (always visible):
- Upload file, upload folder, create folder buttons

## File Preview

- **Trigger**: Eye icon button on file hover actions
- **Display**: Radix Popover or Dialog anchored near the clicked item
- **Content**: File name, metadata (size, modified date), content preview (image/text/code/binary info)
- **Footer actions**: Download, Close
- **Constraints**: Max ~400px wide, ~500px tall
- **Behavior**: Click outside or Escape to close. One preview open at a time.

## Pinning Flow

1. User selects files via checkboxes (clicking filenames)
2. "Pin Selected" bar appears at bottom with count
3. User clicks "Pin Selected"
4. If no conversation selected, a new conversation is created (existing behavior)
5. Progress displays inline in the pinned summary section (progress bar + phase text)
6. Affected files show subtle pulsing animation during pin
7. On completion, pinned summary updates with new stats

Repin from summary section uses stored file paths from pinned content metadata.

## Conversation Switching

- Pinned summary refreshes to show the new conversation's pinned content
- File tree stays the same (files are global, not per-conversation)

## Component Architecture

### New Components

| Component | Description |
|-----------|-------------|
| `ChatFilesSidebar` | Top-level sidebar wrapper. Contains pinned summary, file tree, floating actions. |
| `PinnedContentSummary` | Collapsible bar with pin stats, staleness, repin/clear actions. Reuses logic from `PinnedContentIndicator` and `PinnedFilesListDialog`. |
| `FileTreeItem` | Tree row with pin overlay, hover actions (eye, download, rename, delete), checkbox. |

### Modified Components

| Component | Change |
|-----------|--------|
| `ChatContainer` | Wrap in `PanelGroup` with two `Panel`s (chat + sidebar). Add toggle button to action bar. |

### New Store

`files-sidebar-store.ts`:
```typescript
{
  isOpen: boolean  // sidebar visibility, persisted to localStorage
}
```

### Reused Hooks/Stores

- `useFilesStore` -- file CRUD, selection, expanded folders
- `usePinnedContentStore` -- pin state, progress, staleness
- `usePinFiles` -- pin/repin/clear operations with SSE streaming

### No Backend Changes

All existing API routes for files and pinning are sufficient.

## Behavior Details

- Opening sidebar triggers file list refresh
- Closing sidebar does not cancel in-progress pinning -- progress continues in background
- Sidebar toggle button shows dot badge when pinned content is stale (even when closed)
- No keyboard shortcuts initially

## Coexistence with Existing UI

- `PinFilesButton` has been **removed** from the action bar — pinning is done exclusively through the sidebar's file selection + "Pin Selected" flow.
- `FileBrowser` (Sheet-based) is **hidden** when the sidebar is open (redundant), but remains visible when the sidebar is closed as a fallback.
- `PinnedContentIndicator` remains in the action bar status area.

## react-resizable-panels API

The library (v4.x) exports `Group`, `Panel`, and `Separator` (not `PanelGroup`/`PanelResizeHandle`). Layout persistence uses the `useDefaultLayout` hook with an `id` parameter, not an `autoSaveId` prop. The `Group` component uses `orientation` instead of `direction`.
