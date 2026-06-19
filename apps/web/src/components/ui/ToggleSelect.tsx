/**
 * ToggleSelect — a custom single-select dropdown for "switch between a fixed
 * set of options" UIs (language, watchlist, data source, …).
 *
 * Why custom (FRA-45): AntD `Select` needs a wall of `!important` token
 * overrides to match the project palette (see the old `.language-switcher`
 * rules in index.css). This component renders straight off the project's
 * `--fra-*` CSS variables, so every toggle across the app shares one look with
 * no antd-token wrestling. It is NOT a replacement for search/typeahead selects
 * — those keep antd `Select` with `showSearch`. Use this only for picking one
 * value from a known finite list.
 *
 * Accessibility: the trigger is `button[aria-haspopup=listbox][aria-expanded]`;
 * the menu is `ul[role=listbox]` with `option` items. Keyboard: Enter / Space /
 * ArrowDown opens; Up/Down move the active row; Enter selects; Escape closes and
 * returns focus to the trigger. Click-outside closes.
 *
 * The menu is `position: fixed` (placed via the trigger's bounding rect) so it
 * escapes any ancestor `overflow: auto` (e.g. the dashboard sidebar list) and
 * sticks to the viewport regardless of where the trigger lives.
 */
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import { createPortal } from 'react-dom';

export interface ToggleSelectOption {
  value: string;
  label: string;
}

export interface ToggleSelectProps {
  options: ToggleSelectOption[];
  /** Controlled value. Optional so the component can sit inside an antd
   *  Form.Item, which injects value/onChange at runtime (TS can't see that). */
  value?: string | null;
  onChange?: (value: string) => void;
  ariaLabel?: string;
  placeholder?: string;
  /** Trigger width (px when number, raw CSS otherwise). Omit → fit content. */
  width?: number | string;
  size?: 'small' | 'middle';
  disabled?: boolean;
  loading?: boolean;
  className?: string;
}

export function ToggleSelect({
  options,
  value,
  onChange,
  ariaLabel,
  placeholder = '',
  width,
  size = 'middle',
  disabled = false,
  loading = false,
  className,
}: ToggleSelectProps) {
  const listId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLUListElement>(null);

  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [coords, setCoords] = useState({ top: 0, left: 0, width: 0 });

  const selectedIndex = options.findIndex((o) => o.value === value);
  const selected = selectedIndex >= 0 ? options[selectedIndex] : null;

  const openMenu = useCallback(() => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) {
      setCoords({ top: rect.bottom + 4, left: rect.left, width: rect.width });
    }
    setActiveIndex(selectedIndex >= 0 ? selectedIndex : 0);
    setOpen(true);
  }, [selectedIndex]);

  const close = useCallback(() => setOpen(false), []);

  const choose = useCallback(
    (v: string) => {
      onChange?.(v);
      close();
    },
    [onChange, close],
  );

  // Close on outside click / Escape while open; focus the menu for kbd nav.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      const target = e.target as Node;
      if (triggerRef.current?.contains(target)) return;
      if (menuRef.current?.contains(target)) return;
      close();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') close();
    }
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKey);
    // Focus the menu so Up/Down/Enter work without moving DOM focus manually.
    const t = window.setTimeout(() => menuRef.current?.focus(), 0);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKey);
      window.clearTimeout(t);
    };
  }, [open, close]);

  function onTriggerKeyDown(e: ReactKeyboardEvent<HTMLButtonElement>) {
    if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
      e.preventDefault();
      if (!open) openMenu();
    }
  }

  function onMenuKeyDown(e: ReactKeyboardEvent<HTMLUListElement>) {
    if (options.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((i) => (i + 1) % options.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((i) => (i - 1 + options.length) % options.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const opt = options[activeIndex];
      if (opt) choose(opt.value);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      close();
      triggerRef.current?.focus();
    }
  }

  const sizeClass = size === 'small' ? 'toggle-select-sm' : '';
  const triggerStyle = width
    ? { width: typeof width === 'number' ? `${width}px` : width }
    : undefined;

  return (
    <span className={`toggle-select ${sizeClass} ${className ?? ''}`.trim()}>
      <button
        ref={triggerRef}
        type="button"
        className="toggle-select-trigger"
        style={triggerStyle}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={ariaLabel}
        disabled={disabled || loading}
        onClick={() => (open ? close() : openMenu())}
        onKeyDown={onTriggerKeyDown}
      >
        <span className="toggle-select-label">
          {loading ? placeholder || '…' : selected ? selected.label : placeholder}
        </span>
        <span className={`toggle-select-arrow ${open ? 'is-open' : ''}`} aria-hidden>
          ▾
        </span>
      </button>
      {open &&
        createPortal(
          <ul
            ref={menuRef}
            id={listId}
            role="listbox"
            tabIndex={-1}
            className="toggle-select-menu"
            style={{ top: coords.top, left: coords.left, minWidth: coords.width }}
            onKeyDown={onMenuKeyDown}
          >
            {options.map((opt, i) => (
              <li
                key={opt.value}
                role="option"
                aria-selected={i === selectedIndex}
                className={[
                  'toggle-select-option',
                  i === activeIndex ? 'is-active' : '',
                  i === selectedIndex ? 'is-selected' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                onClick={() => choose(opt.value)}
                onMouseEnter={() => setActiveIndex(i)}
              >
                {opt.label}
              </li>
            ))}
          </ul>,
          document.body,
        )}
    </span>
  );
}

export default ToggleSelect;
