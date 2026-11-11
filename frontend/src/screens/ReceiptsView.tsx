import { useState } from "react";
import type { Receipt } from "../types";
import { IconBarcode, IconCheck, IconCopy } from "../components/Icons";

interface ReceiptsViewProps {
  receipts: Receipt[];
  onMatchItem: (receiptId: string, itemId: string, productName: string) => void;
}

const FORWARD_ADDRESS = "receipts@pantry.local";

export default function ReceiptsView({ receipts, onMatchItem }: ReceiptsViewProps) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const copyAddress = async () => {
    try {
      await navigator.clipboard.writeText(FORWARD_ADDRESS);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div>
      <div className="card forward-card">
        <div className="info">
          <div className="item-name">Forward receipts by mail</div>
          <div className="forward-address">{FORWARD_ADDRESS}</div>
        </div>
        <button className="icon-btn" onClick={copyAddress} aria-label="Copy address">
          {copied ? <IconCheck size={18} /> : <IconCopy size={18} />}
        </button>
      </div>

      <h2 className="section-title">Recent</h2>

      {receipts.map((receipt) => {
        const open = openId === receipt.id;
        const pending = receipt.items.filter((i) => i.status === "pending");
        return (
          <div key={receipt.id} className="card receipt-card" style={{ marginBottom: 10 }}>
            <button
              className="receipt-head"
              onClick={() => (receipt.status === "review" ? setOpenId(open ? null : receipt.id) : undefined)}
            >
              <div className="info">
                <div className="store">{receipt.store}</div>
                <div className="meta">
                  {receipt.date} · {receipt.items.length} items
                </div>
              </div>
              <span className="receipt-head total">{receipt.total.toFixed(2)} €</span>
              <span className={`status-chip ${receipt.status}`}>{receipt.status}</span>
            </button>

            {open && receipt.status === "review" && (
              <div className="review-items">
                {pending.map((item) => (
                  <div key={item.id} className="review-item">
                    <div className="raw">
                      {item.rawName} <span className="qty">×{item.quantity}</span>
                    </div>
                    {item.suggestion ? (
                      <span className="suggestion">
                        {item.suggestion}
                        <button
                          aria-label={`Accept ${item.suggestion}`}
                          onClick={() => onMatchItem(receipt.id, item.id, item.suggestion!)}
                        >
                          <IconCheck size={13} />
                        </button>
                      </span>
                    ) : (
                      <button className="btn btn-ghost" style={{ padding: "6px 12px", fontSize: 12.5 }}>
                        <IconBarcode size={14} />
                        Match
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
