import type { MouseEventHandler, ReactNode } from "react";

interface SheetProps {
  onClose: () => void;
  children: ReactNode;
  /** Level-2 sheet rendered on top of an already open sheet. */
  nested?: boolean;
  /** Opens the next level when set: tapping the top of this sheet raises it. */
  onHeaderClick?: () => void;
}

export default function Sheet({ onClose, children, nested, onHeaderClick }: SheetProps) {
  const handleClick: MouseEventHandler | undefined = onHeaderClick;
  return (
    <>
      <div className={nested ? "sheet-backdrop nested" : "sheet-backdrop"} onClick={onClose} />
      <div className={nested ? "sheet nested" : "sheet"} role="dialog">
        {onHeaderClick ? (
          <button className="sheet-handle clickable" onClick={handleClick} aria-label="Adjust alarms" />
        ) : (
          <div className="sheet-handle" />
        )}
        {children}
      </div>
    </>
  );
}
