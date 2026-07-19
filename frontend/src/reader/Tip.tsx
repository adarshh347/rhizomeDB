import type { ReactNode } from "react";
import * as RTooltip from "@radix-ui/react-tooltip";

// One tooltip, borrowed from Radix (positioning, keyboard/focus a11y, escape) —
// skinned in ink/paper via .rz-tooltip. Replaces scattered `title` attributes so
// hints are consistent and reachable. A single <RTooltip.Provider> lives at the
// app root (App.tsx). `label` is the accessible hint; wrap any focusable child.
export function Tip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <RTooltip.Root>
      <RTooltip.Trigger asChild>{children}</RTooltip.Trigger>
      <RTooltip.Portal>
        <RTooltip.Content className="rz-tooltip" sideOffset={6} collisionPadding={8}>
          {label}
          <RTooltip.Arrow className="rz-tooltip-arrow" width={10} height={5} />
        </RTooltip.Content>
      </RTooltip.Portal>
    </RTooltip.Root>
  );
}
