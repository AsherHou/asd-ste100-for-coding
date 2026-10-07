# T1：Add Google sign-in to an existing email/password web app

下面是一个对比任务的原始输出，只做了脱敏。这个任务在生成之前就选定了。各组拿到的简报和请求完全相同，只有项目的 `CLAUDE.md` 不同。

**请求**: 在 Tallybook 的登录页和注册页加上“使用 Google 登录”，让用户可以用自己的 Google 账号代替密码登录，并且要能和我们现有的邮箱/密码账号兼容配合。在动手改任何东西之前，先给我一份方案，等我审批通过再执行。

## A · 普通 agent

<details>
<summary>展开完整回复 (2200 字)</summary>

# 方案：Tallybook 接入“使用 Google 登录”

按你的要求，这次只出方案，不改任何文件。下面先列出需要你拍板的决策和外部依赖，然后是技术设计、改动清单和上线步骤。

## 一、需要先确定的事项

**1. 账号关联规则（最关键）**

我建议：**只用 Google 的 `sub` 识别用户，不靠邮箱自动合并账号。** 如果 Google 返回的邮箱已经对应一个现有账号，必须先用该账号的密码登录确认，才能完成关联。

原因：现在约 9,000 个账号从未验证过邮箱。如果按邮箱自动合并，会出现“预先劫持”：

1. 攻击者先用受害者的邮箱和自己设的密码注册（不需要验证）。
2. 受害者后来用 Google 登录，被自动并入这个账号。
3. 攻击者仍然可以用密码登录，看到受害者的发票、客户和银行导出文件。

要求密码确认就能堵住这个口子。真正的邮箱主人如果不知道密码，可以走“忘记密码”。重置流程本身证明了邮箱所有权，前提是重置会清掉该用户的所有旧会话（见第三节第 6 条）。

代价：已有密码账号的用户第一次用 Google 登录时多一步输密码。如果你更看重顺滑，可以只对“本地已验证且 Google 返回 `email_verified=true`”的账号自动关联。但我不推荐用于自定义企业域名的邮箱，因为域名或邮箱可能易主。

**2. 需要创始人亲自完成的工作（工程师没有控制台权限）**

- 在 `tallybook-prod` 中配置 OAuth 同意屏幕，包括应用名称、首页、隐私政策 URL 和授权域名 `tallybook.example.com`。范围只用 `openid email profile`，不属于敏感 scope，但上传 logo 等品牌信息可能需要 Google 审核。
- 建两个 OAuth 客户端（Web 类型）：
  - **生产**：回调为 `https://app.tallybook.example.com/auth/google/callback`
  - **非生产**：回调为 staging 地址和 `http://localhost:3000/auth/google/callback`。这个客户端保持 Testing 状态，并加入测试用户。
- 把 `GOOGLE_CLIENT_ID` 和 `GOOGLE_CLIENT_SECRET` 写入托管平台的 staging 和生产环境设置，非生产那套同时放进密码管理器保险库。
- 另外，这个项目是之前地址自动补全实验留下的。建议顺便检查一下是否还有遗留的 API key 没撤销，或者另建一个专用项目。由你们决定。

**3. 隐私政策（这是生产上线的硬性前提）**

现行政策只写了“邮箱 + 密码”，没有提从 Google 接收的数据（邮箱、姓名、Google 账号 ID）。所以生产环境开启功能之前，必须先修订 `public/legal/privacy.html`，经创始人批准、外部法律顾问审阅后再发布。Google 同意屏幕也会引用这个 URL。我可以起草修订文本供审阅，但不会自行合并。

**4. 预览部署**

Google 不支持通配符回调地址，`pr-<n>.preview…` 没法注册。我建议预览环境里不显示 Google 按钮，具体做法见第三节第 7 条。

## 二、技术设计

**库选择**：用 `openid-client` 走标准 OIDC 授权码流程，配合 PKCE、`state` 和 `nonce`，并校验 ID Token 的签名、`iss`、`aud`、`exp`、`nonce`。不选 `passport-google-oauth20`，因为它不做 ID Token / nonce 校验。登录成功后仍然调用 Passport 的 `req.login()`，与现有会话体系共用。

**数据库迁移**（`db/migrations/`）：
- 新建 `user_identities` 表，字段为 `id`、`user_id`（外键关联 `users`，级联删除）、`provider`、`provider_subject`、`email_at_link`、`created_at`、`last_used_at`。在 `(provider, provider_subject)` 上加唯一约束，在 `(user_id, provider)` 上也加唯一约束。表结构是通用的，方便以后做 #388（Microsoft / Apple 登录）。
- 把 `users.password_hash` 改成可为空。只用 Google 注册的用户没有密码。
- 两步都是新增或放宽约束，与旧版本代码兼容。发布时先跑迁移再切流量，没有问题。

**路由**（新文件 `src/auth/google.ts`，挂到 `routes.ts`）：

| 路由 | 行为 |
|---|---|
| `GET /auth/google` | 生成 state、nonce 和 PKCE verifier，302 跳转到 Google |
| `GET /auth/google/callback` | 校验 state 和 ID Token，然后进入下表分支 |
| `GET/POST /auth/google/link` | 匹配到已有账号时，要求输入该账号密码确认关联（POST 走现有 CSRF 校验） |
| `POST /account/security/google/unlink` | 解绑。仅在账号设置了密码时允许，避免用户把自己锁在外面 |

回调的分支逻辑：

| 情况 | 处理 |
|---|---|
| `sub` 已关联某个用户 | 直接登录 |
| 当前已登录（从安全设置页发起关联） | 把这个 Google 身份关联到当前用户 |
| Google 返回 `email_verified !== true` | 拒绝，并提示原因 |
| 邮箱匹配到已有账号 | 把待关联信息暂存，跳转到密码确认页 |
| 没有匹配 | 新建用户：`password_hash` 为 NULL，`email_verified_at` 设为当前时间，`display_name` 取 Google 的 name |

另外两条规则：
- Google 侧邮箱以后发生变化时，不自动改 `users.email`。
- 关联成功后给该账号邮箱发一封“已关联 Google 登录”的通知邮件。

## 三、现有配置带来的坑（必须处理）

**1. `sameSite: 'strict'` 会破坏回调**

