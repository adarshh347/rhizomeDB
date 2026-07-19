import * as Tabs from "@radix-ui/react-tabs";

import type { BookPayload, Paragraph, Annotation } from "../api/types";
import type { ConnectionsState } from "./useConnections";
import { ConnectionsPanel } from "./ConnectionsPanel";
import { NotesRail } from "./NotesRail";
import { SpinePanel } from "./SpinePanel";

export type RailMode = "notes" | "spine" | "connections";

export function ReaderRail({
  mode,
  onMode,
  book,
  items,
  activeChunk,
  connectionChunk,
  connectionState,
  onJump,
  onDelete,
  onPin,
  onDismiss,
  onOpenChunk,
  onConnect,
  onCloseConnections,
  activeAnnotation,
}: {
  mode: RailMode;
  onMode: (mode: RailMode) => void;
  book: BookPayload;
  items: Annotation[];
  activeChunk: string | null;
  connectionChunk: string | null;
  connectionState: ConnectionsState;
  onJump: (annotation: Annotation) => void;
  onDelete: (id: string) => void;
  onPin: (id: string, chunkId: string) => void;
  onDismiss: (id: string) => void;
  onOpenChunk: (chunk: Paragraph) => void;
  onConnect: (chunkId: string) => void;
  onCloseConnections: () => void;
  activeAnnotation?: string | null;
}) {
  return (
    <Tabs.Root className="rail" value={mode} onValueChange={(value) => onMode(value as RailMode)}>
      <Tabs.List className="rail-tabs" aria-label="Reader context">
        <Tabs.Trigger className="rail-tab" value="notes">Notes</Tabs.Trigger>
        <Tabs.Trigger className="rail-tab" value="spine">Spine</Tabs.Trigger>
        <Tabs.Trigger className="rail-tab" value="connections" disabled={!connectionChunk}>
          Connections
        </Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content className="rail-tab-panel" value="notes" forceMount>
        <NotesRail
          items={items}
          onJump={onJump}
          onDelete={onDelete}
          onPin={onPin}
          onDismiss={onDismiss}
          onConnect={onConnect}
          activeId={activeAnnotation}
        />
      </Tabs.Content>
      <Tabs.Content className="rail-tab-panel" value="spine" forceMount>
        <SpinePanel
          book={book}
          activeId={activeChunk}
          active={mode === "spine"}
          onOpen={onOpenChunk}
          onConnect={(chunk) => onConnect(chunk.id)}
        />
      </Tabs.Content>
      <Tabs.Content className="rail-tab-panel" value="connections" forceMount>
        {connectionChunk && (
          <ConnectionsPanel
            chunkId={connectionChunk}
            fromLabel={book.title}
            state={connectionState}
            onClose={onCloseConnections}
          />
        )}
      </Tabs.Content>
    </Tabs.Root>
  );
}
