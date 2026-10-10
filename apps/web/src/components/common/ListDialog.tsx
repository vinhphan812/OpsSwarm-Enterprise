import { Modal, ModalBody, ModalContent, ModalHeader } from "@heroui/react";
import type { ReactNode } from "react";

/** Width and height of a list dialog; the table scrolls inside it. Smaller screens get most of the viewport. */
const DIALOG_SIZE = "w-[min(768px,calc(100vw-32px))] max-w-none h-[min(600px,85dvh)]";

type ListDialogProps = {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  /** Chips beside the title, such as "Sample data". */
  badges?: ReactNode;
  /** Totals above the toolbar. */
  summary?: ReactNode;
  /** Filters and search, on one row. */
  toolbar: ReactNode;
  /** Shown in place of the table when no row matches. */
  empty: string;
  isEmpty: boolean;
  /** The table. It scrolls on its own; everything above it stays put. */
  children: ReactNode;
};

/**
 * A dialog of one fixed size holding a filtered table: title, optional totals, a toolbar,
 * then the table, which alone scrolls. The size does not change as filters change the
 * row count.
 */
export function ListDialog({ isOpen, onClose, title, subtitle, badges, summary, toolbar, empty, isEmpty, children }: ListDialogProps) {
  return (
    <Modal isOpen={isOpen} onClose={onClose} size="3xl" scrollBehavior="inside" backdrop="blur" classNames={{ base: DIALOG_SIZE }}>
      <ModalContent>
        <ModalHeader className="flex flex-col gap-1">
          <span className="flex flex-wrap items-center gap-2">
            {title}
            {badges}
          </span>
          {subtitle ? <span className="text-xs font-normal text-ink-muted">{subtitle}</span> : null}
        </ModalHeader>
        <ModalBody className="min-h-0 gap-3 overflow-hidden pb-6">
          {summary}
          <div className="dialog-toolbar">{toolbar}</div>
          {isEmpty ? (
            <p className="flex flex-1 items-center justify-center text-sm text-ink-muted">{empty}</p>
          ) : (
            <div className="data-table-scroll">{children}</div>
          )}
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}
