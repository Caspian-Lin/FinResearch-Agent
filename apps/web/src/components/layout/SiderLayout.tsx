/**
 * SiderLayout — shared left-sider + right-main layout for authenticated pages
 * (FRA-45). Extracted from the dashboard's original markup so dashboard /
 * watchlist / backtest compose identically: each page renders
 * `<SiderLayout sidebar={<…Sidebar/>}>{main}</SiderLayout>`.
 *
 * Layout mechanics live in `index.css` under `.sider-layout*`:
 *  - #root locks the viewport (height:100vh + overflow:hidden); the app shell
 *    is a flex column of header / .app-content / footer, so .app-content is a
 *    fixed-height stage;
 *  - .sider-layout fills that stage (height:100%) and the sider + main each
 *    scroll on their own — the sider stays floor-to-ceiling while only the main
 *    scrolls, so no page-level scrollbar ever appears (the footer is always
 *    visible, never covered);
 *  - full-bleed via MARGIN (NOT transform — a transform would make descendant
 *    position:fixed/sticky relative to this box instead of the viewport).
 *
 * Pages own all state/polling/modals; the sidebar they pass in is a
 * pure-presentational component. This component only wires the antd
 * Layout/Sider/Content skeleton.
 */
import type { ReactNode } from 'react';
import { Layout } from 'antd';

const { Sider, Content } = Layout;

export interface SiderLayoutProps {
  sidebar: ReactNode;
  children: ReactNode;
  /** antd Sider width in px. Default 248 (matches the dashboard). */
  siderWidth?: number;
  /** Extra class on the outer <Layout> (page-specific overrides). */
  className?: string;
}

export function SiderLayout({ sidebar, children, siderWidth = 248, className }: SiderLayoutProps) {
  return (
    <Layout className={['sider-layout', className].filter(Boolean).join(' ')}>
      <Sider className="sider-layout-sider" theme="light" width={siderWidth} trigger={null}>
        {sidebar}
      </Sider>
      <Content className="sider-layout-main">{children}</Content>
    </Layout>
  );
}

export default SiderLayout;