Google 跳回 `/auth/google/callback` 属于跨站导航，`tb.sid` 不会随请求发送，存在会话里的 state 就取不到了。

处理方法：state、nonce 和 verifier 放进一个独立的短期 cookie `tb.oauth`，属性为 `httpOnly`、`secure`、`sameSite=lax`、`path=/auth/google`、有效期 10 分钟，签名后存放，用完立即清除。

**2. 登录后第一跳同样受 strict 影响**

回调里设置好会话后，如果直接 302 到 `/dashboard`，这条重定向链仍算跨站发起，新的 `tb.sid` 不会被带上，用户看起来像没登录。

处理方法：回调返回一个 200 的极简页面，用 `<meta http-equiv="refresh">` 做同站跳转。这样不需要放宽 CSP 的 script 限制，也不需要把 `tb.sid` 改成 lax。

**3. CSP 的 `form-action 'self'`**

Chrome 会拦截“表单提交之后重定向到外部域”的跳转。所以“使用 Google 登录”做成指向 `/auth/google` 的普通链接，而不是表单。这样也不用往 `form-action` 里加 Google 的域名。发起端用 GET 的 CSRF 风险很低，回调端由 state 和 PKCE 保护。

**4. 会话固定攻击**

确认 Passport 版本不低于 0.6，这样 `req.login()` 会重新生成会话 ID。如果版本更低，就手动调用 `req.session.regenerate()`。

**5. 只有 Google 登录的用户（`password_hash` 为 NULL）**

- `passport.ts` 中的 local 策略遇到 NULL 哈希时，按“密码错误”返回统一错误，不向外透露该账号是 Google 账号。
- `security.ejs` 对这类用户显示“设置密码”，而不是“修改密码”。

**6. 密码重置流程（`reset.ts`）**

需要确认并补齐两点：
- 重置成功后删除该用户的所有会话。做法是从 `session` 表按 `sess->'passport'->>'user'` 找到并删除。
- 同时把 `email_verified_at` 置为当前时间。

这两点是第一节第 1 条安全论证的前提。

**7. 配置与开关**

