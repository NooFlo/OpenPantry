import { useCallback, useEffect, useMemo, useState } from "react";
import type { ControlCodeInfo, CustomLabelInfo, Item, ItemCreatePayload, ItemPatch, ModelList, Receipt, ScanLogEntry, Settings, SettingsPatch } from "../types";
import { CANONICAL_CATEGORIES } from "../types";
import {
  deleteItemCustomLabel,
  fetchCustomLabelInfos,
  saveItemCustomLabel,
} from "../api";
import { IconBarcode, IconClock, IconGear, IconInventory, IconMinus, IconPlus, IconReceipt, IconSearch, IconTag } from "../components/Icons";
import Sheet from "../components/Sheet";
import AlarmSheet, { ItemSettings } from "../components/AlarmSheet";
import ThemeToggle from "../components/ThemeToggle";
import ModelSettingsSheet from "../components/ModelSettingsSheet";
import BarcodesView from "../components/BarcodesView";
import LabelEditor, { type LabelEditorTarget } from "../components/LabelEditor";
import AddItemSheet from "../components/AddItemSheet";
import EditableName from "../components/EditableName";
import ScanLogSheet from "../components/ScanLogSheet";
import NfcLinkBlock from "../components/NfcLinkBlock";
import ReceiptsView from "./ReceiptsView";
import { useMediaQuery } from "../lib/useMediaQuery";
import { formatStock, isBinary, isLow, isInStock, stepAmount } from "../lib/tracking";

type View = "items" | "receipts" | "barcodes";

/** Sub line of an item's detail header: the primary EAN, or a count when the
 *  item carries several product barcodes. */
function eanLine(item: Item) {
  if (item.barcodes && item.barcodes.length > 1)
    return ` · ${item.barcodes.length} EANs`;
  return item.barcode ? ` · ${item.barcode}` : "";
}

interface InventoryScreenProps {
  items: Item[];
  receipts: Receipt[];
  onConsume: (id: string, amount: number) => void;
  onRestock: (id: string, amount: number) => void;
  onDelete: (id: string) => void;
  onMatchItem: (receiptId: string, itemId: string, productName: string) => void;
  onUpdateItem: (id: string, patch: ItemPatch) => void;
  /** Rename an item; rejects (e.g. 409 taken) with the reason. */
  onRenameItem: (id: string, name: string) => Promise<void>;
  onAddItem: (payload: ItemCreatePayload) => Promise<void>;
  onAddItemBarcode: (id: string, barcode: string) => void;
  onRemoveItemBarcode: (id: string, barcode: string) => void;
  settings: Settings;
  models: ModelList;
  onSaveSettings: (patch: SettingsPatch) => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  scanLog: ScanLogEntry[];
  onOpenReview: () => void;
}

