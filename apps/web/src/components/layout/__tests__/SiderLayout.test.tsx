/**
 * SiderLayout component tests (FRA-45).
 *
 * Pure structural: renders the sidebar + children, applies the outer className,
 * and forwards siderWidth to the antd Sider (which sets it as an inline style).
 * No CSS/layout behaviour asserted (that's covered by manual e2e).
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

import { SiderLayout } from '@/components/layout/SiderLayout';

describe('SiderLayout', () => {
  it('renders the sidebar and the main children', () => {
    render(
      <SiderLayout sidebar={<div>SIDEBAR</div>}>
        <div>MAIN</div>
      </SiderLayout>,
    );
    expect(screen.getByText('SIDEBAR')).toBeInTheDocument();
    expect(screen.getByText('MAIN')).toBeInTheDocument();
  });

  it('applies the outer className alongside the base class', () => {
    const { container } = render(
      <SiderLayout className="page-override" sidebar={<span />}>
        <span />
      </SiderLayout>,
    );
    const layout = container.querySelector('.sider-layout');
    expect(layout).toBeInTheDocument();
    expect(layout).toHaveClass('page-override');
  });

  it('forwards siderWidth to the antd Sider (inline width)', () => {
    const { container } = render(
      <SiderLayout siderWidth={300} sidebar={<span />}>
        <span />
      </SiderLayout>,
    );
    const sider = container.querySelector('.sider-layout-sider');
    expect(sider).toHaveStyle({ width: '300px' });
  });

  it('defaults siderWidth to 248', () => {
    const { container } = render(
      <SiderLayout sidebar={<span />}>
        <span />
      </SiderLayout>,
    );
    expect(container.querySelector('.sider-layout-sider')).toHaveStyle({ width: '248px' });
  });
});