- 在 `config.ts` 里新增 `GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、`GOOGLE_REDIRECT_URI`，仅在 `FEATURE_GOOGLE_LOGIN` 开启时才要求必填。
- 预览环境会继承 staging 的配置，所以只有当请求的 host 与 `GOOGLE_REDIRECT_URI` 的 host 一致时才渲染 Google 按钮。这样预览部署会自动隐藏按钮。

## 四、改动清单

- **新增**：
  - `src/auth/google.ts`
  - `db/migrations/<ts>_user_identities.ts`
  - `src/views/auth/google-link.ejs`
  - `src/views/auth/oauth-redirect.ejs`
  - `test/auth/google.test.ts`
- **修改**：
  - `src/auth/routes.ts`
  - `src/auth/passport.ts`
  - `src/auth/reset.ts`
  - `src/config.ts`
  - `src/flags.ts`
  - `src/views/auth/login.ejs`
  - `src/views/auth/signup.ejs`
  - `src/views/account/security.ejs`
  - `.env.example`（如果仓库里有的话）
- **不在本次范围**：Microsoft / Apple 登录（#388）、会话存储迁移到 Redis（#412）。

## 五、测试

**Jest + supertest**：用一个本地伪造的 OIDC issuer（自签 JWKS），不访问真实的 Google。覆盖以下场景：
- state 不匹配、nonce 不匹配、`aud` 或 `iss` 错误、ID Token 过期，都应拒绝
- `email_verified=false` 拒绝
- 新用户注册
- `sub` 已关联时直接登录
- 邮箱冲突时必须输对密码才能关联
- 预先劫持场景：重置密码后攻击者原有的会话失效
- NULL 哈希账号走密码登录被拒，且错误信息统一
- 有密码才能解绑
- 登录后会话 ID 已更换
- 开关关闭时路由返回 404

**Playwright 冒烟测试**：不接入 Google，避免依赖外部服务导致不稳定。staging 上由人工用测试用户按清单走一遍。

## 六、上线顺序

1. 提 PR（默认关闭开关），评审后合并，自动部署到 staging。
2. 创始人配置非生产客户端，在 staging 开启 `FEATURE_GOOGLE_LOGIN`，人工验收。
3. 隐私政策修订完成法律审阅并发布。
4. 创始人配置生产客户端和密钥，把构建提升到生产，开启开关。
5. 观察登录错误率和关联数量。出问题时关闭开关即可回滚。迁移本身无需回滚。

---

**请确认：**
- 第一节第 1 条的关联策略：强制密码确认，还是对已验证账号自动关联？
- 预览环境隐藏按钮的做法是否可以接受？
- 是否需要我同时起草隐私政策的修订文本？

确认后我再开始改代码。

</details>

## D · plan-first

**批准人读到的内容** (1521 字):

# 在登录页和注册页加上"使用 Google 登录"

> 状态：待批准 · v1 · 2026-10-07
>
> agent 执行版：[../plan/2026-10-07-google-login.md](../plan/2026-10-07-google-login.md)

## 这次要做什么

1. **新增 Google 登录和注册**
   - 目的：用户可以用 Google 账号登录，不用再记一个密码。这是你的要求。
   - 做完后：
     - 登录页和注册页会出现"使用 Google 登录"按钮。这是你的要求。
     - 没有账号的人点这个按钮，Tallybook 会直接为对方创建账号。
     - 只用 Google 注册的账号没有密码。需要密码时，用户可以用"忘记密码"邮件设置一个。
     - 按钮由一个功能开关控制。功能开关是一项环境设置，打开后按钮才会出现。
     - 在 staging 上，你可以用自己的 Google 账号登录成功。
2. **兼容已有的邮箱密码账号**（依赖功能 1）
   - 目的：已有账号的人用 Google 登录时，应该进入原来的账号。否则用户会多出一个空账号。这是你的要求。
   - 做完后：
     - "关联"指把一个 Google 账号和一个 Tallybook 账号绑在一起。关联后，用户用 Google 登录会进入这个账号。
     - 邮箱相同时，Tallybook 按"需要你决定的事"第 1 项的规则决定是否自动关联。
     - 不能自动关联时，页面会请用户先用密码登录，再去账号安全页关联。
     - 每次关联成功，Tallybook 会给账号邮箱发一封通知邮件。
     - 原来的邮箱密码登录照常可用。
3. **在账号安全页管理 Google 关联**（依赖功能 1）
   - 目的：已登录的用户可以自己关联或解除关联 Google 账号。
   - 做完后：
     - 账号安全页会显示是否已关联 Google，并提供"关联"和"解除关联"两个按钮。
     - 账号没有密码时，Tallybook 不允许解除关联。这样用户不会被锁在账号外面。

不做：我不会加 Microsoft 和 Apple 登录（Issue #388）。我不会修改隐私政策。PR 预览环境上不会显示 Google 按钮，因为 Google 要求提前登记每个回调地址。

## 需要你决定的事

1. **同一邮箱已有账号时，用 Google 登录要自动关联吗？**（功能 2，能回退）
   - 推荐：只在 Google 能担保这个邮箱时自动关联。担保指 gmail.com 邮箱，或由公司 Google Workspace 管理的邮箱。其他邮箱在 Google 那边的"已验证"可能是很久以前的状态，被冒用的风险更高。这些用户需要先用密码登录，再手动关联。
   - 备选 A：只要 Google 标记邮箱已验证，就自动关联。用户更省事，但企业域名邮箱的风险更高。
   - 备选 B：一律不自动关联，都要先用密码登录再手动关联。最安全，但每个老用户都要多走一步。
2. **自动关联一个从未验证邮箱的老账号时，要清除它原来的密码吗？**（功能 2，难回退）
   - 推荐：清除密码，并让这个账号在其他设备上全部退出登录。别人可能早就用这个邮箱注册并设了密码，清除后对方就进不来了。Tallybook 会在通知邮件里说明，用户需要时可以用"忘记密码"重设。
   - 备选：保留原密码，只把邮箱标记为已验证。
   - 代价：被清除的密码找不回来。现在约有 9,000 个未验证邮箱的账号，但只有用 Google 登录的那部分会受影响。
3. **合并上线后，生产环境先保持 Google 登录关闭吗？**（难回退）
   - 推荐：先关闭。隐私政策现在没写通过 Google 登录，需要律师改完、你批准之后再打开。打开只需要改一项环境设置。
   - 备选：合并后直接在生产环境打开。
   - 代价：一旦有人只用 Google 注册，再关闭开关，这些人就只能靠"忘记密码"邮件登录。

全部按推荐，回复"批准"即可开始；要改某项，回复如"1 选备选 A"，其余按推荐，也即可开始。

## 需要你做的事

- 开始执行时：请创始人在 Google Cloud 项目 tallybook-prod 里完成两件事。第一件是配置同意屏幕，也就是用户点按钮后 Google 显示的授权页。第二件是创建一个网页客户端。只有创始人有这个权限。我会在执行版里列出每一项要填什么。约 30 分钟。
- 拿到客户端以后：请创始人或首席工程师把客户端编号和密钥填进 staging 的环境设置和团队密码库，并打开 staging 的功能开关。约 10 分钟。
- 我提交 PR 以后：请安排一位同事评审并合并。main 分支要求至少一个评审批准。约 30 分钟。
- 部署到 staging 以后：请你用自己的 Google 账号在 staging 上登录一次，再关联一次。我没法替你登录 Google。约 10 分钟。

## 影响面

- 会改：登录页、注册页、账号安全页、密码登录和找回密码的代码、配置和功能开关，约 11 个文件。
- 新增：
  - 一张数据库表，记录哪个 Google 账号关联了哪个 Tallybook 账号。
  - 一个依赖 openid-client，按 Google 的标准校验登录结果，不用自己写校验代码。
  - 一封"已关联 Google 账号"通知邮件，提醒账号主人留意这次变化。
  - 一个只存 10 分钟的临时 cookie，用来在跳转 Google 前后接上登录过程。
  - 约 13 个新文件，包括代码、页面和测试。
- 删除：无。
- 对外行为：
  - 数据库里用户的"密码"一栏会改为可以为空。生产环境会在下一次发布时执行这个改动。
  - 功能开关关闭时，用户看不到任何变化。
  - 开关打开后，Tallybook 会从 Google 收到用户的邮箱、姓名和 Google 账号编号。
  - 现有的登录 cookie 和安全策略保持不变。

预计时间：AI 约 4 小时；你约 1 小时 20 分钟。

<details>
<summary>展开给 agent 的计划 (3805 字)</summary>

# Plan：登录/注册页新增 Google 登录，并与邮箱密码账号兼容

> 状态：待批准 · v1 · 2026-10-07
>
> 人读版：[../human/2026-10-07-google-login.md](../human/2026-10-07-google-login.md)

## 1. 状态
待批准 · v1 · 2026-10-07

## 2. 目标和完成标准

F1 新增 Google 登录和注册
- F1-1 `FEATURE_GOOGLE_LOGIN=true` 且 GOOGLE_* 配置齐全且请求 host 等于 `GOOGLE_REDIRECT_URI` 的 host 时，`/login`、`/signup` 渲染 Google 按钮；任一条件不满足时不渲染，`/auth/google*` 返回 404。supertest 覆盖。
- F1-2 `GET /auth/google` 302 到 `https://accounts.google.com/...`，URL 含 `state`、`nonce`、`code_challenge`（S256）、`scope=openid email profile`，并设置 `tb.oauth` cookie。测试覆盖。
- F1-3 callback 的 state 不匹配、cookie 缺失、cookie 被篡改或过期 → 400，不建会话。测试覆盖。
- F1-4 无对应账号且 `email_verified=true` → 新建用户（`password_hash` NULL，`email_verified_at`=now，`display_name`=Google `name`，缺省时用邮箱 @ 前部分）并写 `user_identities`，登录成功。`email_verified!==true` → 拒绝页，不建账号。测试覆盖。
- F1-5 `password_hash` 为 NULL 的用户：local 登录返回与密码错误相同的失败；重置密码流程可以给它设置密码。测试覆盖。
- F1-6 staging：用户手工用 Google 账号登录成功（第 10 项最后一条）。