export default function InventoryScreen({ items, receipts, onConsume, onRestock, onDelete, onMatchItem, onUpdateItem, onRenameItem, onAddItem, onAddItemBarcode, onRemoveItemBarcode, settings, models, onSaveSettings, theme, onToggleTheme, scanLog, onOpenReview }: InventoryScreenProps) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [selected, setSelected] = useState<Item | null>(null);
  const [confirmDeleteFor, setConfirmDeleteFor] = useState<string | null>(null);
  const [alarmsOpen, setAlarmsOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [addItemOpen, setAddItemOpen] = useState(false);
  const [scanLogOpen, setScanLogOpen] = useState(false);
  const [view, setView] = useState<View>("items");
  const [customLabels, setCustomLabels] = useState<CustomLabelInfo[]>([]);
  const [labelEditorFor, setLabelEditorFor] = useState<LabelEditorTarget | null>(null);
  const twoPane = useMediaQuery("(min-width: 1180px)");

  const refreshCustomLabels = useCallback(() => {
    return fetchCustomLabelInfos()
      .then(setCustomLabels)
      .catch(() => { /* backend briefly away */ });
  }, []);

  useEffect(() => {
    refreshCustomLabels();
  }, [refreshCustomLabels]);

  /** The "Create custom label" checkbox: checking it links a default design
   *  to exactly this item; unchecking deletes it (user decision). */
  const toggleCustomLabel = async (item: Item, enabled: boolean) => {
    try {
      if (enabled) {
        await saveItemCustomLabel(item.id, { tape: 24, widthMm: 50 });
      } else {
        await deleteItemCustomLabel(item.id);
      }
      await refreshCustomLabels();
    } catch {
      /* backend briefly away — checkbox state stays stale until next refresh */
    }
  };

  const hasCustomLabel = (itemId: string): boolean =>
    customLabels.some((entry) => entry.itemId === itemId);

  const editItemLabel = (item: Item) => {
    setAlarmsOpen(false);
    setLabelEditorFor({ kind: "item", item });
  };

  const editControlLabel = (control: ControlCodeInfo) => {
    setLabelEditorFor({ kind: "control", control });
  };

  const closeLabelEditor = () => setLabelEditorFor(null);

  const labelEditorSaved = () => {
    refreshCustomLabels();
  };

  const categories = useMemo(() => [...new Set(items.map((i) => i.category))], [items]);
  // canonical order first, then customs alphabetically — picker suggestions
  const categorySuggestions = useMemo(
    () => [
      ...CANONICAL_CATEGORIES.filter((c) => categories.includes(c)),
      ...categories.filter((c) => !CANONICAL_CATEGORIES.includes(c)).sort(),
    ],
    [categories]
  );

  const filtered = items
    .filter((i) => (category === null ? true : i.category === category))
    .filter((i) => i.name.toLowerCase().includes(query.trim().toLowerCase()))
    .sort((a, b) => a.name.localeCompare(b.name));

  const selectedLive = selected ? items.find((i) => i.id === selected.id) ?? null : null;

  const itemsPane = (
    <>
      <div className="search">
        <IconSearch size={18} />
        <input
          type="text"
          placeholder="Search items"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      <div className="chip-row">
        <button className={category === null ? "chip active" : "chip"} onClick={() => setCategory(null)}>
          All
        </button>
        {categories.map((c) => (
          <button key={c} className={category === c ? "chip active" : "chip"} onClick={() => setCategory(c)}>
            {c}
          </button>
        ))}
      </div>

      <div>
        {filtered.map((item) => (
          <div key={item.id} className="list-row-wrap">
            <button
              className={selectedLive?.id === item.id ? "list-row selected" : "list-row"}
              onClick={() => setSelected(item)}
            >
              <div className="info">
                <div className="item-name">{item.name}</div>
                <div className="item-sub">{item.category}</div>
              </div>
              <span className={isLow(item) ? "qty low" : "qty"}>
                {formatStock(item)}
              </span>
            </button>
            {!isBinary(item) && (
              <div className="row-stepper">
                <button
                  aria-label={`Use one ${item.name}`}
                  disabled={item.quantity <= 0}
                  onClick={() => onConsume(item.id, stepAmount(item))}
                >
                  <IconMinus size={16} />
                </button>
                <button
                  aria-label={`Add one ${item.name}`}
                  onClick={() => onRestock(item.id, stepAmount(item))}
                >
                  <IconPlus size={16} />
                </button>
              </div>
            )}
          </div>
        ))}
        {filtered.length === 0 && <div className="empty-state">No items match.</div>}
      </div>
    </>
  );

  const detail = selectedLive ? (
    <>
      {twoPane ? (
        <div>
          <h2 className="sheet-title">
            <EditableName
              name={selectedLive.name}
              onRename={(name) => onRenameItem(selectedLive.id, name)}
            />
          </h2>
          <p className="sheet-sub">
            {selectedLive.category}
            {eanLine(selectedLive)}
          </p>
        </div>
      ) : (
        <button className="sheet-header-btn" onClick={() => setAlarmsOpen(true)}>
          <div>
            <h2 className="sheet-title">{selectedLive.name}</h2>
            <p className="sheet-sub">
              {selectedLive.category}
              {eanLine(selectedLive)}
            </p>
          </div>
          {alarmsOpen ? <span className="chevron up" aria-hidden /> : <span className="chevron" aria-hidden />}
        </button>
      )}

      {isBinary(selectedLive) ? (
        <div className="qty-stepper">
          <span className="value">{formatStock(selectedLive)}</span>
          <span style={{ width: 40 }} />
        </div>
      ) : (
        <div className="qty-stepper">
          <button onClick={() => onConsume(selectedLive.id, stepAmount(selectedLive))} aria-label="Use one">
            <IconMinus size={18} />
          </button>
          <span className="value">
            {formatStock(selectedLive)}
          </span>
          <button onClick={() => onRestock(selectedLive.id, stepAmount(selectedLive))} aria-label="Add one">
            <IconPlus size={18} />
          </button>
        </div>
      )}

      <div className="sheet-actions">
        <button className="btn btn-ghost" onClick={() => setSelected(null)}>
          Close
        </button>
        {hasCustomLabel(selectedLive.id) && (
          <button className="btn btn-ghost" onClick={() => editItemLabel(selectedLive)}>
            <IconTag size={16} />
            Edit label
          </button>
        )}
        {isBinary(selectedLive) ? (
          isInStock(selectedLive) ? (
            <button
              className="btn btn-primary"
              onClick={() => {
                onConsume(selectedLive.id, selectedLive.packageSize);
                setSelected(null);
              }}
            >
              <IconBarcode size={16} />
              Mark as used up
            </button>
          ) : (
            <button className="btn btn-primary" disabled>
              Out of stock
            </button>
          )
        ) : (
          <button
            className="btn btn-primary"
            onClick={() => {
              onConsume(selectedLive.id, selectedLive.packageSize);
              setSelected(null);
            }}
          >
            <IconBarcode size={16} />
            Used up one package ({selectedLive.packageSize} {selectedLive.unit})
          </button>
        )}
      </div>

      <NfcLinkBlock item={selectedLive} />

      <div className="delete-block">
        {confirmDeleteFor === selectedLive.id ? (
          <>
            <p className="delete-confirm-text">
              Permanently remove {selectedLive.name} and its stock from the inventory?
            </p>
            <div className="sheet-actions">
              <button className="btn btn-ghost" onClick={() => setConfirmDeleteFor(null)}>
                Cancel
              </button>
              <button
                className="btn btn-danger"
                onClick={() => {
                  onDelete(selectedLive.id);
                  setConfirmDeleteFor(null);
                  setSelected(null);
                  setAlarmsOpen(false);
                }}
              >
                Delete
              </button>
            </div>
          </>
        ) : (
          <button
            className="btn btn-danger btn-block btn-lg"
            onClick={() => setConfirmDeleteFor(selectedLive.id)}
          >
            Delete item
          </button>
        )}
      </div>

      {twoPane && (
        <div className="detail-settings">
          <ItemSettings item={selectedLive} onUpdate={onUpdateItem}
                        onAddBarcode={onAddItemBarcode} onRemoveBarcode={onRemoveItemBarcode}
                        categories={categorySuggestions}
                        hasCustomLabel={hasCustomLabel(selectedLive.id)}
                        onToggleCustomLabel={toggleCustomLabel}
                        onEditCustomLabel={editItemLabel} />
        </div>
      )}
    </>
  ) : null;

  return (
    <div className="screen">
      <header className="screen-header">
        <h1 className="screen-title">
          {view === "items" ? "Inventory" : view === "receipts" ? "Receipts" : "Labels & barcodes"}
        </h1>
        <div className="header-actions">
          {view !== "barcodes" && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setView(view === "items" ? "receipts" : "items")}
              title={view === "items" ? "Show the receipt inbox" : "Back to the item list"}
            >
              {view === "items" ? (
                <>
                  <IconReceipt size={15} />
                  Receipts
                </>
              ) : (
                <>
                  <IconInventory size={15} />
                  Items
                </>
              )}
            </button>
          )}
          {view === "barcodes" && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setView("items")}
              title="Back to the item list"
            >
              <IconInventory size={15} />
              Items
            </button>
          )}
          {view === "receipts" && (
            <button className="icon-btn" onClick={() => setSettingsOpen(true)} aria-label="Model settings">
              <IconGear size={19} />
            </button>
          )}
          {view === "items" && (
            <>
              <button
                className="icon-btn"
                onClick={() => setScanLogOpen(true)}
                aria-label="Recent scans"
                title="Recent scans"
              >
                <IconClock size={19} />
              </button>
              <button className="icon-btn" onClick={() => setAddItemOpen(true)} aria-label="Add item manually" title="Add item">
                <IconPlus size={19} />
              </button>
              <button
                className="icon-btn"
                onClick={() => setView("barcodes")}
                aria-label="Labels and barcodes"
                title="Labels & barcodes"
              >
                <IconBarcode size={19} />
              </button>
            </>
          )}
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
        </div>
      </header>

      {view === "receipts" ? (
        <ReceiptsView receipts={receipts} onMatchItem={onMatchItem} />
      ) : view === "barcodes" ? (
        <BarcodesView
          items={items}
          customLabels={customLabels}
          onEditItemLabel={editItemLabel}
          onEditControlLabel={editControlLabel}
        />
      ) : twoPane ? (
        <div className="split">
          <div className="split-master">{itemsPane}</div>
          <aside className="split-detail">
            {detail ?? <div className="empty-state">Select an item to see its stock and alarms.</div>}
          </aside>
        </div>
      ) : (
        <>
          {itemsPane}
          {selectedLive && (
            <Sheet
              onClose={() => {
                setSelected(null);
                setAlarmsOpen(false);
              }}
              onHeaderClick={() => setAlarmsOpen(true)}
            >
              {detail}
            </Sheet>
          )}
        </>
      )}

      {view === "items" && selectedLive && alarmsOpen && !twoPane && (
        <AlarmSheet
          item={selectedLive}
          onUpdate={onUpdateItem}
          onAddBarcode={onAddItemBarcode}
          onRemoveBarcode={onRemoveItemBarcode}
          hasCustomLabel={hasCustomLabel(selectedLive.id)}
          onToggleCustomLabel={toggleCustomLabel}
          onEditCustomLabel={editItemLabel}
          onClose={() => setAlarmsOpen(false)}
          categories={categorySuggestions}
          onRename={(name) => onRenameItem(selectedLive.id, name)}
        />
      )}

      {settingsOpen && (
        <ModelSettingsSheet
          task="receipts"
          settings={settings}
          localModels={models.local}
          llmAvailable={models.llmAvailable}
          onSave={onSaveSettings}
          onClose={() => setSettingsOpen(false)}
        />
      )}

      {addItemOpen && (
        <AddItemSheet onAddItem={onAddItem} onClose={() => setAddItemOpen(false)} categories={categorySuggestions} />
      )}

      {scanLogOpen && (
        <ScanLogSheet
          scans={scanLog}
          onOpenReview={onOpenReview}
          onClose={() => setScanLogOpen(false)}
        />
      )}

      {labelEditorFor && (
        <LabelEditor
          target={labelEditorFor}
          onClose={closeLabelEditor}
          onSaved={labelEditorSaved}
        />
      )}
    </div>
  );
}
