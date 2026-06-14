/**
 * 简体中文 — `auth` 命名空间。
 *
 * 登录 / 会话相关 UI 文案。仅作为表单标签,后端返回的错误信息不作为 key;
 * 错误文案基于稳定错误码翻译,详见 `errors` 命名空间。
 */

const auth = {
  signIn: {
    title: '登录',
    username: '用户名',
    password: '密码',
    submit: '登录',
    rememberMe: '记住我',
  },
  signOut: '退出登录',
  session: {
    expired: '您的会话已过期,请重新登录。',
  },
} as const;

export default auth;
