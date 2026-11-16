import { useState } from "react";
import type { Item } from "../types";
import { IconCheck, IconCopy, IconNfc } from "./Icons";

const STORAGE_KEY = "openpantry.nfc-links";

function readEnabledIds(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]"));
  } catch {
    return new Set();
  }
}

function writeEnabledIds(ids: Set<string>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...ids]));
}

/** "NFC Link" section of the item detail. Disabled by default: enabling it
 *  creates the plain-GET tag links for this item, which NFC tags, QR
 *  stickers, the Shortcuts app and a browser can all open directly. */
export default function NfcLinkBlock({ item }: { item: Item }) {
  const [enabled, setEnabled] = useState(() => readEnabledIds().has(item.id));
  const [copied, setCopied] = useState<string | null>(null);

  const origin = window.location.origin;
  const links = [
    { key: "empty", label: "Container empty", url: `${origin}/tag/${item.id}/empty` },
    { key: "buy", label: `Buy (${item.packageSize} ${item.unit})`, url: `${origin}/tag/${item.id}/buy` },
  ];

  const enable = () => {
    const ids = readEnabledIds();
    ids.add(item.id);
    writeEnabledIds(ids);
    setEnabled(true);
  };

  const disable = () => {
    const ids = readEnabledIds();
    ids.delete(item.id);
    writeEnabledIds(ids);
    setEnabled(false);
    setCopied(null);
  };

  const copy = async (key: string, url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(key);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      setCopied(null);
    }
  };

  if (!enabled) {
    return (
      <div className="nfc-block">
        <button className="btn btn-ghost btn-block" onClick={enable}>
          <IconNfc size={16} /> NFC Link
        </button>
        <p className="sheet-sub">Enable to create the tag links for this container.</p>
      </div>
    );
  }

  return (
    <div className="nfc-block">
      <div className="nfc-head">
        <span className="nfc-label">
          <IconNfc size={16} /> NFC Link
        </span>
        <button className="btn btn-ghost btn-sm" onClick={disable}>
          Disable
        </button>
      </div>
      {links.map((link) => (
        <div key={link.key} className="tag-link">
          <div className="info">
            <div className="tag-name">{link.label}</div>
            <div className="tag-url">{link.url}</div>
          </div>
          <button
            className="icon-btn"
            aria-label={`Copy ${link.label} link`}
            onClick={() => copy(link.key, link.url)}
          >
            {copied === link.key ? <IconCheck size={16} /> : <IconCopy size={16} />}
          </button>
        </div>
      ))}
      <p className="sheet-sub">
        Write a link onto an NFC tag or QR sticker. Opening it marks the container
        empty or adds one package to the shopping list.
      </p>
    </div>
  );
}
