# Certificate monitor

每 10 分钟尝试检查 2026 年英语组综合能力、笔译校赛证书。GitHub 调度可能延迟。
每累计 10 次自动运行发送一次状态邮件，无论证书是否发放；达到汇报次数时如检查失败，也发送失败状态。
计数从此功能上线后开始，只统计进入监测脚本的 schedule 运行（包括查询失败），不统计手动测试、未触发、取消、依赖安装失败或密钥缺失的任务。
只有在相应项目卡片中明确找到下载入口才发送发证提醒；任一项目发放并成功发信后停止监测。
若第 10 次恰好发放，发证提醒替代当次定期汇报，避免重复邮件。
公开计数文件只存运行次数和已汇报批次，不保存账号、密码、Cookie 或页面。
每次检查重新登录；不保存密码、Cookie、页面、证书文件或截图。

## 配置

在仓库 Settings → Secrets and variables → Actions 中添加 Repository secrets：

| 名称 | 内容 |
|---|---|
| SITE_USERNAME | 网站登录账号 |
| SITE_PASSWORD | 网站当前密码 |
| SMTP_USER | 开通 SMTP 的 QQ 邮箱地址 |
| SMTP_PASSWORD | QQ 邮箱 SMTP 授权码，不是邮箱密码 |
| MAIL_TO | 接收提醒的邮箱地址 |

缺少 Secrets 时仅报告未配置的名称，不运行登录。
配置后在 Actions → Certificate monitor → Run workflow 手动验证。
日志 pending 表示尚未发放；unknown 或任务失败需要人工检查，不会当作发证。
验证码、账号风控、站点改版或邮件故障均可能导致失败，不能保证持续登录或准点送达。
失败通知由你的 GitHub Actions 通知设置决定。

公开仓库只应包含此通用代码。勿将账号、密码、邮箱授权码或个人证书上传到仓库。
不触发 pull_request 工作流，不接受外部输入，GitHub token 只在检查步骤可用。
发信与状态保存不是跨服务事务；如果发信后 GitHub 状态写入失败，重试可能重复提醒。
