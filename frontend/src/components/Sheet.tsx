import type { ReactNode } from "react";

interface SheetProps {
  onClose: () => void;
  children: ReactNode;
}

export default function Sheet({ onClose, children }: SheetProps) {
  return (
    <>
      <div className="sheet-backdrop" onClick={onClose} />
      <div className="sheet" role="dialog">
        <div className="sheet-handle" />
        {children}
      </div>
    </>
  );
}