F2 兼容已有的邮箱密码账号
- F2-1 按 `sub` 找到 identity → 登录该用户，不看邮箱。
- F2-2 邮箱命中已有用户：权威邮箱（域名 gmail.com / googlemail.com，或 `hd` 声明存在且等于邮箱域名）→ 自动关联；非权威 → 渲染 `google-link-required` 页，不关联不登录。（决定 1 的推荐；选备选时按第 9 项改判据）
- F2-3 自动关联到 `email_verified_at IS NULL` 的用户 → 同事务内设 `email_verified_at`、`password_hash=NULL`，删除该用户在 `session` 表中的全部会话后再建新会话。（决定 2 的推荐）
- F2-4 该用户已关联另一个 Google 账号 → 错误页，不改数据。
- F2-5 每次关联成功发送"已关联 Google 账号"邮件（测试中断言发信函数被调用及收件人）。
- F2-6 已关联用户的密码登录照常成功。
以上全部有测试。

F3 账号安全页管理关联
- F3-1 `/account/security` 显示关联状态；未关联时显示"关联 Google"链接（`GET /auth/google/link`），已关联时显示"解除关联"表单（POST，带 CSRF token）。
- F3-2 `GET /auth/google/link` 未登录 → 重定向 `/login`。登录态下完成流程后关联到当前用户；该 `sub` 已属于别的用户 → 错误页。
- F3-3 `password_hash` 为 NULL 时解除关联 → 400 且不删除；有密码 → 删除 identity 并发通知邮件。
- F3-4 `password_hash` 为 NULL 时，安全页不显示"当前密码"修改表单，改为"通过邮件设置密码"按钮（复用现有忘记密码发信）。
以上全部有测试。

G 通用
- G-1 `npm run lint`、`npx tsc --noEmit`、`npx jest` 本地全过；PR 的 CI 全绿。
- G-2 迁移 `up` → `down` → `up` 在本地空库上成功。
- G-3 合并后 staging 自动部署，Playwright 冒烟测试通过。

## 3. 背景与约束
- 栈：Node 20、Express 4、EJS、Postgres 15、Knex 迁移、Passport local、express-session + connect-pg-simple。
- `tb.sid`：`sameSite: 'strict'`。从 accounts.google.com 跳回的 callback 是跨站顶层导航，**不带 `tb.sid`**；callback 后的 302 链在浏览器里仍算跨站。因此 OAuth 状态不能存进 session，最终建会话也不能放在 callback 里。
- CSP 含 `form-action 'self'`：Chrome 对表单提交后的跳转也执行 form-action。所以发起 Google 登录用 `<a>` 链接（GET），不用表单。
- CSRF 中间件校验所有 POST；callback 是 GET，不受影响。
- `users.password_hash` 为 NOT NULL；`email` 为 citext UNIQUE。约 9,000 个账号未验证邮箱；约 55% 为 gmail.com。
- Google 项目 `tallybook-prod` 无 OAuth 客户端、无同意屏幕，只有创始人是 Owner。
- 回调地址必须逐个登记，PR 预览域名 `pr-<n>.preview...` 无法登记，且预览使用 staging 配置。
- 隐私政策未提及第三方登录，改动需创始人批准和外部律师审阅。本 plan 不碰。
- `main` 受保护：合并需 1 个评审 + CI 全绿；合并后自动部署 staging；生产 promote 由创始人或首席工程师手动执行，会跑 `npm run migrate`。
- 不能做：改 `tb.sid` 的 sameSite 或其他属性；改 CSP；改 `public/legal/`；改托管平台的环境变量；promote 到生产；改全局 git 配置。

## 4. 方案与关键决策
- **流程（三段式）**：
  1. `GET /auth/google`（或 `/auth/google/link`，需登录态）：生成 state、nonce、PKCE verifier；写入加密 cookie `tb.oauth`（httpOnly，生产 secure，`sameSite=lax`，`path=/auth/google`，maxAge 10 分钟），内容 `{state, nonce, verifier, intent: 'login'|'link', linkUserId?, exp}`；302 到 Google，参数 `scope=openid email profile`、`prompt=select_account`。
  2. `GET /auth/google/callback`（无 `tb.sid`）：用 `tb.oauth` 校验 state，用 openid-client 换 code、校验 ID token（iss、aud、exp、nonce）。成功后把 `{sub, email, email_verified, hd, name, intent, linkUserId, exp: now+5min}` 加密写回 `tb.oauth`，渲染 `google-continue.ejs`：仅含 `<meta http-equiv="refresh" content="0;url=/auth/google/finish">` 和一个兜底链接，无内联脚本。
  3. `GET /auth/google/finish`（由本站页面发起，同站，带 `tb.sid`）：解密并立即清除 `tb.oauth`，调用 `resolveGoogleLogin`，按结果 `req.session.regenerate` + `req.login`，或渲染提示页。link 意图要求 `req.user.id === linkUserId`。
