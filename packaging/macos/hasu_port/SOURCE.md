# HaSu desktop frontend port

Source snapshot: HaSu checkout `f8bcc5e5a6544270b6554222b2b50b02e984e210`.

| Upstream source | Adaptation in `desktop.js` |
| --- | --- |
| `apps/desktop/src/app/settings/settings-search.ts` and `apps/desktop/src/lib/text.ts` | Entry scoring, stable result ordering and text normalization. Hetu builds entries from its settings controls. |
| `apps/desktop/src/lib/middle-click.ts` and `apps/desktop/src/components/ui/pane-tab.tsx` | Command-click, middle press/release and Delete to close. DOM listeners instead of React event props. |
| `apps/desktop/src/components/pane-shell/tree/renderer/layout-picker.tsx` | Recursive split thumbnails and dashed resting panes. Hetu supplies its own layouts and pane names. |

`LICENSE` and `NOTICE` are preserved from the same source snapshot. The macOS packager ships both notices with the port. The desktop port is adapted upstream software and is outside the original cleanroom record.
