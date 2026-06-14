/**
 * Cross-page asset selection store.
 *
 * When a user picks an asset on the Watchlist page ("view in dashboard"), the
 * selection lands here so the Dashboard (FRA-11) can read it without prop
 * drilling or URL plumbing. Intentionally NOT persisted — a page reload
 * clears the selection, which is the safe default for financial UIs.
 */
import { create } from 'zustand';

import type { SelectedAsset } from '@/types/api';

interface SelectionState {
  /** Currently selected asset id, or null. */
  selectedAssetId: string | null;
  /** Currently selected asset projection, or null. */
  selectedAsset: SelectedAsset | null;
  /** Set the active selection. */
  setSelectedAsset: (asset: SelectedAsset) => void;
  /** Clear the active selection. */
  clearSelection: () => void;
}

export const useSelectionStore = create<SelectionState>((set) => ({
  selectedAssetId: null,
  selectedAsset: null,
  setSelectedAsset: (asset) => set({ selectedAssetId: asset.asset_id, selectedAsset: asset }),
  clearSelection: () => set({ selectedAssetId: null, selectedAsset: null }),
}));
