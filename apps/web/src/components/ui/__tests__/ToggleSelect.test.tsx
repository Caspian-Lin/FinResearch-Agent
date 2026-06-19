/**
 * ToggleSelect component tests (FRA-45).
 *
 * Covers render (selected label / placeholder), open-on-click, option pick →
 * onChange + close, Escape close + focus return, click-outside close, keyboard
 * nav (ArrowUp/Down/Enter), and the a11y attributes (haspopup/expanded/listbox/
 * option/aria-selected). No antd involved — pure DOM assertions.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { ToggleSelect } from '@/components/ui/ToggleSelect';

const OPTIONS = [
  { value: 'en', label: 'English' },
  { value: 'zh', label: '中文' },
  { value: 'ja', label: '日本語' },
];

function renderSelect(props: Partial<Parameters<typeof ToggleSelect>[0]> = {}) {
  const onChange = vi.fn();
  const utils = render(
    <ToggleSelect
      options={OPTIONS}
      value="en"
      onChange={onChange}
      ariaLabel="Language"
      {...props}
    />,
  );
  return { onChange, ...utils };
}

beforeEach(() => {
  // jsdom leaves the menu in the DOM after each test via fixed positioning.
  document.body.innerHTML = '';
});

describe('ToggleSelect', () => {
  it('renders the selected option label on the trigger', () => {
    renderSelect({ value: 'zh' });
    expect(screen.getByRole('button', { name: 'Language' })).toHaveTextContent('中文');
  });

  it('renders the placeholder when no value is selected', () => {
    renderSelect({ value: null, placeholder: 'Pick one' });
    expect(screen.getByRole('button', { name: 'Language' })).toHaveTextContent('Pick one');
  });

  it('opens the menu on trigger click and exposes all options', () => {
    renderSelect();
    expect(screen.queryByRole('listbox')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Language' }));
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    expect(screen.getAllByRole('option')).toHaveLength(3);
    expect(screen.getByRole('option', { name: '中文' })).toBeInTheDocument();
  });

  it('calls onChange with the picked value and closes the menu', () => {
    const { onChange } = renderSelect();
    fireEvent.click(screen.getByRole('button', { name: 'Language' }));
    fireEvent.click(screen.getByRole('option', { name: '中文' }));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith('zh');
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  it('closes on Escape and returns focus to the trigger', () => {
    renderSelect();
    const trigger = screen.getByRole('button', { name: 'Language' });
    fireEvent.click(trigger);
    const menu = screen.getByRole('listbox');
    fireEvent.keyDown(menu, { key: 'Escape' });
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it('closes on outside click', () => {
    renderSelect();
    fireEvent.click(screen.getByRole('button', { name: 'Language' }));
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    // mousedown outside both trigger and menu.
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  it('navigates with ArrowDown/Up and selects with Enter', () => {
    const { onChange } = renderSelect({ value: 'en' });
    fireEvent.click(screen.getByRole('button', { name: 'Language' }));
    const menu = screen.getByRole('listbox');
    // Active starts at the selected index (en=0). Down → zh (1), Enter picks.
    fireEvent.keyDown(menu, { key: 'ArrowDown' });
    fireEvent.keyDown(menu, { key: 'Enter' });
    expect(onChange).toHaveBeenCalledWith('zh');
  });

  it('marks the selected option with aria-selected', () => {
    renderSelect({ value: 'ja' });
    fireEvent.click(screen.getByRole('button', { name: 'Language' }));
    const opts = screen.getAllByRole('option');
    expect(opts[2]).toHaveAttribute('aria-selected', 'true');
    expect(opts[0]).toHaveAttribute('aria-selected', 'false');
  });

  it('exposes aria-haspopup / aria-expanded on the trigger', () => {
    renderSelect();
    const trigger = screen.getByRole('button', { name: 'Language' });
    expect(trigger).toHaveAttribute('aria-haspopup', 'listbox');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
  });

  it('does not open when disabled', () => {
    renderSelect({ disabled: true });
    const trigger = screen.getByRole('button', { name: 'Language' });
    expect(trigger).toBeDisabled();
    fireEvent.click(trigger);
    expect(screen.queryByRole('listbox')).toBeNull();
  });
});
