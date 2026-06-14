/**
 * 简体中文 — `auth` 命名空间。
 *
 * 登录 / 会话相关 UI 文案。仅作为表单标签,后端返回的错误信息不作为 key;
 * 错误文案基于稳定错误码翻译,详见 `errors` 命名空间。
 */

const auth = {
  signIn: {
    title: '登录',
    email: {
      label: '邮箱',
      placeholder: 'you@example.com',
    },
    password: {
      label: '密码',
      placeholder: '请输入密码',
    },
    submit: '登录',
    /** 从注册页跳转回登录页的链接文案。 */
    link: '去登录',
  },
  register: {
    title: '创建账户',
    email: {
      label: '邮箱',
      placeholder: 'you@example.com',
    },
    password: {
      label: '密码',
      placeholder: '至少 8 位字符',
    },
    passwordConfirm: {
      label: '确认密码',
    },
    submit: '注册',
    /** 从登录页跳转到注册页的链接文案。 */
    link: '去注册',
    /** 注册成功后跳转登录页前的提示。 */
    success: '账户创建成功,请登录。',
  },
  /** 会话刷新恢复期间的全屏加载文案。 */
  loading: '正在恢复您的会话…',
  signOut: '退出登录',
  userMenu: {
    /** 下拉菜单项文案。 */
    signOut: '退出登录',
  },
  session: {
    expired: '您的会话已过期,请重新登录。',
  },
} as const;

export default auth;
