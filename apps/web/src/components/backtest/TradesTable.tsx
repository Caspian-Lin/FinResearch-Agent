/**
 * Backtest trade-detail table (FRA-38).
 *
 * Lists the persisted fills (FRA-42): time, asset (symbol if known, else a
 * short asset-id stub), side (buy/sell tag), quantity, price, cost. Empty until
 * the worker reaches success; pagination + side filter keep large trade logs
 * browseable. The `symbolByAsset` map comes from the universe watchlist so
 * traded assets show their symbol rather than a bare UUID.
 */
import { Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';

import type { TradeRead } from '@/types/api';

interface TradesTableProps {
  trades: TradeRead[];
  /** Optional asset_id → symbol map (from the universe watchlist). */
  symbolByAsset?: Record<string, string>;
}

function fmt(value: number, fractionDigits: number): string {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  });
}

export function TradesTable({ trades, symbolByAsset }: TradesTableProps) {
  const { t } = useTranslation();

  const columns: ColumnsType<TradeRead> = [
    {
      title: t('backtest:trades.columns.time'),
      dataIndex: 'time',
      key: 'time',
      render: (time: string) => dayjs(time).format('YYYY-MM-DD'),
      sorter: (a, b) => a.time.localeCompare(b.time),
      defaultSortOrder: 'ascend',
    },
    {
      title: t('backtest:trades.columns.asset'),
      dataIndex: 'asset_id',
      key: 'asset',
      render: (assetId: string) => symbolByAsset?.[assetId] ?? `${assetId.slice(0, 8)}…`,
    },
    {
      title: t('backtest:trades.columns.side'),
      dataIndex: 'side',
      key: 'side',
      render: (side: string) => (
        <Tag color={side === 'buy' ? 'green' : 'red'}>{t(`backtest:trades.side.${side}`)}</Tag>
      ),
      filters: [
        { text: t('backtest:trades.side.buy'), value: 'buy' },
        { text: t('backtest:trades.side.sell'), value: 'sell' },
      ],
      onFilter: (value, record) => record.side === String(value),
    },
    {
      title: t('backtest:trades.columns.quantity'),
      dataIndex: 'quantity',
      key: 'quantity',
      align: 'right',
      render: (q: number) => q.toLocaleString(undefined, { maximumFractionDigits: 4 }),
    },
    {
      title: t('backtest:trades.columns.price'),
      dataIndex: 'price',
      key: 'price',
      align: 'right',
      render: (p: number) => fmt(p, 2),
    },
    {
      title: t('backtest:trades.columns.cost'),
      dataIndex: 'cost',
      key: 'cost',
      align: 'right',
      render: (c: number) => fmt(c, 2),
    },
  ];

  return (
    <Table<TradeRead>
      rowKey="id"
      columns={columns}
      dataSource={trades}
      size="small"
      pagination={{ pageSize: 10, showSizeChanger: false }}
    />
  );
}

export default TradesTable;