- **加密 cookie**：AES-256-GCM，密钥用 HKDF-SHA256 从 `COOKIE_SIGNING_KEY` 派生（info=`tb.oauth`），不新增配置项。
- **关联判定**（`src/auth/identities.ts` 中的纯函数 `resolveGoogleLogin`，DB 读写另封装）：按 F1-4、F2-1～F2-4 的顺序判定。邮箱匹配用 citext 精确匹配，不做 Gmail 点号/加号归一化。
- **数据模型**：新表 `user_identities(id, user_id FK→users ON DELETE CASCADE, provider text, provider_subject text, email_at_link citext, created_at)`，唯一键 `(provider, provider_subject)`、`(user_id, provider)`。表名通用，便于以后接 #388。不存任何 Google token，不申请 offline access。
- **password_hash 改可空**；local 策略遇 NULL 时先跑一次 dummy argon2 verify 再失败，保持耗时一致。
- **踢会话**：`DELETE FROM session WHERE sess::jsonb -> 'passport' ->> 'user' = $1`，前提是 `serializeUser` 存的是 user id（步骤 0 核对）。
- **预览环境**：按钮和路由以"请求 host 等于 `GOOGLE_REDIRECT_URI` 的 host"为启用条件之一，预览自动关闭。
- **配置**：`config.ts` 新增可选的 `GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、`GOOGLE_REDIRECT_URI`（url）。`flags.ts` 新增 `GOOGLE_LOGIN`。开关开但配置缺失时：启动时打 warn 日志，按关闭处理，不让进程崩溃。
- **依赖**：`openid-client`，精确锁定版本。优先 v6；若与项目模块系统（CJS/ESM、tsconfig）不兼容，用 v5。属于可回退的小选择。
- **按钮样式**：按 Google 品牌指南，用本地静态 SVG 加 CSS，不加载 Google 的 GSI JS（避免改 CSP）。文案语言跟随现有页面。
- **Google-only 用户设密码**：复用现有重置 token 流程，不新增流程。
- 被否掉的方案：
  - 把 `tb.sid` 改成 lax：削弱全站 CSRF 纵深防御。
  - `passport-google-oauth20` + session 存 state：strict cookie 下 callback 拿不到 session。
  - 在 callback 里直接建会话并 302：重定向链仍按跨站处理，strict cookie 行为不可靠。
  - 服务端新建 pending 表存 callback 结果：多一张表和清理任务，加密 cookie 足够。
  - 给 `password_hash` 填随机不可用哈希、不改可空：语义含糊，以后难以区分"无密码"和"有密码"。

## 5. 改动清单与影响面

新建：
- `db/migrations/<timestamp>_google_login.ts`：建 `user_identities`，`password_hash` DROP NOT NULL；down：存在 NULL 时抛出明确错误，否则恢复 NOT NULL 并删表。
- `src/auth/google.ts`：openid-client 客户端（懒加载 discovery 并缓存）与 `/auth/google`、`/auth/google/link`、`/auth/google/callback`、`/auth/google/finish` 路由。
- `src/auth/identities.ts`：`resolveGoogleLogin` 及 identity 的读写、解除关联、踢会话。
- `src/auth/oauthCookie.ts`：`tb.oauth` 加解密与读写。
- `src/views/auth/google-continue.ejs`、`src/views/auth/google-link-required.ejs`、`src/views/auth/google-error.ejs`
- `src/views/partials/google-button.ejs`
- `public/img/google-g.svg`
- 关联/解除通知邮件模板：放在 `verify.ts` 邮件模板所在目录，沿用同一发信方式（步骤 0 确认位置）。
- `test/auth/google.test.ts`、`test/auth/identities.test.ts`、`test/auth/oauthCookie.test.ts`

修改：
- `package.json`、`package-lock.json`（加 openid-client）
- `src/config.ts`、`src/flags.ts`
- `src/auth/routes.ts`（挂载 Google 路由；新增 `POST /account/security/google/unlink`，若安全页路由不在此文件则改其所在文件）
- `src/auth/passport.ts`（NULL hash 处理）
- `src/auth/reset.ts`（仅当现有逻辑要求旧 hash 存在时才改）
- `src/views/auth/login.ejs`、`src/views/auth/signup.ejs`、`src/views/account/security.ejs`
- `.env.example`（若存在）：加 GOOGLE_* 和 `FEATURE_GOOGLE_LOGIN` 的空值

删除：无。

影响面四行：
- 会改：登录、注册、账号安全三个页面，密码登录与重置代码，配置和功能开关，约 11 个文件。
- 新增：`user_identities` 表（记录关联）；依赖 openid-client（标准 OIDC 校验）；关联通知邮件；临时 cookie `tb.oauth`（10 分钟，跨越 Google 跳转保存状态）；约 13 个新文件。
- 删除：无。
- 对外行为：`users.password_hash` 改为可空，生产在下一次 promote 时执行迁移；开关关闭时无可见变化；开关打开后从 Google 接收邮箱、姓名、`sub`；`tb.sid` 与 CSP 不变。

## 6. 步骤
0. 预检：`git status` 干净；`git config --local user.name` / `user.email` 存在（缺失则按停下条件问一次）；`git switch -c feat/google-login`。读 `src/app.ts`、`src/session.ts`、`src/auth/*.ts`、三个视图、`src/config.ts`、`src/flags.ts`、`package.json`、`tsconfig.json`、`knexfile`，核对第 3、4 项的假设（`serializeUser` 存 id、`trust proxy` 设置、邮件模板位置、注册页字段、模块系统）。产出：执行记录里写一行核对结果。
1. 加依赖：`npm install --save-exact openid-client@<版本>`。验证 `npx tsc --noEmit` 通过。
2. 迁移：写迁移文件。验证本地 `npm run migrate`，然后 `npx knex migrate:rollback`，再 `npm run migrate`，三步都成功（G-2）。
3. 配置与开关：改 `config.ts`、`flags.ts`、`.env.example`。验证 `tsc` 通过，现有测试全过。
4. `oauthCookie.ts` + 测试：往返、篡改、过期、密钥不同。验证 `npx jest test/auth/oauthCookie.test.ts`。
5. `identities.ts` + 测试：覆盖 F1-4、F2-1～F2-4 全部分支和踢会话。验证 `npx jest test/auth/identities.test.ts`。
6. `google.ts`、视图、按钮、路由挂载；用 `jest.mock` 替换 Google 客户端。测试覆盖 F1-1～F1-4、F2-5、F3-2。验证 `npx jest test/auth/google.test.ts`。
7. passport、reset、安全页、解除关联：测试覆盖 F1-5、F2-6、F3-1、F3-3、F3-4。
8. 本地手工检查：开关关闭时登录页无按钮；`npm run dev` 下各页面正常渲染。若已有本地 Google 客户端，再走一遍真实登录。
9. 全量验证：`npm run lint && npx tsc --noEmit && npx jest`（G-1）。
10. 把两份文档改为"执行中"并写执行记录；按逻辑分 2～4 个提交，只暂存第 5 项文件和两份文档；`git push -u origin feat/google-login`；`gh pr create`，正文附第 10 项的 Google 控制台清单。等 CI 全绿。
11. 合并后（等人工评审）：确认 staging 部署和 Playwright 冒烟测试通过（G-3）；等用户完成 staging 手工验证（F1-6）。
12. 收尾：两份文档改为"已完成"，写完整执行记录；在新分支提交这两份文档并开一个小 PR；给用户完成汇报。

总预计用时：AI 约 4 小时（含 CI 和 staging 部署等待，不含等人评审和用户回复）。

## 7. 风险处理与停下条件
风险去向：
- strict cookie 导致 callback 丢会话 → 改方案消除（三段式 + lax 临时 cookie）。
- 抢注攻击（他人先用受害者邮箱注册并设密码）→ 改方案（只对权威邮箱自动关联）+ 用户决定 2（清密码、踢会话）。
- 非 Gmail 邮箱的 `email_verified` 可能过期 → 用户决定 1。
- 预览环境回调地址无法登记 → 改方案消除（按 host 关闭）。
- 隐私政策未覆盖 → 用户决定 3（生产保持关闭）。
- Google 侧配置只能由创始人做 → 第 10 项。
- 生产迁移后回退：down 迁移在存在 NULL `password_hash` 时会失败。补救：先让这些用户通过重置邮件设置密码，或保留可空约束只回退代码。决定 3 选推荐时，生产不会产生 NULL 行。

停下条件（遇到就停，问用户）：
- 步骤 0 发现假设不成立：`serializeUser` 不是存 user id；注册页要求勾选条款或填写额外字段；`req.hostname` 在生产代理后不可信且无 `trust proxy`。
- 实现需要改 `tb.sid` 属性、CSP、`src/app.ts` 的安全中间件或 `public/legal/`。
- 改动超出第 5 项清单，或 NULL `password_hash` 的影响波及清单外 2 个以上文件。
- openid-client v6 和 v5 都无法接入当前模块系统。
- 本地无署名配置（只问一次名字和邮箱）。
- CI 或 staging 冒烟测试失败，且原因不在本次改动范围内。
- staging 手工验证时，`/auth/google/finish` 拿不到 `tb.sid` 或无法建会话。
- 工作区出现非本任务造成的改动。

## 8. 不做的事
- Microsoft、Apple 登录（#388）；会话迁移 Redis（#412）。
- 修改隐私政策或任何法务页面。
- 修改托管平台环境变量、Google 控制台、生产开关；promote 到生产。
- 在 PR 预览环境支持 Google 登录。
- Google One Tap / GSI JS、头像同步、Google 侧邮箱变更后自动更新 Tallybook 邮箱。
- 强制所有用户验证邮箱；批量处理现有 9,000 个未验证账号。
- 账号合并（两个 Tallybook 账号合一）。

## 9. 待用户决定的问题
1. 同邮箱已有账号是否自动关联（能回退）。推荐：仅权威邮箱（gmail.com/googlemail.com 或 `hd`=邮箱域名）自动关联，其余要求先密码登录后手动关联。理由：Google 对非 Gmail 邮箱的 `email_verified` 只代表某一时刻的验证。备选 A：`email_verified=true` 即关联。备选 B：一律手动关联。
2. 自动关联到未验证邮箱的老账号时是否清密码、踢会话（难回退）。推荐：清除并踢会话，在通知邮件里说明。理由：防止抢注者保留密码。代价：被清的 hash 不可恢复，用户需走重置邮件。备选：保留密码，只标记已验证。
3. 合并后生产是否保持关闭（难回退）。推荐：保持关闭，等隐私政策由律师修订、创始人批准，且同意屏幕发布为"正式"后再开。代价（若直接开启）：隐私政策与实际不符；产生 Google-only 账号后关闭开关，这些用户只能靠重置邮件登录。

## 10. 需要用户做的事
- 创始人，步骤 0 前后均可（需在步骤 11 前完成），约 30 分钟：在 `tallybook-prod` 中
  - 配置 OAuth 同意屏幕：用户类型 External；应用名 Tallybook；支持邮箱；授权网域 `tallybook.example.com`；隐私政策链接指向现有 privacy 页；范围只选 `openid`、`email`、`profile`；发布状态先保持 Testing，把参与 staging 验证的 Google 账号加为测试用户。
  - 创建 OAuth 客户端，类型 Web，回调地址三个：`http://localhost:3000/auth/google/callback`、`https://staging.tallybook.example.com/auth/google/callback`、`https://app.tallybook.example.com/auth/google/callback`。
- 创始人或首席工程师，拿到客户端后，约 10 分钟：在 staging 环境设置填 `GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、`GOOGLE_REDIRECT_URI=https://staging.tallybook.example.com/auth/google/callback`、`FEATURE_GOOGLE_LOGIN=true`；把客户端编号和密钥存入团队密码库供本地开发使用。生产暂不设置。
- 用户安排的评审者，步骤 10 后，约 30 分钟：评审并合并 PR。
- 用户本人，步骤 11 staging 部署后，约 10 分钟：在 staging 用一个测试用户 Google 账号做一次新注册登录；用一个已有密码账号在安全页做一次关联。

## 11. 变更记录
- v1 · 2026-10-07：初稿。

## 12. 执行记录
无

---

两份文档：

- 人读版：`docs/human/2026-10-07-google-login.md`
- 执行版：`docs/plan/2026-10-07-google-login.md`

要点：

- **方案**：做三件事。第一，在登录页和注册页加 Google 按钮。第二，老账号按邮箱自动关联，规则见决定 1。第三，账号安全页可以手动关联和解除关联。
- **技术难点**：`tb.sid` 是 `sameSite: 'strict'`，Google 跳回时浏览器不会带上它。我的处理是用一个 10 分钟的加密临时 cookie，加一个本站中转页，把登录过程接上。这样不用放宽现有 cookie 和 CSP。
- **需要你决定的 3 件事**：
  1. 自动关联只限 Gmail 和 Workspace 邮箱。
  2. 自动关联未验证邮箱的老账号时，清除原密码。
  3. 生产环境先保持关闭，等隐私政策改完再打开。
- **需要人做的事**：Google 控制台只有创始人能配置，staging 的环境变量也要创始人或首席工程师填写，我无法代劳。合计约 1 小时 20 分钟，其中 30 分钟是同事评审。

另外，本次会话我没能读到真实代码。`serializeUser` 存的内容、注册页有哪些字段等假设，我都写成了步骤 0 的核对项和停下条件。

回复"批准"即可开始。

</details>

## E · 计划 + 短摘要（消融组）

**批准人读到的内容** (514 字):

下面是完整方案和给批准人看的摘要（按项目约定单独成文件，文件名带 summary）。批准前我不会改任何代码。

# 摘要：Google 登录方案（待审批）

**做什么**：在登录页、注册页加入"使用 Google 登录"（OIDC 授权码流程，带 PKCE、state、nonce，依赖库为 openid-client）。已有的邮箱密码账号可以关联 Google，也可以只用 Google、不设密码。

**需要创始人操作**：
1. 在 GCP 配置同意屏幕和 OAuth 客户端，建议 staging 和生产分开。
2. 在托管平台写入 GOOGLE_CLIENT_ID、GOOGLE_CLIENT_SECRET、GOOGLE_REDIRECT_URI、FEATURE_GOOGLE_LOGIN。
3. 更新隐私政策，经外部法律顾问审阅。这是生产上线的硬性阻塞项。

**改动**：
- 新表 user_identities，以 Google 的 sub 为唯一键。
- password_hash 改为可空。
- 新增 /auth/google 和回调路由，在安全设置页提供关联、解除关联。
- 所有用到密码的地方兼容"无密码"账号。

**关键风险与对策**：
- tb.sid 是 sameSite=strict，Google 回调时浏览器不会携带。对策：OAuth 临时状态放进单独的短期 lax cookie；登录后经同源中转页跳转。不降低会话 cookie 的安全级别。
- 账号劫持：
  - 只有 gmail 或 Workspace 邮箱、且本地账号已验证时才自动关联。
  - 其他企业邮箱需要先用密码登录，再手动关联。
  - 约 9,000 个未验证账号，关联时清空原密码、注销所有会话，并发邮件通知。
- 预览环境无法注册动态回调域名，因此自动隐藏 Google 登录。
- CSP 不需要修改。

**上线**：功能开关默认关闭，先在 staging 验收，再在生产内部灰度，最后全量。回滚只需关闭开关；只用 Google 的用户可以通过"忘记密码"设置密码，继续登录。

**测试**：使用本地伪造的 OIDC provider，覆盖关联规则、token 校验和重放等用例；现有 CI 必须全部通过。

**待确认**：关联规则、staging 是否单独建客户端、隐私政策起草、依赖库选择。

<details>
<summary>展开给 agent 的计划 (2390 字)</summary>

下面是完整方案和给批准人看的摘要（按项目约定单独成文件，文件名带 summary）。批准前我不会改任何代码。

# 方案：登录页、注册页支持"使用 Google 登录"

状态：待审批（未改动任何代码）

## 1. 目标与范围

- 在 `/login` 和 `/signup` 增加"使用 Google 登录"按钮，用户可以用 Google 账号代替密码登录或注册。
- 与现有邮箱/密码账号兼容：已有账号可以关联 Google，关联后两种方式都能登录。也可以只用 Google、没有密码。
- 不在范围内：Microsoft/Apple 登录（#388），以及会话存储迁移到 Redis（#412）。不过数据结构按多提供方设计，#388 以后可以直接复用。

## 2. 前置条件（需要创始人操作，工程师无权限）

1. **OAuth 同意屏幕**：类型选 External，只申请 `openid email profile`（非敏感范围，不需要 Google 的安全审核，但需要品牌信息：应用名、Logo、首页、隐私政策链接，以及已授权域名 `tallybook.example.com`）。
2. **OAuth 客户端**（Web application）。建议 staging 和生产使用不同的客户端，最好放在不同的 GCP 项目里。现有的 `tallybook-prod` 是废弃实验留下的，可以继续用于生产，但需要先确认上面没有残留的 API key 或权限。
   - 生产重定向 URI：`https://app.tallybook.example.com/auth/google/callback`
   - staging 重定向 URI：`https://staging.tallybook.example.com/auth/google/callback`
   - 本地开发：`http://localhost:3000/auth/google/callback`（建议单独建一个开发用客户端）
3. **环境变量**：在托管平台写入 `GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、`GOOGLE_REDIRECT_URI`、`FEATURE_GOOGLE_LOGIN`，并在团队密码管理器里存一份本地开发用的值。密钥不进仓库。
4. **隐私政策**：现行政策写明"通过邮箱和密码创建账号"，没有提到第三方登录，也没有提到从 Google 接收数据（姓名、邮箱、Google 账号 ID）。上线生产前必须更新 `public/legal/privacy.html`，需要创始人批准，并经过外部法律顾问审阅。**这是生产上线的硬性阻塞项。** 我可以起草修改稿，但不会自行合并。

## 3. 技术设计

### 3.1 协议与依赖
- 使用 OpenID Connect 授权码流程，加 PKCE、`state` 和 `nonce`。
- 依赖库采用 `openid-client`：由它完成 discovery、JWKS 拉取，以及 ID token 的签名、`iss`、`aud`、`exp`、`nonce` 校验。不自己手写 JWT 校验。
- 新增 Passport 策略，与现有 local 策略并存。

### 3.2 数据库迁移（Knex）
1. 新表 `user_identities`：
   - 字段：`id`、`user_id`（外键指向 users，ON DELETE CASCADE）、`provider`（text）、`provider_subject`（Google 的 `sub`）、`email_at_link`、`created_at`、`last_login_at`
   - 唯一约束：`(provider, provider_subject)`、`(user_id, provider)`
2. 把 `users.password_hash` 改为可空，用于只用 Google 登录的账号。

这两项改动对旧版本代码向后兼容：在出现 Google-only 用户之前，表里不会有空的 password_hash。发布流程会先执行 `migrate`，再切流量，所以顺序没有问题。回滚脚本见 §6。

### 3.3 路由
- `GET /auth/google`：生成 state、nonce、PKCE verifier，然后 302 跳转到 Google。
  - 使用 GET 链接，不用表单。原因是 CSP 的 `form-action 'self'` 会拦截表单提交后跳转到外部域名。这样做也不需要放宽 CSP。
- `GET /auth/google/callback`：校验 state，用 code 换取 token，校验 ID token，再按 §3.5 的规则登录、注册或关联。
- `POST /account/security/google/unlink`：解除关联。受 CSRF 保护。如果解除后账号将没有任何登录方式（没有密码），则拒绝操作。
- "关联 Google"入口放在 `security.ejs`，供已登录用户使用。它走同一个流程，但在 state 里记录"关联意图"和当前 user_id。

### 3.4 关键坑：`sameSite: 'strict'`
从 accounts.google.com 跳回 callback 属于跨站的顶层导航，此时**浏览器不会携带 `tb.sid`**。因此：
- **state、nonce、PKCE verifier 不能放在 session 里。** 改为放在一个独立的短期 cookie（例如 `tb.oauth`）中：签名、httpOnly、secure、`sameSite: 'lax'`、`path=/auth/google`、有效期 10 分钟、用完即删。
- **登录成功后不能直接 302 到 `/dashboard`。** 这条跳转链起源于跨站，strict cookie 在 Chrome 等浏览器里仍然不会被发送，用户会看起来像没登录。做法是让 callback 返回一个同源中转页（`<meta http-equiv="refresh">` 加一个可点击的链接，不使用内联脚本，因此不需要改 CSP），由它再导航到目标页。
- **`tb.sid` 保持 `strict` 不变**，不为这个功能降低现有会话的安全级别。
- 关联流程同理：callback 拿不到 session，所以当前 user_id 由签名的 `tb.oauth` cookie 携带。中转页返回同源之后，还要再核对一次 session 中的用户是否与之一致。

### 3.5 账号匹配与关联规则（安全核心，需要审批确认）
匹配一律以 Google 的 `sub` 为准，不以邮箱为准，因为 Google 账号的邮箱可能变更。

1. 用 `(google, sub)` 能找到关联记录：直接登录该用户。
2. 找不到关联记录，且 Google 返回 `email_verified !== true`：拒绝，并提示用户改用邮箱密码登录或注册。
3. 找不到关联记录，且没有同邮箱的用户：新建用户。`password_hash = NULL`，`email_verified_at = now()`，`display_name` 取 Google 的 name。
4. 找不到关联记录，但存在同邮箱的用户：
   - **a. 自动关联**的条件：该账号已验证邮箱，并且 Google 对这个邮箱具有权威性，即邮箱是 `@gmail.com`，或 ID token 带有 `hd` 声明且与邮箱域名一致（Google Workspace）。
   - **b. 不自动关联**：企业域名邮箱、但不是 Workspace 账号的情况。任何人都能用别人的企业邮箱注册一个"非 Gmail 的 Google 账号"。此时提示用户"该邮箱已注册，请先用密码登录，再到安全设置里关联 Google"。
   - **c. 本地账号未验证邮箱**（约 9,000 个）：存在"抢注劫持"风险，即攻击者事先用受害者的邮箱注册了密码账号。建议做法：在满足 a 的条件下允许关联，但同时把 `email_verified_at` 设为当前时间、**清空 password_hash、注销该用户的所有现有会话**，并发邮件通知。如果是合法用户，他们之后可以通过"忘记密码"重新设置密码。
5. 每次关联或解除关联，都给账号邮箱发送通知邮件。
6. 登录成功时调用 `req.session.regenerate()`，防止会话固定攻击（Passport 0.6 及以上版本默认会这样做，需确认当前版本）。

### 3.6 兼容现有密码逻辑（password_hash 可能为 NULL）
- `passport.ts` 的 local 策略：hash 为 NULL 时，按"邮箱或密码错误"处理，返回与普通失败相同的提示和相同的耗时（对一个假 hash 做一次 argon2 校验），避免泄露账号是否存在。
- `reset.ts`：Google-only 用户也可以通过邮件 token 设置密码，以此作为兜底的登录方式。
- `security.ejs`：没有密码时，显示"设置密码"（走邮件验证），不显示"修改密码"。
- 全局搜索 `password_hash` 的所有使用处，逐一检查。

### 3.7 前端
- `login.ejs` 和 `signup.ejs` 加入 Google 按钮，遵循 Google 品牌规范。
- 按钮只在 `FEATURE_GOOGLE_LOGIN` 开启**且**当前请求的 host 与 `GOOGLE_REDIRECT_URI` 的域名一致时显示（见 §3.8）。
- 注册页如果有服务条款勾选，Google 注册也需要同等处理，可以放在中转页上确认。

### 3.8 预览环境
`pr-<n>.preview...` 是动态域名，无法在 Google 端逐个注册重定向 URI，而且预览环境用的是 staging 配置。处理方式：按 §3.7 的 host 校验，预览环境自动隐藏按钮，路由也返回 404。预览环境里不测 Google 登录，改在 staging 上测。

### 3.9 配置（`src/config.ts`）
在 zod 中新增上述变量。规则：`FEATURE_GOOGLE_LOGIN` 开启时，这些变量必填；关闭时可以不填。这样 CI 和现有环境不受影响。

## 4. 测试
- Jest 加 supertest，测试放在 `test/auth/google.test.ts`。用本地伪造的 OIDC provider（自签 JWKS）替代 Google，不访问外网。覆盖以下用例：
  - 新用户注册
  - 已关联用户登录
  - gmail 和 Workspace 账号自动关联
  - 非 Workspace 企业邮箱拒绝自动关联
  - 未验证本地账号的处理（清空密码、注销会话）
  - `email_verified=false`
  - state 不匹配、nonce 不匹配、ID token 过期、aud 错误
  - 回调重放
  - Google-only 用户用密码登录失败
  - 解除最后一种登录方式被拒绝
  - 功能开关关闭时返回 404
- Playwright 冒烟测试不接入真实 Google，只增加一条"开关开启时按钮可见"的检查。
- 已有约 650 个测试必须全部通过（lint、tsc、Jest）。

## 5. 上线步骤
1. 提交 PR：包含迁移、代码、测试，`FEATURE_GOOGLE_LOGIN` 默认关闭。评审通过且 CI 通过后合并，自动部署到 staging。
2. 创始人在 staging 配置客户端和变量，打开开关，团队人工验收（包括 Safari 和 Chrome 下 strict cookie 的表现）。
3. 隐私政策完成法务审阅并更新上线。
4. 提升到生产（此时开关仍关闭），先只对内部测试账号开启（同意屏幕在 Testing 状态下可以限定测试用户），观察日志后再全面开启。

## 6. 回滚
- 首选：关闭 `FEATURE_GOOGLE_LOGIN`。Google-only 用户可以通过"忘记密码"设置密码后继续使用，所以必须保证 `reset.ts` 先行支持 NULL hash。
- 迁移回滚：先确认不存在 password_hash 为 NULL 的用户，才能恢复 NOT NULL。因此这一步通常不执行，保留新表即可。

## 7. 需要你确认的问题
1. §3.5 的关联规则，尤其是 4b（企业邮箱不自动关联）和 4c（未验证账号关联时清空密码）是否接受？
2. staging 是否单独建一个 GCP 项目或 OAuth 客户端？
3. 隐私政策由我起草修改稿给你和法律顾问，可以吗？
4. 依赖库选 `openid-client` 是否同意？

</details>

---

方法和全部输出见 [benchmark/](../README.md)。
