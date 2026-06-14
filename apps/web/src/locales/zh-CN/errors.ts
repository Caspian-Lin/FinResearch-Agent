/**
 * 简体中文 — `errors` 命名空间。
 *
 * 重要:错误展示基于**稳定的错误码**(`error.*`),绝不以后端原始 message 字符串为 key。
 * 后端错误信息可能变更且不做本地化;前端将已知错误码映射为稳定、已翻译的用户文案。
 * 未知错误码回退到 `errors.unknown`。
 */

const errors = {
  /** 通用未知 / 未映射错误。绝不向用户暴露原始 key。 */
  unknown: '发生错误,请重试。',
  network: '网络错误,请检查连接后重试。',
  timeout: '请求超时,请重试。',
  unauthorized: '您没有执行该操作的权限。',
  forbidden: '访问被拒绝。',
  notFound: '未找到请求的资源。',
  conflict: '资源已存在或与现有数据冲突。',
  validation: '部分字段无效,请核对后重试。',
  rateLimited: '请求过于频繁,请稍候重试。',
  server: '服务器错误,我们已收到通知,请稍后重试。',

  /** 领域错误码:保持标识符稳定,在前端做映射。 */
  assetNotFound: '未找到该资产。',
  ohlcvSyncFailed: '同步该标的的 OHLCV 数据失败。',
  watchlistLimitReached: '观察列表条数已达上限。',
  watchlistNameExists: '已存在同名自选股。',
  backtestFailed: '回测执行失败,请检查参数后重试。',
} as const;

export default errors;
